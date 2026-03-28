"""ICMP ping engine with adaptive interval."""

import time
import threading
from icmplib import ping as icmp_ping
from icmplib.exceptions import ICMPLibError

from .collector import Collector, Measurement
from .config import ProbeConfig, ANOMALY_COOLDOWN_S, ANOMALY_JITTER_MS, ANOMALY_LOSS_THRESHOLD


class Prober:
    def __init__(self, config: ProbeConfig, collector: Collector):
        self.config = config
        self.collector = collector
        self._stop = threading.Event()
        self._anomaly = threading.Event()
        self._last_stable = time.time()
        self._threads: list[threading.Thread] = []
        self._recent_rtts: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._stats = {"sent": 0, "lost": 0, "fast_mode_switches": 0}
        self._active_targets: dict[str, str] = {}

    @property
    def interval(self) -> float:
        if self._anomaly.is_set():
            return self.config.fast_interval
        return self.config.normal_interval

    @property
    def stats(self) -> dict:
        with self._lock:
            return dict(self._stats)

    def start(self) -> None:
        targets = self.config.all_targets
        with self._lock:
            self._active_targets = dict(targets)
        for name, ip in targets.items():
            t = threading.Thread(target=self._probe_loop, args=(name, ip), daemon=True)
            t.start()
            self._threads.append(t)

    @property
    def active_targets(self) -> dict[str, str]:
        with self._lock:
            return dict(self._active_targets)

    def add_target(self, name: str, ip: str) -> bool:
        with self._lock:
            if name in self._active_targets:
                return False
            self._active_targets[name] = ip
        t = threading.Thread(target=self._probe_loop, args=(name, ip), daemon=True)
        t.start()
        self._threads.append(t)
        return True

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=5)

    def _probe_loop(self, name: str, ip: str) -> None:
        while not self._stop.is_set():
            ts = time.time()
            rtt_ms = None
            is_lost = True

            try:
                result = icmp_ping(ip, count=1, timeout=self.config.ping_timeout, privileged=True)
                if result.packets_received > 0:
                    rtt_ms = result.avg_rtt
                    is_lost = False
            except (ICMPLibError, OSError):
                pass

            m = Measurement(
                timestamp=ts,
                target_name=name,
                target_ip=ip,
                rtt_ms=rtt_ms,
                is_lost=is_lost,
            )
            self.collector.record(m)

            with self._lock:
                self._stats["sent"] += 1
                if is_lost:
                    self._stats["lost"] += 1

            self._update_anomaly_state(name, rtt_ms, is_lost)

            wait = self.interval
            self._stop.wait(timeout=wait)

    def _update_anomaly_state(self, name: str, rtt_ms: float | None, is_lost: bool) -> None:
        with self._lock:
            if name not in self._recent_rtts:
                self._recent_rtts[name] = []

            if rtt_ms is not None:
                window = self._recent_rtts[name]
                window.append(rtt_ms)
                if len(window) > 10:
                    window.pop(0)

            triggered = False

            if is_lost:
                triggered = True

            if not triggered and len(self._recent_rtts.get(name, [])) >= 3:
                rtts = self._recent_rtts[name][-5:]
                jitter = max(rtts) - min(rtts)
                if jitter > ANOMALY_JITTER_MS:
                    triggered = True

            now = time.time()
            if triggered:
                if not self._anomaly.is_set():
                    self._stats["fast_mode_switches"] += 1
                self._anomaly.set()
                self._last_stable = now
            elif now - self._last_stable > ANOMALY_COOLDOWN_S:
                self._anomaly.clear()
