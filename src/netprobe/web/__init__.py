"""Flask web UI for NetProbe."""

import time
import threading
from pathlib import Path
from datetime import datetime, timezone

from flask import Flask, render_template, jsonify, send_file, request
from flask_socketio import SocketIO

from ..collector import Collector, Measurement
from ..config import ProbeConfig, VALVE_TARGETS
from ..prober import Prober
from ..analyzer import analyze_session
from ..reporter import generate_report

app = Flask(__name__)
app.config["SECRET_KEY"] = "netprobe-local"
socketio = SocketIO(app, cors_allowed_origins="*")

# App state
state = {
    "running": False,
    "session_id": None,
    "start_time": None,
    "collector": None,
    "prober": None,
    "emitter_thread": None,
}


def _get_collector() -> Collector:
    if state["collector"] is None:
        state["collector"] = Collector()
    return state["collector"]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    running = state["running"]
    data = {"running": running, "session_id": state["session_id"]}
    if running and state["prober"]:
        stats = state["prober"].stats
        elapsed = time.time() - state["start_time"] if state["start_time"] else 0
        data.update({
            "elapsed": int(elapsed),
            "sent": stats["sent"],
            "lost": stats["lost"],
            "loss_pct": (stats["lost"] / stats["sent"] * 100) if stats["sent"] > 0 else 0,
            "fast_mode": state["prober"]._anomaly.is_set(),
            "fast_switches": stats["fast_mode_switches"],
        })
    return jsonify(data)


@app.route("/api/start", methods=["POST"])
def api_start():
    if state["running"]:
        return jsonify({"error": "Already running"}), 400

    config = ProbeConfig()
    collector = _get_collector()
    session_id = collector.start_session()
    prober = Prober(config, collector)

    state["running"] = True
    state["session_id"] = session_id
    state["start_time"] = time.time()
    state["prober"] = prober

    prober.start()

    # Start emitter thread for live data
    t = threading.Thread(target=_emit_live_data, daemon=True)
    t.start()
    state["emitter_thread"] = t

    return jsonify({"session_id": session_id})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    if not state["running"]:
        return jsonify({"error": "Not running"}), 400

    state["prober"].stop()
    _get_collector().end_session()
    state["running"] = False

    session_id = state["session_id"]
    state["prober"] = None
    state["session_id"] = None
    state["start_time"] = None

    return jsonify({"session_id": session_id})


@app.route("/api/targets", methods=["POST"])
def api_add_target():
    if not state["running"] or not state["prober"]:
        return jsonify({"error": "Not running. Start monitoring first."}), 400

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    ip = (data.get("ip") or "").strip()

    if not name or not ip:
        return jsonify({"error": "Both name and ip are required"}), 400

    # Basic IP validation
    parts = ip.split(".")
    if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return jsonify({"error": "Invalid IP address"}), 400

    added = state["prober"].add_target(name, ip)
    if not added:
        return jsonify({"error": f"Target '{name}' already exists"}), 409

    return jsonify({"ok": True, "name": name, "ip": ip})


@app.route("/api/targets")
def api_targets():
    if not state["running"] or not state["prober"]:
        return jsonify([])
    targets = state["prober"].active_targets
    return jsonify([{"name": n, "ip": ip} for n, ip in targets.items()])


@app.route("/api/sessions")
def api_sessions():
    collector = _get_collector()
    sessions = collector.get_sessions()
    result = []
    for s in sessions:
        start = datetime.fromtimestamp(s["start_time"], tz=timezone.utc).astimezone()
        duration = None
        if s["end_time"]:
            duration = int(s["end_time"] - s["start_time"])
        result.append({
            "id": s["id"],
            "date": start.strftime("%Y-%m-%d"),
            "start": start.strftime("%H:%M:%S"),
            "duration": duration,
            "measurements": s["measurement_count"],
        })
    return jsonify(result)


