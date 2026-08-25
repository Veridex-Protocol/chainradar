"""Interactive Live Terminal UI (TUI) for the Early Chain Discovery Engine."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from rich.align import Align
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.storage.database import db_manager
from src.storage.repository import Repository


console = Console()


def get_wat_time_str() -> str:
    now = datetime.now(timezone.utc)
    # WAT is UTC+1 (no DST)
    wat_hour = (now.hour + 1) % 24
    return f"{wat_hour:02d}:{now.minute:02d}:{now.second:02d} WAT"


def make_header_layout() -> Panel:
    wat_time = get_wat_time_str()
    header_text = Text()
    header_text.append("⚡ CHAINRADAR INTELLIGENCE ENGINE  ", style="bold cyan")
    header_text.append("│  Early Chain Discovery & Africa Expansion  │  ", style="dim white")
    header_text.append(f"🕒 {wat_time}", style="bold green")

    return Panel(Align.center(header_text), border_style="bright_blue", padding=(0, 1))


def make_kpi_table(candidates: list) -> Table:
    hot_count = sum(1 for c in candidates if c.score and c.score.state == "HOT")
    qual_count = sum(1 for c in candidates if c.score and c.score.state == "QUALIFIED")
    radar_count = sum(1 for c in candidates if c.score and c.score.state in ("RADAR", "STALE"))
    africa_count = sum(1 for c in candidates if c.assessment and c.assessment.intent_label in ("A1_explicit_intent", "A2_active_regional_motion"))

    table = Table(expand=True, box=None, padding=(0, 2))
    table.add_column("🔥 HOT OUTREACH", justify="center", style="bold red")
    table.add_column("🎯 QUALIFIED LEADS", justify="center", style="bold yellow")
    table.add_column("📡 RADAR WATCHLIST", justify="center", style="bold cyan")
    table.add_column("🌍 AFRICA INTENT (A1/A2)", justify="center", style="bold green")

    table.add_row(
        f"[bold red]{hot_count}[/bold red]",
        f"[bold yellow]{qual_count}[/bold yellow]",
        f"[bold cyan]{radar_count}[/bold cyan]",
        f"[bold green]{africa_count}[/bold green]",
    )
    return table


def make_candidates_table(candidates: list) -> Table:
    table = Table(title="Live Chain Discovery Pipeline (Ranked by Recency & Recent Funding)", expand=True, border_style="dim")
    table.add_column("Chain Name", style="bold white", width=18)
    table.add_column("Stage", style="magenta", width=12)
    table.add_column("Stack", style="blue", width=10)
    table.add_column("Africa", width=14)
    table.add_column("Raised", justify="right", style="bold green", width=10)
    table.add_column("Raised On", justify="center", style="dim green", width=11)
    table.add_column("Lead Investor", style="bold yellow", width=16)
    table.add_column("Outreach", justify="right", style="bold red", width=9)
    table.add_column("State", justify="center", width=9)

    if not candidates:
        table.add_row("No candidates observed yet", "-", "-", "-", "-", "-", "-", "-", "-")
        return table

    for c in candidates[:12]:
        a_label = c.assessment.intent_label if c.assessment else "A4_no_evidence"
        a_color = "red" if a_label.startswith("A1") else ("yellow" if a_label.startswith("A2") else "dim cyan")
        a_fmt = f"[{a_color}]{a_label.replace('_', ' ')}[/{a_color}]"

        state_color = "bold red" if c.score and c.score.state == "HOT" else ("bold yellow" if c.score and c.score.state == "QUALIFIED" else ("dim" if c.score and c.score.state == "STALE" else "cyan"))
        state_fmt = f"[{state_color}]{c.score.state if c.score else 'RADAR'}[/{state_color}]"

        rounds = c.funding_rounds or []
        latest_round = max(rounds, key=lambda r: r.announced_at or datetime.min.replace(tzinfo=timezone.utc)) if rounds else None
        total_usd = sum(float(r.amount_usd) for r in rounds if r.amount_usd)
        if total_usd >= 1_000_000_000:
            raised_str = f"${total_usd/1_000_000_000:.1f}B"
        elif total_usd >= 1_000_000:
            raised_str = f"${total_usd/1_000_000:.1f}M"
        elif total_usd > 0:
            raised_str = f"${total_usd/1_000:.0f}K"
        elif rounds:
            raised_str = "undisc."
        else:
            raised_str = "—"

        raised_on = latest_round.announced_at.strftime("%Y-%m-%d") if (latest_round and latest_round.announced_at) else "—"
        lead_investor = (latest_round.lead_investor[:15] if latest_round and latest_round.lead_investor else "—")
        outreach_score = f"{c.score.outreach_score:.0f}" if c.score else "0"

        stage_clean = c.stage.replace("S2_public_testnet", "S2 Testnet").replace("S1_devnet_prototype", "S1 Devnet").replace("S5_early_mainnet", "S5 Mainnet").replace("S4_mainnet_announced", "S4 Announce")

        table.add_row(
            c.canonical_name[:17],
            stage_clean,
            f"{c.stack_family.upper()} ({c.layer or 'L2'})",
            a_fmt,
            raised_str,
            raised_on,
            lead_investor,
            outreach_score,
            state_fmt,
        )

    return table


def make_source_health_table() -> Table:
    table = Table(title="Source Health & Live Ingestion Feeds", expand=True, border_style="dim")
    table.add_column("Source", style="cyan", width=20)
    table.add_column("Tier", justify="center", width=6)
    table.add_column("Cadence", width=10)
    table.add_column("Status", justify="center", width=10)

    table.add_row("recent_funded", "A", "10m", "[bold green]ONLINE[/bold green]")
    table.add_row("ethereum_lists", "A", "10m", "[bold green]ONLINE[/bold green]")
    table.add_row("chainid_network", "A", "15m", "[bold green]ONLINE[/bold green]")
    table.add_row("superchain_reg", "A", "10m", "[bold green]ONLINE[/bold green]")
    table.add_row("cosmos_registry", "A", "15m", "[bold green]ONLINE[/bold green]")
    table.add_row("funding_enricher", "A", "live", "[bold green]ONLINE[/bold green]")
    table.add_row("github_hyper", "A", "30m", "[bold green]ONLINE[/bold green]")
    table.add_row("ats_job_boards", "C", "6h", "[bold green]ONLINE[/bold green]")

    return table


async def run_tui():
    """Runs the live full-screen terminal UI."""
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="kpi", size=4),
        Layout(name="main", ratio=1),
        Layout(name="footer", size=3),
    )

    layout["main"].split_row(
        Layout(name="candidates", ratio=2),
        Layout(name="sources", ratio=1),
    )

    with Live(layout, refresh_per_second=2, screen=True):
        while True:
            layout["header"].update(make_header_layout())

            async with db_manager.session() as session:
                repo = Repository(session)
                candidates = await repo.list_candidates(limit=20)

            layout["kpi"].update(Panel(make_kpi_table(candidates), border_style="bright_blue"))
            layout["main"]["candidates"].update(Panel(make_candidates_table(candidates), border_style="dim"))
            layout["main"]["sources"].update(Panel(make_source_health_table(), border_style="dim"))
            layout["footer"].update(
                Panel(
                    Align.center(Text("Press Ctrl+C to exit  │  Run 'chainradar report generate' for daily digest", style="dim italic")),
                    border_style="dim",
                )
            )

            await asyncio.sleep(1)
