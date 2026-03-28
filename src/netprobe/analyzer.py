"""Statistical analysis of measurement data."""

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .collector import Collector, Measurement
from .config import VALVE_TARGETS


@dataclass
class TargetStats:
    name: str
    ip: str
    total_pings: int = 0
    lost_pings: int = 0
    rtts: list[float] = field(default_factory=list)

    @property
    def loss_pct(self) -> float:
        return (self.lost_pings / self.total_pings * 100) if self.total_pings > 0 else 0.0

    @property
    def avg_rtt(self) -> float:
        return statistics.mean(self.rtts) if self.rtts else 0.0

    @property
    def median_rtt(self) -> float:
        return statistics.median(self.rtts) if self.rtts else 0.0

    @property
    def min_rtt(self) -> float:
        return min(self.rtts) if self.rtts else 0.0

    @property
    def max_rtt(self) -> float:
        return max(self.rtts) if self.rtts else 0.0

    @property
    def p95_rtt(self) -> float:
        if len(self.rtts) < 2:
            return self.avg_rtt
        sorted_rtts = sorted(self.rtts)
        idx = int(len(sorted_rtts) * 0.95)
        return sorted_rtts[min(idx, len(sorted_rtts) - 1)]

    @property
    def p99_rtt(self) -> float:
        if len(self.rtts) < 2:
            return self.avg_rtt
        sorted_rtts = sorted(self.rtts)
        idx = int(len(sorted_rtts) * 0.99)
        return sorted_rtts[min(idx, len(sorted_rtts) - 1)]

    @property
    def jitter(self) -> float:
        if len(self.rtts) < 2:
            return 0.0
        diffs = [abs(self.rtts[i + 1] - self.rtts[i]) for i in range(len(self.rtts) - 1)]
        return statistics.mean(diffs)

    @property
    def stdev_rtt(self) -> float:
        if len(self.rtts) < 2:
            return 0.0
        return statistics.stdev(self.rtts)


@dataclass
class ProblemPeriod:
    start_time: float
    end_time: float
    loss_count: int
    affected_targets: set[str] = field(default_factory=set)

    @property
    def duration_s(self) -> float:
        return self.end_time - self.start_time

    @property
    def is_widespread(self) -> bool:
        return len(self.affected_targets) > 1


