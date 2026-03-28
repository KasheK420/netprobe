"""Professional PDF report generator."""

import io
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from fpdf import FPDF

from .analyzer import AnalysisResult, TargetStats
from .config import (
    LATENCY_GOOD, LATENCY_WARN,
    LOSS_GOOD, LOSS_WARN,
    JITTER_GOOD, JITTER_WARN,
    VALVE_TARGETS,
)

# Colors
C_PRIMARY = (41, 65, 122)       # dark blue
C_ACCENT = (59, 130, 246)       # bright blue
C_GREEN = (34, 139, 34)
C_YELLOW = (204, 153, 0)
C_RED = (200, 30, 30)
C_GRAY = (120, 120, 120)
C_LIGHT_BG = (245, 247, 250)
C_WHITE = (255, 255, 255)
C_TEXT = (30, 30, 30)


def _status_color(value: float, good: float, warn: float) -> tuple[int, int, int]:
    if value <= good:
        return C_GREEN
    if value <= warn:
        return C_YELLOW
    return C_RED


def _fmt_duration(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def _fmt_dt(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


class ReportPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*C_GRAY)
        self.cell(0, 8, "NetProbe Network Quality Report", align="L")
        self.cell(0, 8, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*C_ACCENT)
        self.set_line_width(0.5)
        self.line(10, self.get_y(), self.w - 10, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*C_GRAY)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")


def generate_report(result: AnalysisResult, output_path: Path) -> Path:
    pdf = ReportPDF(orientation="P", unit="mm", format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)

    _add_cover_page(pdf, result)
    _add_executive_summary(pdf, result)
    _add_target_details(pdf, result)
    _add_timeline_graphs(pdf, result)
    _add_problem_periods(pdf, result)
    _add_methodology(pdf)

    pdf.output(str(output_path))
    return output_path


def _add_cover_page(pdf: ReportPDF, r: AnalysisResult) -> None:
    pdf.add_page()
    pdf.ln(50)

    pdf.set_font("Helvetica", "B", 32)
    pdf.set_text_color(*C_PRIMARY)
    pdf.cell(0, 15, "Network Quality Report", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)
    pdf.set_font("Helvetica", "", 14)
    pdf.set_text_color(*C_GRAY)
    pdf.cell(0, 8, "Internet Connection Stability Analysis", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(20)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*C_TEXT)

    info = [
        ("Date", r.start_dt.strftime("%B %d, %Y")),
        ("Time", f"{r.start_dt.strftime('%H:%M:%S')} — {r.end_dt.strftime('%H:%M:%S')}"),
        ("Duration", _fmt_duration(r.duration_s)),
        ("Targets Monitored", str(len(r.target_stats))),
        ("Total Measurements", str(sum(s.total_pings for s in r.target_stats.values()))),
        ("Session ID", str(r.session_id)),
    ]

    col_w = 80
    x_start = (pdf.w - col_w * 2) / 2
    for label, value in info:
        pdf.set_x(x_start)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(col_w, 8, label, new_x="END")
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(col_w, 8, value, new_x="LMARGIN", new_y="NEXT")

    # Diagnosis badge at bottom
    pdf.ln(25)
    diag = r.diagnosis
    diag_labels = {
        "ISP_ISSUE": "ISP ISSUE DETECTED",
        "VALVE_ISSUE": "VALVE SERVER ISSUE",
        "PARTIAL_ISP": "PARTIAL ISP ISSUE",
        "HEALTHY": "CONNECTION HEALTHY",
        "INTERMITTENT": "INTERMITTENT ISSUES",
    }
    diag_colors = {
        "ISP_ISSUE": C_RED,
        "VALVE_ISSUE": C_YELLOW,
        "PARTIAL_ISP": C_YELLOW,
        "HEALTHY": C_GREEN,
        "INTERMITTENT": C_YELLOW,
    }
    color = diag_colors.get(diag, C_GRAY)
    label = diag_labels.get(diag, diag)

    badge_w = 100
    x = (pdf.w - badge_w) / 2
    pdf.set_x(x)
    pdf.set_fill_color(*color)
    pdf.set_text_color(*C_WHITE)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(badge_w, 14, label, align="C", fill=True, new_x="LMARGIN", new_y="NEXT")


def _add_executive_summary(pdf: ReportPDF, r: AnalysisResult) -> None:
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*C_PRIMARY)
    pdf.cell(0, 12, "Executive Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Key metrics boxes
    metrics = [
        ("Packet Loss", f"{r.overall_loss_pct:.1f}%", _status_color(r.overall_loss_pct, LOSS_GOOD, LOSS_WARN)),
        ("Avg Latency", f"{r.overall_avg_rtt:.1f} ms", _status_color(r.overall_avg_rtt, LATENCY_GOOD, LATENCY_WARN)),
        ("Avg Jitter", f"{r.overall_jitter:.1f} ms", _status_color(r.overall_jitter, JITTER_GOOD, JITTER_WARN)),
    ]

    box_w = 55
    gap = 10
    x_start = (pdf.w - (box_w * 3 + gap * 2)) / 2
    y = pdf.get_y()

    for i, (label, value, color) in enumerate(metrics):
        x = x_start + i * (box_w + gap)
        pdf.set_xy(x, y)
        pdf.set_fill_color(*C_LIGHT_BG)
        pdf.rect(x, y, box_w, 28, style="F")

        pdf.set_xy(x, y + 3)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*C_GRAY)
        pdf.cell(box_w, 6, label, align="C", new_x="LMARGIN", new_y="NEXT")

        pdf.set_xy(x, y + 10)
        pdf.set_font("Helvetica", "B", 18)
        pdf.set_text_color(*color)
        pdf.cell(box_w, 12, value, align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_y(y + 35)

    # Valve vs General comparison
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*C_PRIMARY)
    pdf.cell(0, 8, "Valve Servers vs General Internet", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    _draw_comparison_table(pdf, r)
    pdf.ln(5)

    # Diagnosis
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*C_PRIMARY)
    pdf.cell(0, 8, "Diagnosis", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*C_TEXT)
    pdf.multi_cell(0, 6, r.diagnosis_text)

    if r.problem_periods:
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, f"Problem periods detected: {len(r.problem_periods)}", new_x="LMARGIN", new_y="NEXT")
        widespread = sum(1 for p in r.problem_periods if p.is_widespread)
        if widespread:
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(*C_RED)
            pdf.cell(0, 6, f"  {widespread} of these affected multiple targets simultaneously (ISP-level).", new_x="LMARGIN", new_y="NEXT")