@app.route("/api/sessions/<int:session_id>/report")
def api_report(session_id):
    collector = _get_collector()
    try:
        analysis = analyze_session(collector, session_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(f"netprobe_report_s{session_id}_{ts}.pdf")
    generate_report(analysis, out_path)

    return send_file(str(out_path.absolute()), as_attachment=True, download_name=out_path.name)


@app.route("/api/sessions/<int:session_id>/summary")
def api_session_summary(session_id):
    collector = _get_collector()
    try:
        r = analyze_session(collector, session_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    valve_names = set(VALVE_TARGETS.keys())
    targets = []
    for name, ts in r.target_stats.items():
        targets.append({
            "name": name,
            "ip": ts.ip,
            "is_valve": name in valve_names,
            "total": ts.total_pings,
            "lost": ts.lost_pings,
            "loss_pct": round(ts.loss_pct, 1),
            "avg_rtt": round(ts.avg_rtt, 1),
            "median_rtt": round(ts.median_rtt, 1),
            "p95_rtt": round(ts.p95_rtt, 1),
            "jitter": round(ts.jitter, 1),
        })

    return jsonify({
        "session_id": session_id,
        "duration": int(r.duration_s),
        "overall_loss": round(r.overall_loss_pct, 1),
        "overall_avg_rtt": round(r.overall_avg_rtt, 1),
        "overall_jitter": round(r.overall_jitter, 1),
        "valve_loss": round(r.valve_loss_pct, 1),
        "general_loss": round(r.general_loss_pct, 1),
        "diagnosis": r.diagnosis,
        "diagnosis_text": r.diagnosis_text,
        "problem_periods": len(r.problem_periods),
        "targets": targets,
    })


def _emit_live_data():
    """Emit live measurement data to connected WebSocket clients."""
    collector = _get_collector()
    last_count = 0

    while state["running"]:
        if state["session_id"] is None:
            break

        prober = state["prober"]
        if prober is None:
            break

        stats = prober.stats
        elapsed = time.time() - state["start_time"] if state["start_time"] else 0

        # Get recent measurements
        measurements = collector.get_measurements(state["session_id"])
        new_measurements = measurements[last_count:]
        last_count = len(measurements)

        # Build per-target live stats
        target_data = {}
        for m in measurements:
            if m.target_name not in target_data:
                target_data[m.target_name] = {"rtts": [], "lost": 0, "total": 0}
            td = target_data[m.target_name]
            td["total"] += 1
            if m.is_lost:
                td["lost"] += 1
            elif m.rtt_ms is not None:
                td["rtts"].append(m.rtt_ms)

        targets = {}
        for name, td in target_data.items():
            loss = (td["lost"] / td["total"] * 100) if td["total"] > 0 else 0
            avg = sum(td["rtts"]) / len(td["rtts"]) if td["rtts"] else 0
            last_rtt = None
            for m in reversed(new_measurements):
                if m.target_name == name and m.rtt_ms is not None:
                    last_rtt = round(m.rtt_ms, 1)
                    break
            targets[name] = {
                "loss_pct": round(loss, 1),
                "avg_rtt": round(avg, 1),
                "last_rtt": last_rtt,
                "total": td["total"],
                "lost": td["lost"],
            }

        # New data points for chart
        chart_points = []
        for m in new_measurements:
            chart_points.append({
                "time": m.timestamp,
                "target": m.target_name,
                "rtt": round(m.rtt_ms, 1) if m.rtt_ms is not None else None,
                "lost": m.is_lost,
            })

        socketio.emit("live_data", {
            "elapsed": int(elapsed),
            "sent": stats["sent"],
            "lost": stats["lost"],
            "loss_pct": round((stats["lost"] / stats["sent"] * 100) if stats["sent"] > 0 else 0, 1),
            "fast_mode": prober._anomaly.is_set(),
            "fast_switches": stats["fast_mode_switches"],
            "targets": targets,
            "chart_points": chart_points,
        })

        socketio.sleep(1)


def run_ui(host: str = "127.0.0.1", port: int = 5555):
    socketio.run(app, host=host, port=port, allow_unsafe_werkzeug=True)
