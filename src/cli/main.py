"""Command-line interface and background daemon for the Early Chain Discovery Engine."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.alerting.digests import DigestGenerator
from src.cli.reporter import report_generator
from src.cli.tui import run_tui
from src.collectors.registries.ethereum_lists import EthereumListsCollector
from src.core.pipeline import IntelligencePipeline
from src.storage.database import db_manager
from src.storage.repository import Repository
from src.verifier.engine import verifier_engine
from src.verifier.safe_url import SafeURLValidator

app = typer.Typer(
    name="ashinity",
    help="Ashinity Early Chain Discovery & Africa Expansion Intelligence Engine CLI",
    add_completion=False,
)
report_app = typer.Typer(help="Generate and export intelligence briefs and candidate datasets.")
app.add_typer(report_app, name="report")

console = Console()


@app.command()
def tui():
    """Launch the interactive live Terminal UI monitoring dashboard."""
    console.print("[bold cyan]Starting Ashinity Live Terminal UI...[/bold cyan]")
    try:
        asyncio.run(run_tui())
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Terminal UI stopped.[/bold yellow]")


@app.command()
def daemon(
    interval_minutes: int = typer.Option(10, "--interval", "-i", help="Collector polling interval in minutes"),
    reports_enabled: bool = typer.Option(True, "--reports/--no-reports", help="Auto-generate scheduled digests to disk"),
):
    """Run the engine in the background as a continuous discovery & reporting daemon."""
    console.print(Panel(
        f"[bold green]Ashinity Background Intelligence Daemon Running[/bold green]\n"
        f"• Polling cadence: Every {interval_minutes} minutes\n"
        f"• Scheduled reporting: {'Active (07:30 & 18:00 WAT)' if reports_enabled else 'Disabled'}\n"
        f"• Reports directory: [cyan]./reports/[/cyan]\n"
        f"• Press Ctrl+C to terminate.",
        title="Daemon Active",
        border_style="bright_blue",
    ))

    async def _daemon_loop():
        await db_manager.init_db()
        while True:
            now_utc = datetime.now(timezone.utc)
            wat_hour = (now_utc.hour + 1) % 24
            wat_min = now_utc.minute

            console.print(f"[dim]{now_utc.isoformat()} UTC ({wat_hour:02d}:{wat_min:02d} WAT)[/dim] Running scheduled discovery cycle...")

            # 1. Run Registry Collector batch
            async with db_manager.session() as session:
                pipeline = IntelligencePipeline(session)
                try:
                    count = await pipeline.run_collector_batch(EthereumListsCollector())
                    console.print(f"[green]✓ Processed {count} items from ethereum-lists[/green]")
                except Exception as e:
                    console.print(f"[red]✗ Collector cycle error: {e}[/red]")

            # 2. Check Scheduled Report Times (07:30 WAT & 18:00 WAT)
            if reports_enabled and wat_min < interval_minutes:
                if wat_hour == 7 and wat_min <= 35:
                    async with db_manager.session() as session:
                        res = await report_generator.generate_digest(session, "morning", save_to_disk=True)
                        console.print(f"[bold green]✓ Generated 07:30 WAT Morning Digest -> {res['saved_files']['markdown']}[/bold green]")
                elif wat_hour == 18 and wat_min <= 15:
                    async with db_manager.session() as session:
                        res = await report_generator.generate_digest(session, "evening", save_to_disk=True)
                        console.print(f"[bold green]✓ Generated 18:00 WAT Evening Digest -> {res['saved_files']['markdown']}[/bold green]")

            await asyncio.sleep(interval_minutes * 60)

    try:
        asyncio.run(_daemon_loop())
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Background daemon stopped by user.[/bold yellow]")


@report_app.command("generate")
def generate_report(
    digest_type: str = typer.Option("morning", "--type", "-t", help="Digest type: 'morning' (07:30 WAT) or 'evening' (18:00 WAT)"),
    save: bool = typer.Option(True, "--save/--no-save", help="Save markdown and json files to ./reports/digests/"),
):
    """Generate an on-demand intelligence digest report."""
    console.print(f"[cyan]Generating {digest_type.upper()} Intelligence Digest...[/cyan]")

    async def _gen():
        async with db_manager.session() as session:
            res = await report_generator.generate_digest(session, digest_type=digest_type, save_to_disk=save)
            console.print("\n" + res["markdown"])
            if save:
                console.print(f"\n[bold green]✓ Report saved to disk:[/bold green]")
                console.print(f"  • Markdown: [cyan]{res['saved_files']['markdown']}[/cyan]")
                console.print(f"  • JSON:     [cyan]{res['saved_files']['json']}[/cyan]")

    asyncio.run(_gen())


@report_app.command("export")
def export_dataset(
    format: str = typer.Option("csv", "--format", "-f", help="Export format: 'csv' or 'json'"),
):
    """Export the candidate database to CSV or JSON."""
    async def _export():
        async with db_manager.session() as session:
            if format.lower() == "csv":
                path = await report_generator.export_candidates_csv(session)
                console.print(f"[bold green]✓ Exported candidates to CSV:[/bold green] [cyan]{path}[/cyan]")
            else:
                repo = Repository(session)
                candidates = await repo.list_candidates(limit=500)
                data = [
                    {
                        "id": c.id,
                        "name": c.canonical_name,
                        "slug": c.slug,
                        "stage": c.stage,
                        "stack_family": c.stack_family,
                        "outreach_score": c.score.outreach_score if c.score else 0,
                        "radar_score": c.score.radar_score if c.score else 0,
                        "africa_intent": c.assessment.intent_label if c.assessment else "A4_no_evidence",
                        "first_seen_at": c.first_seen_at.isoformat() if c.first_seen_at else None,
                    }
                    for c in candidates
                ]
                now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                json_path = Path("./reports/exports") / f"candidates_export_{now_str}.json"
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                console.print(f"[bold green]✓ Exported candidates to JSON:[/bold green] [cyan]{json_path}[/cyan]")

    asyncio.run(_export())


@app.command()
def verify(
    rpc_url: str = typer.Argument(..., help="HTTP/HTTPS JSON-RPC URL to probe"),
    family: str = typer.Option("evm", "--family", "-f", help="Stack family: evm, cosmos, substrate, svm, starknet, aptos, sui, fuel"),
):
    """Perform an SSRF-hardened probe on an RPC endpoint."""
    console.print(f"[bold cyan]Initiating SSRF-Safe Probe on:[/bold cyan] {rpc_url} ({family.upper()})")

    async def _probe():
        # Validate URL for SSRF
        try:
            SafeURLValidator.validate_url(rpc_url)
            console.print("[green]✓ SSRF Pre-validation PASSED (Public IPv4/IPv6 verified)[/green]")
        except Exception as e:
            console.print(f"[bold red]✗ SSRF Pre-validation FAILED: {e}[/bold red]")
            return

        result = await verifier_engine.probe_endpoint(rpc_url, family=family)
        if result.success:
            console.print("[bold green]✓ Probe SUCCESSFUL[/bold green]")
            table = Table(box=None)
            table.add_column("Property", style="cyan")
            table.add_column("Value", style="bold white")

            if result.identity:
                table.add_row("CAIP-2", result.identity.caip2 or "N/A")
                table.add_row("Chain ID", result.identity.human_chain_id or "N/A")
                table.add_row("Genesis Hash", result.identity.genesis_hash or "N/A")
                table.add_row("Client Version", result.identity.client_version or "N/A")
            if result.head:
                table.add_row("Current Block Height", str(result.head.block_height))
                table.add_row("Head Block Hash", result.head.block_hash or "N/A")
                table.add_row("Observed Latency", f"{result.latency_ms:.1f} ms")

            console.print(table)
        else:
            console.print(f"[bold red]✗ Probe FAILED: {result.error_message}[/bold red]")

    asyncio.run(_probe())


@app.command("list")
def list_candidates(
    state: Optional[str] = typer.Option(None, "--state", "-s", help="Filter by state: HOT, QUALIFIED, RADAR"),
    search: Optional[str] = typer.Option(None, "--search", "-q", help="Search query string"),
):
    """List discovered blockchain candidates with scores and Africa classification."""
    async def _list():
        async with db_manager.session() as session:
            repo = Repository(session)
            candidates = await repo.list_candidates(
                state=state.upper() if state else None,
                query=search,
                limit=50,
            )

            table = Table(title="Blockchain Candidates", expand=True)
            table.add_column("Name", style="bold white")
            table.add_column("Stage", style="magenta")
            table.add_column("Stack", style="blue")
            table.add_column("Africa Label")
            table.add_column("Outreach", justify="right", style="bold red")
            table.add_column("Radar", justify="right", style="cyan")
            table.add_column("State", justify="center")

            for c in candidates:
                a_label = c.assessment.intent_label if c.assessment else "A4"
                a_color = "red" if a_label.startswith("A1") else ("yellow" if a_label.startswith("A2") else "dim cyan")
                state_c = "bold red" if c.score.state == "HOT" else ("bold yellow" if c.score.state == "QUALIFIED" else "cyan")

                table.add_row(
                    c.canonical_name,
                    c.stage,
                    f"{c.stack_family.upper()}",
                    f"[{a_color}]{a_label}[/{a_color}]",
                    f"{c.score.outreach_score:.0f}",
                    f"{c.score.radar_score:.0f}",
                    f"[{state_c}]{c.score.state}[/{state_c}]",
                )

            console.print(table)

    asyncio.run(_list())


if __name__ == "__main__":
    app()