def _draw_comparison_table(pdf: ReportPDF, r: AnalysisResult) -> None:
    valve_names = set(VALVE_TARGETS.keys())

    valve_stats = [s for n, s in r.target_stats.items() if n in valve_names]
    general_stats = [s for n, s in r.target_stats.items() if n not in valve_names]

    def _avg(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    rows = [
        ("", "Valve Servers", "General Internet"),
        ("Packet Loss",
         f"{_avg([s.loss_pct for s in valve_stats]):.1f}%",
         f"{_avg([s.loss_pct for s in general_stats]):.1f}%"),
        ("Avg Latency",
         f"{_avg([s.avg_rtt for s in valve_stats]):.1f} ms",
         f"{_avg([s.avg_rtt for s in general_stats]):.1f} ms"),
        ("Avg Jitter",
         f"{_avg([s.jitter for s in valve_stats]):.1f} ms",
         f"{_avg([s.jitter for s in general_stats]):.1f} ms"),
    ]

    col_widths = [50, 55, 55]
    x_start = (pdf.w - sum(col_widths)) / 2

    for i, row in enumerate(rows):
        pdf.set_x(x_start)
        for j, cell in enumerate(row):
            if i == 0:
                pdf.set_font("Helvetica", "B", 9)
                pdf.set_fill_color(*C_PRIMARY)
                pdf.set_text_color(*C_WHITE)
            elif j == 0:
                pdf.set_font("Helvetica", "B", 9)
                pdf.set_fill_color(*C_LIGHT_BG)
                pdf.set_text_color(*C_TEXT)
            else:
                pdf.set_font("Helvetica", "", 9)
                pdf.set_fill_color(*C_WHITE)
                pdf.set_text_color(*C_TEXT)

            pdf.cell(col_widths[j], 8, cell, border=1, fill=True, align="C", new_x="END")
        pdf.ln()


def _add_target_details(pdf: ReportPDF, r: AnalysisResult) -> None:
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*C_PRIMARY)
    pdf.cell(0, 12, "Detailed Target Metrics", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Table header
    headers = ["Target", "IP", "Pings", "Loss %", "Avg ms", "Med ms", "P95 ms", "Jitter ms"]
    col_w = [40, 28, 16, 17, 17, 17, 17, 20]
    x_start = (pdf.w - sum(col_w)) / 2

    pdf.set_x(x_start)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(*C_PRIMARY)
    pdf.set_text_color(*C_WHITE)
    for i, h in enumerate(headers):
        pdf.cell(col_w[i], 7, h, border=1, fill=True, align="C", new_x="END")
    pdf.ln()

    # Sort: Valve targets first, then general
    valve_names = set(VALVE_TARGETS.keys())
    sorted_targets = sorted(r.target_stats.values(), key=lambda s: (s.name not in valve_names, s.name))

    for ts in sorted_targets:
        pdf.set_x(x_start)
        pdf.set_font("Helvetica", "", 7.5)

        loss_color = _status_color(ts.loss_pct, LOSS_GOOD, LOSS_WARN)
        rtt_color = _status_color(ts.avg_rtt, LATENCY_GOOD, LATENCY_WARN)
        jitter_color = _status_color(ts.jitter, JITTER_GOOD, JITTER_WARN)

        row = [
            (ts.name, C_TEXT),
            (ts.ip, C_TEXT),
            (str(ts.total_pings), C_TEXT),
            (f"{ts.loss_pct:.1f}", loss_color),
            (f"{ts.avg_rtt:.1f}", rtt_color),
            (f"{ts.median_rtt:.1f}", C_TEXT),
            (f"{ts.p95_rtt:.1f}", C_TEXT),
            (f"{ts.jitter:.1f}", jitter_color),
        ]

        bg = C_LIGHT_BG if ts.name in valve_names else C_WHITE
        pdf.set_fill_color(*bg)

        for i, (val, color) in enumerate(row):
            pdf.set_text_color(*color)
            align = "L" if i == 0 else "C"
            pdf.cell(col_w[i], 7, val, border=1, fill=True, align=align, new_x="END")
        pdf.ln()

    pdf.ln(3)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(*C_GRAY)
    pdf.cell(0, 5, "Shaded rows = Valve/gaming servers. Color coding: green = good, yellow = warning, red = critical.", new_x="LMARGIN", new_y="NEXT")


def _add_timeline_graphs(pdf: ReportPDF, r: AnalysisResult) -> None:
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*C_PRIMARY)
    pdf.cell(0, 12, "Timeline Graphs", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # Latency timeline
    latency_img = _plot_latency_timeline(r)
    if latency_img:
        pdf.image(latency_img, x=10, w=pdf.w - 20)
        pdf.ln(5)

    # Packet loss timeline
    loss_img = _plot_loss_timeline(r)
    if loss_img:
        pdf.image(loss_img, x=10, w=pdf.w - 20)


def _plot_latency_timeline(r: AnalysisResult) -> str | None:
    fig, ax = plt.subplots(figsize=(10, 3.5), dpi=150)
    fig.patch.set_facecolor("#fafbfd")
    ax.set_facecolor("#fafbfd")

    valve_names = set(VALVE_TARGETS.keys())

    for name, stats in r.target_stats.items():
        ms_data = [(m.timestamp, m.rtt_ms) for m in r.measurements
                   if m.target_name == name and m.rtt_ms is not None]
        if not ms_data:
            continue
        times = [datetime.fromtimestamp(t, tz=timezone.utc).astimezone() for t, _ in ms_data]
        rtts = [rtt for _, rtt in ms_data]

        alpha = 0.9 if name in valve_names else 0.5
        lw = 1.2 if name in valve_names else 0.8
        ax.plot(times, rtts, label=name, alpha=alpha, linewidth=lw)

    ax.set_ylabel("Latency (ms)", fontsize=9)
    ax.set_title("Latency Over Time", fontsize=11, fontweight="bold", color="#293d7a")
    ax.legend(loc="upper right", fontsize=7, ncol=2)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.grid(True, alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()
    path = tempfile.mktemp(suffix=".png")
    fig.savefig(path, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return path


def _plot_loss_timeline(r: AnalysisResult) -> str | None:
    fig, ax = plt.subplots(figsize=(10, 2.5), dpi=150)
    fig.patch.set_facecolor("#fafbfd")
    ax.set_facecolor("#fafbfd")

    targets = list(r.target_stats.keys())
    target_idx = {name: i for i, name in enumerate(targets)}

    losses = [m for m in r.measurements if m.is_lost]
    if not losses:
        plt.close(fig)
        return None

    times = [datetime.fromtimestamp(m.timestamp, tz=timezone.utc).astimezone() for m in losses]
    y_pos = [target_idx[m.target_name] for m in losses]

    valve_names = set(VALVE_TARGETS.keys())
    colors = ["#c62828" if m.target_name in valve_names else "#e65100" for m in losses]

    ax.scatter(times, y_pos, c=colors, s=15, alpha=0.7, marker="|", linewidths=2)
    ax.set_yticks(range(len(targets)))
    ax.set_yticklabels(targets, fontsize=7)
    ax.set_title("Packet Loss Events", fontsize=11, fontweight="bold", color="#293d7a")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.grid(True, alpha=0.3, axis="x")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()
    path = tempfile.mktemp(suffix=".png")
    fig.savefig(path, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return path


def _add_problem_periods(pdf: ReportPDF, r: AnalysisResult) -> None:
    if not r.problem_periods:
        return

    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*C_PRIMARY)
    pdf.cell(0, 12, "Problem Periods", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*C_TEXT)
    pdf.multi_cell(0, 6,
        "The following time periods showed concentrated packet loss. "
        "Periods affecting multiple targets simultaneously suggest an ISP-level issue."
    )
    pdf.ln(3)

    headers = ["#", "Start", "End", "Duration", "Lost Pkts", "Targets", "Scope"]
    col_w = [8, 30, 30, 22, 20, 50, 25]
    x_start = (pdf.w - sum(col_w)) / 2

    pdf.set_x(x_start)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(*C_PRIMARY)
    pdf.set_text_color(*C_WHITE)
    for i, h in enumerate(headers):
        pdf.cell(col_w[i], 7, h, border=1, fill=True, align="C", new_x="END")
    pdf.ln()

    for idx, pp in enumerate(r.problem_periods, 1):
        pdf.set_x(x_start)
        pdf.set_font("Helvetica", "", 7.5)
        pdf.set_text_color(*C_TEXT)

        scope = "Widespread" if pp.is_widespread else "Isolated"
        scope_color = C_RED if pp.is_widespread else C_YELLOW
        targets_str = ", ".join(sorted(pp.affected_targets))
        if len(targets_str) > 30:
            targets_str = targets_str[:28] + "..."

        row = [
            str(idx),
            _fmt_dt(pp.start_time).split(" ")[1],
            _fmt_dt(pp.end_time).split(" ")[1],
            _fmt_duration(pp.duration_s),
            str(pp.loss_count),
            targets_str,
        ]

        bg = C_WHITE
        pdf.set_fill_color(*bg)
        for i, val in enumerate(row):
            pdf.cell(col_w[i], 7, val, border=1, fill=True, align="C", new_x="END")

        pdf.set_text_color(*scope_color)
        pdf.set_font("Helvetica", "B", 7.5)
        pdf.cell(col_w[6], 7, scope, border=1, fill=True, align="C", new_x="END")
        pdf.ln()


def _add_methodology(pdf: ReportPDF) -> None:
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*C_PRIMARY)
    pdf.cell(0, 12, "Methodology", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*C_TEXT)

    sections = [
        ("Measurement Method",
         "ICMP Echo Request (ping) packets were sent to each target at regular intervals. "
         "Each probe consists of a single ICMP packet with a 64-byte payload and a 2-second timeout. "
         "The tool uses an adaptive measurement interval: 2 seconds under normal conditions, "
         "increasing to 0.5 seconds when anomalies (packet loss or high jitter) are detected. "
         "This ensures high-resolution data during problem periods while minimizing overhead during stable operation."),

        ("Targets",
         "Two categories of targets were monitored simultaneously:\n"
         "- Valve Game Servers: CS2 relay servers in major European cities (Vienna, Frankfurt, Warsaw, Stockholm)\n"
         "- General Internet: Major public DNS resolvers (Google 8.8.8.8, Cloudflare 1.1.1.1, OpenDNS)\n\n"
         "By comparing results between categories, this report can distinguish between ISP-level issues "
         "(affecting all targets) and game-server-specific problems."),

        ("Metrics",
         "- Latency (RTT): Round-trip time in milliseconds. Lower is better. Values above 100ms typically cause noticeable lag.\n"
         "- Packet Loss: Percentage of packets that received no response within the timeout period. "
         "Any loss above 1% degrades real-time gaming experience significantly.\n"
         "- Jitter: Mean deviation between consecutive RTT measurements. High jitter causes inconsistent "
         "hit registration and rubber-banding. Values above 30ms are problematic for competitive gaming.\n"
         "- P95/P99: 95th and 99th percentile latency — worst-case latency excluding extreme outliers."),

        ("Thresholds",
         "Color coding used in this report:\n"
         "- Green (Good): Latency <50ms, Loss <1%, Jitter <10ms\n"
         "- Yellow (Warning): Latency 50-100ms, Loss 1-5%, Jitter 10-30ms\n"
         "- Red (Critical): Latency >100ms, Loss >5%, Jitter >30ms"),

        ("Tool",
         "This report was generated by NetProbe v1.0.0 — an open-source network quality monitoring tool. "
         "Source: github.com/KasheK420/netprobe"),
    ]

    for title, body in sections:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*C_PRIMARY)
        pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*C_TEXT)
        pdf.multi_cell(0, 5, body)
        pdf.ln(3)