@dataclass
class AnalysisResult:
    session_id: int
    start_time: float
    end_time: float
    duration_s: float
    target_stats: dict[str, TargetStats]
    problem_periods: list[ProblemPeriod]
    measurements: list[Measurement]

    @property
    def overall_loss_pct(self) -> float:
        total = sum(s.total_pings for s in self.target_stats.values())
        lost = sum(s.lost_pings for s in self.target_stats.values())
        return (lost / total * 100) if total > 0 else 0.0

    @property
    def overall_avg_rtt(self) -> float:
        all_rtts = [r for s in self.target_stats.values() for r in s.rtts]
        return statistics.mean(all_rtts) if all_rtts else 0.0

    @property
    def overall_jitter(self) -> float:
        all_rtts = [r for s in self.target_stats.values() for r in s.rtts]
        if len(all_rtts) < 2:
            return 0.0
        diffs = [abs(all_rtts[i + 1] - all_rtts[i]) for i in range(len(all_rtts) - 1)]
        return statistics.mean(diffs)

    @property
    def valve_loss_pct(self) -> float:
        valve_names = set(VALVE_TARGETS.keys())
        total = sum(s.total_pings for n, s in self.target_stats.items() if n in valve_names)
        lost = sum(s.lost_pings for n, s in self.target_stats.items() if n in valve_names)
        return (lost / total * 100) if total > 0 else 0.0

    @property
    def general_loss_pct(self) -> float:
        valve_names = set(VALVE_TARGETS.keys())
        total = sum(s.total_pings for n, s in self.target_stats.items() if n not in valve_names)
        lost = sum(s.lost_pings for n, s in self.target_stats.items() if n not in valve_names)
        return (lost / total * 100) if total > 0 else 0.0

    @property
    def diagnosis(self) -> str:
        valve_loss = self.valve_loss_pct
        general_loss = self.general_loss_pct

        if general_loss > 5 and valve_loss > 5:
            return "ISP_ISSUE"
        if valve_loss > 5 and general_loss < 2:
            return "VALVE_ISSUE"
        if general_loss > 5 and valve_loss < 2:
            return "PARTIAL_ISP"
        if self.overall_loss_pct < 1:
            return "HEALTHY"
        return "INTERMITTENT"

    @property
    def diagnosis_text(self) -> str:
        texts = {
            "ISP_ISSUE": (
                "Significant packet loss detected across ALL targets including major DNS providers. "
                "This strongly indicates an issue with your Internet Service Provider's network. "
                "The problem is not specific to gaming servers."
            ),
            "VALVE_ISSUE": (
                "Packet loss is concentrated on Valve/gaming servers while general internet connectivity "
                "remains stable. This suggests routing issues to Valve's network or Valve server problems."
            ),
            "PARTIAL_ISP": (
                "Packet loss detected on general internet targets but not on gaming servers. "
                "This may indicate intermittent ISP issues that could affect gaming unpredictably."
            ),
            "HEALTHY": (
                "Network quality is within acceptable parameters. No significant packet loss or "
                "latency issues detected during the measurement period."
            ),
            "INTERMITTENT": (
                "Low-level intermittent issues detected. While not critical, these may cause "
                "occasional micro-stutters or lag spikes during gameplay."
            ),
        }
        return texts.get(self.diagnosis, "Unable to determine root cause.")

    @property
    def start_dt(self) -> datetime:
        return datetime.fromtimestamp(self.start_time, tz=timezone.utc).astimezone()

    @property
    def end_dt(self) -> datetime:
        return datetime.fromtimestamp(self.end_time, tz=timezone.utc).astimezone()


def analyze_session(collector: Collector, session_id: int) -> AnalysisResult:
    session = collector.get_session(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")

    measurements = collector.get_measurements(session_id)
    if not measurements:
        raise ValueError(f"No measurements for session {session_id}")

    # Per-target stats
    target_stats: dict[str, TargetStats] = {}
    for m in measurements:
        if m.target_name not in target_stats:
            target_stats[m.target_name] = TargetStats(name=m.target_name, ip=m.target_ip)
        ts = target_stats[m.target_name]
        ts.total_pings += 1
        if m.is_lost:
            ts.lost_pings += 1
        elif m.rtt_ms is not None:
            ts.rtts.append(m.rtt_ms)

    # Detect problem periods (clusters of packet loss)
    problem_periods = _detect_problem_periods(measurements)

    start_time = session["start_time"]
    end_time = session["end_time"] or measurements[-1].timestamp

    return AnalysisResult(
        session_id=session_id,
        start_time=start_time,
        end_time=end_time,
        duration_s=end_time - start_time,
        target_stats=target_stats,
        problem_periods=problem_periods,
        measurements=measurements,
    )


def _detect_problem_periods(measurements: list[Measurement], gap_threshold: float = 15.0) -> list[ProblemPeriod]:
    losses = [m for m in measurements if m.is_lost]
    if not losses:
        return []

    periods: list[ProblemPeriod] = []
    current_start = losses[0].timestamp
    current_end = losses[0].timestamp
    current_count = 1
    current_targets = {losses[0].target_name}

    for loss in losses[1:]:
        if loss.timestamp - current_end <= gap_threshold:
            current_end = loss.timestamp
            current_count += 1
            current_targets.add(loss.target_name)
        else:
            periods.append(ProblemPeriod(
                start_time=current_start,
                end_time=current_end,
                loss_count=current_count,
                affected_targets=current_targets,
            ))
            current_start = loss.timestamp
            current_end = loss.timestamp
            current_count = 1
            current_targets = {loss.target_name}

    periods.append(ProblemPeriod(
        start_time=current_start,
        end_time=current_end,
        loss_count=current_count,
        affected_targets=current_targets,
    ))

    return periods
