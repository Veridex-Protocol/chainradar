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
    name="chainradar",
    help="ChainRadar Early Chain Discovery & Africa Expansion Intelligence Engine CLI",
    add_completion=False,
)
report_app = typer.Typer(help="Generate and export intelligence briefs and candidate datasets.")
app.add_typer(report_app, name="report")

console = Console()


@app.command()
def tui():
    """Launch the interactive live Terminal UI monitoring dashboard."""
    console.print("[bold cyan]Starting ChainRadar Live Terminal UI...[/bold cyan]")
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
        f"[bold green]ChainRadar Background Intelligence Daemon Running[/bold green]\n"
        f"• Polling cadence: Every {interval_minutes} minutes\n"
        f"• Scheduled reporting: {'Active (07:30 & 18:00 WAT)' if reports_enabled else 'Disabled'}\n"
        f"• Reports directory: [cyan]./reports/[/cyan]\n"
        f"• Press Ctrl+C to terminate.",
        title="Daemon Active",
        border_style="bright_blue",
    ))

    async def _daemon_loop():
        await db_manager.verify_schema_is_current()
        while True:
            now_utc = datetime.now(timezone.utc)
            wat_hour = (now_utc.hour + 1) % 24
            wat_min = now_utc.minute

            console.print(f"[dim]{now_utc.isoformat()} UTC ({wat_hour:02d}:{wat_min:02d} WAT)[/dim] Running scheduled discovery cycle...")

            # 1. Run Registry Collector batch in its own retried transaction.
            async def _cycle(session):
                return await IntelligencePipeline(session).run_collector_batch(
                    EthereumListsCollector()
                )

            try:
                count = await db_manager.run_in_session(_cycle)
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


@app.command("scan")
def run_scan(
    source: str = typer.Option("all", "--source", "-s", help="Source ID to scan (e.g. 'ethereum_lists', 'chainid_network', 'superchain_registry', 'cosmos_chain_registry', 'all')"),
):
    """Run real collector discovery scans against live public registries and feeds."""
    console.print(f"[bold cyan]Scanning live source:[/bold cyan] [green]{source}[/green]...")

    from src.collectors.registries.ethereum_lists import EthereumListsCollector
    from src.collectors.registries.chainid_network import ChainIdNetworkCollector
    from src.collectors.registries.superchain import SuperchainCollector
    from src.collectors.registries.cosmos_registry import CosmosRegistryCollector
    from src.collectors.web_news.rss_sitemaps import RSSFeedsCollector

    collectors_map = {
        "ethereum_lists": EthereumListsCollector(),
        "chainid_network": ChainIdNetworkCollector(),
        "superchain_registry": SuperchainCollector(),
        "cosmos_chain_registry": CosmosRegistryCollector(),
        "rss_sitemaps": RSSFeedsCollector(),
    }

    async def _scan():
        await db_manager.init_db()

        target_collectors = (
            list(collectors_map.values()) if source == "all" else [collectors_map[source]]
        )

        total_items = 0
        total_failed = 0
        for col in target_collectors:
            console.print(f"📡 Fetching live data from [cyan]{col.source_id}[/cyan]...")
            try:
                # Step 1: Read cursor in its own short session
                async with db_manager.session() as session:
                    repo = Repository(session)
                    cursor_record = await repo.get_cursor(col.source_id)
                    from src.core.types import Cursor, RateBudget
                    cursor = Cursor(
                        source_id=col.source_id,
                        etag=cursor_record.etag if cursor_record else None,
                        last_modified=cursor_record.last_modified if cursor_record else None,
                        cursor_token=cursor_record.cursor if cursor_record else None,
                        last_seen_sha=cursor_record.safe_sha if cursor_record else None,
                    )

                # Step 2: Fetch items from the network (no DB held)
                budget = RateBudget(remaining_requests=60)
                batch = await col.fetch(cursor, budget)
                console.print(f"  [dim]Received {len(batch.items)} items from {col.source_id}[/dim]")

                # Step 3: Process each item in its own session with deadlock retry
                succeeded = 0
                failed = 0
                for raw_item in batch.items:
                    async def _process_one(session, _item=raw_item, _col=col):
                        pipeline = IntelligencePipeline(session)
                        await pipeline.process_raw_item(_col, _item)

                    try:
                        await db_manager.run_in_session(_process_one)
                        succeeded += 1
                    except Exception as item_exc:
                        failed += 1
                        console.print(f"  [dim red]✗ Failed: {str(item_exc)[:100]}[/dim red]")

                # Step 4: Save cursor after all items processed
                next_cursor = col.next_cursor(batch)
                async with db_manager.session() as session:
                    repo = Repository(session)
                    await repo.save_cursor(
                        source_id=col.source_id,
                        etag=next_cursor.etag,
                        last_modified=next_cursor.last_modified,
                        cursor=next_cursor.cursor_token,
                        safe_sha=next_cursor.last_seen_sha,
                        is_success=True,
                    )

                console.print(f"[bold green]✓ {col.source_id}:[/bold green] {succeeded} processed, {failed} failed")
                total_items += succeeded
                total_failed += failed
            except Exception as exc:
                console.print(f"[bold red]✗ {col.source_id} fetch error:[/bold red] {exc}")

        result_color = "green" if total_failed == 0 else "yellow"
        console.print(f"\n[bold {result_color}]Scan complete! {total_items} processed, {total_failed} failed.[/bold {result_color}]")

    asyncio.run(_scan())


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
                search_query=search,
                limit=50,
            )

            table = Table(title="Live Blockchain Candidates", expand=True)
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
                state_c = "bold red" if c.score and c.score.state == "HOT" else ("bold yellow" if c.score and c.score.state == "QUALIFIED" else "cyan")
                outreach_score = c.score.outreach_score if c.score else 0.0
                radar_score = c.score.radar_score if c.score else 0.0
                state_val = c.score.state if c.score else "RADAR"

                table.add_row(
                    c.canonical_name,
                    c.stage,
                    f"{c.stack_family.upper()}",
                    f"[{a_color}]{a_label}[/{a_color}]",
                    f"{outreach_score:.0f}",
                    f"{radar_score:.0f}",
                    f"[{state_c}]{state_val}[/{state_c}]",
                )

            console.print(table)

    asyncio.run(_list())


if __name__ == "__main__":
    app()
