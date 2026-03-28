"""CLI interface for NetProbe."""

import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.text import Text

from . import __version__
from .analyzer import analyze_session
from .collector import Collector
from .config import ProbeConfig
from .prober import Prober
from .reporter import generate_report

console = Console()


@click.group()
@click.version_option(__version__, prog_name="netprobe")
def cli():
    """NetProbe — Network quality monitor for gaming sessions."""


@cli.command()
@click.option("--target", "-t", multiple=True, help="Extra target in format 'name:ip' (e.g. 'MyServer:1.2.3.4')")
@click.option("--no-valve", is_flag=True, help="Skip Valve server targets")
@click.option("--no-general", is_flag=True, help="Skip general internet targets")
@click.option("--output", "-o", type=click.Path(), default=None, help="Output PDF path (default: ./netprobe_report_<timestamp>.pdf)")
def start(target, no_valve, no_general, output):
    """Start monitoring. Press Ctrl+C to stop and generate report."""
    config = ProbeConfig()

    if no_valve:
        config.valve_targets = {}
    if no_general:
        config.general_targets = {}

    for t in target:
        if ":" not in t:
            console.print(f"[red]Invalid target format: {t}. Use 'name:ip'[/red]")
            sys.exit(1)
        name, ip = t.split(":", 1)
        config.extra_targets[name.strip()] = ip.strip()

    if not config.all_targets:
        console.print("[red]No targets configured. Add at least one target.[/red]")
        sys.exit(1)

    collector = Collector()
    session_id = collector.start_session()
    prober = Prober(config, collector)

    console.print()
    console.print(f"[bold blue]NetProbe v{__version__}[/bold blue]")
    console.print(f"Session #{session_id} started at {datetime.now().strftime('%H:%M:%S')}")
    console.print(f"Monitoring [bold]{len(config.all_targets)}[/bold] targets")
    console.print()
    console.print("[dim]Press Ctrl+C to stop and generate report[/dim]")
    console.print()

    prober.start()

    stop_event = False

    def handle_stop(sig, frame):
        nonlocal stop_event
        stop_event = True

    signal.signal(signal.SIGINT, handle_stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, handle_stop)

    try:
        with Live(console=console, refresh_per_second=2) as live:
            while not stop_event:
                stats = prober.stats
                sent = stats["sent"]
                lost = stats["lost"]
                loss_pct = (lost / sent * 100) if sent > 0 else 0.0
                mode = "[red bold]FAST[/red bold]" if prober._anomaly.is_set() else "[green]normal[/green]"

                table = Table(show_header=False, box=None, padding=(0, 2))
                table.add_column(style="bold")
                table.add_column()

                elapsed = time.time() - collector._conn.execute(
                    "SELECT start_time FROM sessions WHERE id = ?",
                    (session_id,)
                ).fetchone()[0]
                m, s = divmod(int(elapsed), 60)
                h, m = divmod(m, 60)

                table.add_row("Elapsed", f"{h:02d}:{m:02d}:{s:02d}")
                table.add_row("Sent", str(sent))
                table.add_row("Lost", f"[red]{lost}[/red]" if lost > 0 else "0")
                table.add_row("Loss", f"[red]{loss_pct:.1f}%[/red]" if loss_pct > 1 else f"[green]{loss_pct:.1f}%[/green]")
                table.add_row("Mode", mode)
                table.add_row("Fast switches", str(stats["fast_mode_switches"]))

                live.update(table)
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass

    console.print()
    console.print("[yellow]Stopping measurement...[/yellow]")
    prober.stop()
    collector.end_session()

    # Generate report
    console.print("[blue]Analyzing data...[/blue]")
    try:
        result = analyze_session(collector, session_id)
    except ValueError as e:
        console.print(f"[red]Analysis failed: {e}[/red]")
        collector.close()
        sys.exit(1)

    if output:
        out_path = Path(output)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path(f"netprobe_report_{ts}.pdf")

    console.print("[blue]Generating PDF report...[/blue]")
    generate_report(result, out_path)
    collector.close()

    console.print()
    console.print(f"[bold green]Report saved: {out_path.absolute()}[/bold green]")
    console.print()

    # Quick summary
    console.print(f"  Duration:    {int(result.duration_s // 60)}m {int(result.duration_s % 60)}s")
    console.print(f"  Packet Loss: {result.overall_loss_pct:.1f}%")
    console.print(f"  Avg Latency: {result.overall_avg_rtt:.1f} ms")
    console.print(f"  Diagnosis:   {result.diagnosis}")
    console.print()


@cli.command()
def sessions():
    """List past measurement sessions."""
    collector = Collector()
    sess = collector.get_sessions()
    collector.close()

    if not sess:
        console.print("[dim]No sessions found.[/dim]")
        return

    table = Table(title="Measurement Sessions")
    table.add_column("ID", style="bold")
    table.add_column("Date")
    table.add_column("Start")
    table.add_column("Duration")
    table.add_column("Measurements")
    table.add_column("Note")

    for s in sess:
        start = datetime.fromtimestamp(s["start_time"], tz=timezone.utc).astimezone()
        if s["end_time"]:
            dur = s["end_time"] - s["start_time"]
            m, sec = divmod(int(dur), 60)
            h, m = divmod(m, 60)
            dur_str = f"{h:02d}:{m:02d}:{sec:02d}"
        else:
            dur_str = "[yellow]running[/yellow]"

        table.add_row(
            str(s["id"]),
            start.strftime("%Y-%m-%d"),
            start.strftime("%H:%M:%S"),
            dur_str,
            str(s["measurement_count"]),
            s["note"] or "",
        )

    console.print(table)


@cli.command()
@click.argument("session_id", type=int)
@click.option("--output", "-o", type=click.Path(), default=None, help="Output PDF path")
def report(session_id, output):
    """Generate PDF report from a past session."""
    collector = Collector()

    try:
        result = analyze_session(collector, session_id)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        collector.close()
        sys.exit(1)

    if output:
        out_path = Path(output)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path(f"netprobe_report_session{session_id}_{ts}.pdf")

    console.print("[blue]Generating PDF report...[/blue]")
    generate_report(result, out_path)
    collector.close()

    console.print(f"[bold green]Report saved: {out_path.absolute()}[/bold green]")


@cli.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", "-p", default=5555, type=int, help="Port to listen on")
@click.option("--no-browser", is_flag=True, help="Don't auto-open browser")
def ui(host, port, no_browser):
    """Launch web UI dashboard."""
    from .web import run_ui
    import webbrowser

    url = f"http://{host}:{port}"
    console.print()
    console.print(f"[bold blue]NetProbe Web UI[/bold blue]")
    console.print(f"Open [link={url}]{url}[/link] in your browser")
    console.print("[dim]Press Ctrl+C to stop[/dim]")
    console.print()

    if not no_browser:
        webbrowser.open(url)

    run_ui(host=host, port=port)


if __name__ == "__main__":
    cli()
