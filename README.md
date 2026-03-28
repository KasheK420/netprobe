# NetProbe

Network quality monitor for gaming sessions. Measures packet loss, latency, and jitter in the background while you play. Generates professional PDF reports suitable for ISP complaints.

## Why?

Getting 90% packet loss every other round in CS2 on a 600/200 Mbit fiber connection? NetProbe runs silently in the background, collects hard data, and produces a report that shows your ISP exactly what's happening.

## Features

- **Adaptive measurement** — 2s interval normally, 0.5s during anomalies for high-resolution data when it matters
- **Dual-target monitoring** — Valve CS2 servers + general internet (Google, Cloudflare DNS) to pinpoint whether the issue is your ISP or Valve
- **Automatic diagnosis** — determines if packet loss is ISP-wide, Valve-specific, or intermittent
- **Professional PDF reports** — color-coded metrics, latency/loss timeline graphs, problem period analysis
- **Minimal footprint** — ~5 MB RAM, <1% CPU, negligible bandwidth. Won't affect your game
- **Session history** — all data stored in SQLite, regenerate reports anytime

## Installation

```bash
pip install -e .
```

Or with a virtual environment:

```bash
python -m venv .venv
.venv\Scripts\activate    # Windows
# source .venv/bin/activate  # Linux/Mac
pip install -e .
```

> **Note:** On Linux, ICMP pings may require root or `sudo`. On Windows, it works without admin.

## Usage

### Start monitoring

```bash
# Basic — monitors Valve EU servers + Google/Cloudflare DNS
netprobe start

# Add custom target (e.g., your ISP's gateway)
netprobe start -t "ISP Gateway:192.168.1.1"

# Skip Valve targets (general internet only)
netprobe start --no-valve

# Custom output path
netprobe start -o my_report.pdf
```

Press **Ctrl+C** to stop. A PDF report is generated automatically.

### View past sessions

```bash
netprobe sessions
```

### Regenerate report from past data

```bash
netprobe report 1
netprobe report 1 -o custom_name.pdf
```

## Report Contents

1. **Cover page** — date, duration, overall diagnosis badge
2. **Executive summary** — key metrics (loss, latency, jitter) with color-coded status, Valve vs. general comparison
3. **Detailed target metrics** — per-server stats table with P95/P99 latency
4. **Timeline graphs** — latency over time, packet loss events
5. **Problem periods** — clustered loss events with scope analysis (isolated vs. widespread)
6. **Methodology** — explains how measurements were taken (useful for ISP support)

## Monitored Targets

### Valve CS2 Servers
| Name | IP |
|------|-----|
| Valve Vienna | 155.133.226.71 |
| Valve Frankfurt | 155.133.248.34 |
| Valve Warsaw | 185.25.182.1 |
| Valve Stockholm | 155.133.254.34 |

### General Internet
| Name | IP |
|------|-----|
| Google DNS | 8.8.8.8 |
| Cloudflare DNS | 1.1.1.1 |
| OpenDNS | 208.67.222.222 |

## Data Storage

All measurement data is stored in `~/.netprobe/netprobe.db` (SQLite). Delete it to start fresh.

## License

MIT
