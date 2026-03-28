"""Default configuration and target definitions."""

from dataclasses import dataclass, field

VALVE_TARGETS: dict[str, str] = {
    "Valve Vienna": "155.133.226.71",
    "Valve Frankfurt": "155.133.248.34",
    "Valve Warsaw": "185.25.182.1",
    "Valve Stockholm": "155.133.254.34",
}

GENERAL_TARGETS: dict[str, str] = {
    "Google DNS": "8.8.8.8",
    "Cloudflare DNS": "1.1.1.1",
    "OpenDNS": "208.67.222.222",
}

# Adaptive interval thresholds
NORMAL_INTERVAL: float = 2.0
FAST_INTERVAL: float = 0.5
ANOMALY_LOSS_THRESHOLD: int = 1  # any loss triggers fast mode
ANOMALY_JITTER_MS: float = 30.0  # jitter above this triggers fast mode
ANOMALY_COOLDOWN_S: float = 10.0  # seconds of stability before returning to normal

# Ping settings
PING_TIMEOUT: float = 2.0  # seconds
PING_COUNT: int = 1  # pings per probe cycle
PING_PAYLOAD_SIZE: int = 64  # bytes

# Report thresholds for color coding
LATENCY_GOOD: float = 50.0
LATENCY_WARN: float = 100.0
LOSS_GOOD: float = 1.0
LOSS_WARN: float = 5.0
JITTER_GOOD: float = 10.0
JITTER_WARN: float = 30.0


@dataclass
class ProbeConfig:
    valve_targets: dict[str, str] = field(default_factory=lambda: dict(VALVE_TARGETS))
    general_targets: dict[str, str] = field(default_factory=lambda: dict(GENERAL_TARGETS))
    extra_targets: dict[str, str] = field(default_factory=dict)
    normal_interval: float = NORMAL_INTERVAL
    fast_interval: float = FAST_INTERVAL
    ping_timeout: float = PING_TIMEOUT

    @property
    def all_targets(self) -> dict[str, str]:
        return {**self.valve_targets, **self.general_targets, **self.extra_targets}
