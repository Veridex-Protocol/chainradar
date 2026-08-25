"""Command-line interface and background daemon for the Early Chain Discovery Engine."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone

logger = logging.getLogger("chainradar.cli")
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


@app.command("enrich")
def enrich_candidates(
    source: str = typer.Option("funding", "--source", "-s", help="Enrichment source: funding, activity, all"),
    candidate: Optional[str] = typer.Option(None, "--candidate", "-c", help="Specific candidate slug/name to enrich"),
    limit: int = typer.Option(100, "--limit", "-n", help="Max candidates to enrich"),
    live_search: bool = typer.Option(True, "--live/--no-live", help="Perform live web & news queries"),
):
    """Enrich blockchain candidates with verifiable public funding rounds and live activity data."""
    async def _enrich():
        from src.enrichment.funding import FundingEnricher
        
        console.print(f"[bold cyan]🔍 Starting ChainRadar Funding & Activity Enrichment Engine...[/bold cyan]")
        
        async with db_manager.session() as session:
            repo = Repository(session)
            enricher = FundingEnricher(session)
            
            if candidate:
                c = await repo.find_candidate_by_slug(candidate)
                if not c:
                    # Try search
                    candidates = await repo.list_candidates(search_query=candidate, limit=1)
                    c = candidates[0] if candidates else None
                if not c:
                    console.print(f"[bold red]✗ Candidate '{candidate}' not found in database.[/bold red]")
                    return
                candidates_to_enrich = [c]
            else:
                candidates_to_enrich = await repo.list_candidates(limit=limit)

            total_enriched = 0
            total_rounds = 0
            total_usd = 0.0

            with console.status("[bold green]Extracting & verifying public funding data...") as status:
                for idx, c in enumerate(candidates_to_enrich, 1):
                    status.update(f"[bold green]({idx}/{len(candidates_to_enrich)}) Processing {c.canonical_name}...[/bold green]")
                    try:
                        rounds = await enricher.enrich_candidate(c, allow_live_network=live_search)
                        if rounds:
                            await session.commit()
                            total_enriched += 1
                            total_rounds += len(rounds)
                            for r in rounds:
                                if r.amount_usd:
                                    total_usd += r.amount_usd
                                lead_str = f" led by [bold yellow]{r.lead_investor}[/bold yellow]" if r.lead_investor else ""
                                amount_str = f"[bold green]{r.amount_as_published}[/bold green]" if r.amount_as_published else "undisclosed amount"
                                console.print(
                                    f"  ✓ [bold white]{c.canonical_name}[/bold white]: "
                                    f"Recorded {r.round_type.upper()} round ({amount_str}{lead_str})"
                                )
                                console.print(f"    [dim]Source: {r.source_url}[/dim]")
                                if r.quote:
                                    console.print(f"    [italic dim]\"{r.quote[:100]}...\"[/italic dim]")
                    except Exception as exc:
                        await session.rollback()
                        logger.warning(f"Error enriching {c.canonical_name}: {exc}")

            usd_fmt = f"${total_usd/1_000_000_000:.2f}B" if total_usd >= 1_000_000_000 else f"${total_usd/1_000_000:.1f}M" if total_usd >= 1_000_000 else f"${total_usd:,.0f}"
            console.print(
                f"\n[bold green]Enrichment complete![/bold green] "
                f"Enriched [bold cyan]{total_enriched}[/bold cyan] chains with "
                f"[bold cyan]{total_rounds}[/bold cyan] verified funding rounds "
                f"([bold yellow]{usd_fmt}[/bold yellow] total disclosed capital)."
            )

    asyncio.run(_enrich())


@app.command("list")
def list_candidates(
    state: Optional[str] = typer.Option(None, "--state", "-s", help="Filter by state: HOT, QUALIFIED, RADAR"),
    search: Optional[str] = typer.Option(None, "--search", "-q", help="Search query string"),
    stack: Optional[str] = typer.Option(None, "--stack", help="Filter by stack family: evm, cosmos, substrate, svm"),
    africa: Optional[str] = typer.Option(None, "--africa", help="Filter by Africa label: A1, A2, A3, A4"),
    page_size: int = typer.Option(25, "--page-size", "-n", help="Rows per page"),
    page: int = typer.Option(1, "--page", "-p", help="Page number to display"),
    verified_only: bool = typer.Option(False, "--verified", help="Show only RPC-verified chains"),
    interactive: bool = typer.Option(
        True, "--interactive/--no-interactive", help="Page through results with n/p keys"
    ),
):
    """List discovered candidates with scores, activity, funding and Africa classification.

    Results are ranked by outreach score. Use n/p to page through them, or
    --page / --no-interactive for scripted output.
    """
    async def _render_page(session, page_number: int, total: int) -> int:
        repo = Repository(session)

        africa_filter = None
        if africa:
            africa_map = {
                "A1": "A1_explicit_intent",
                "A2": "A2_active_regional_motion",
                "A3": "A3_africa_compatible",
                "A4": "A4_no_evidence",
                "A5": "A5_already_covered",
            }
            africa_filter = africa_map.get(africa.upper(), africa)

        total_pages = max(1, (total + page_size - 1) // page_size)
        page_number = max(1, min(page_number, total_pages))
        offset = (page_number - 1) * page_size

        candidates = await repo.list_candidates(
            state=state.upper() if state else None,
            stack_family=stack.lower() if stack else None,
            africa_intent=africa_filter,
            search_query=search,
            limit=page_size,
            offset=offset,
            verified_only=verified_only,
        )

        table = Table(
            title=(
                f"🔗 ChainRadar — page {page_number}/{total_pages} "
                f"(showing {offset + 1}-{min(offset + page_size, total)} of {total:,})"
            ),
            expand=True,
            show_lines=False,
            border_style="dim cyan",
        )
        table.add_column("#", style="dim", width=4, justify="right")
        table.add_column("Chain Name", style="bold white", max_width=24, no_wrap=True)
        table.add_column("Chain ID", style="cyan", width=8, justify="right")
        table.add_column("Stack", style="blue", width=7)
        table.add_column("Stage", style="magenta", width=11)
        table.add_column("Africa", width=6, justify="center")
        table.add_column("Activity", width=8, justify="center")
        table.add_column("Raised", justify="right", style="bold green", width=9)
        table.add_column("Raised On", style="dim", width=10)
        table.add_column("Lead Investor", style="yellow", max_width=16, no_wrap=True)
        table.add_column("Outreach", justify="right", style="bold red", width=8)
        table.add_column("Radar", justify="right", style="cyan", width=6)
        table.add_column("State", justify="center", width=9)

        stage_map = {
            "S0_research_hint": "S0 Research",
            "S1_devnet_prototype": "S1 Devnet",
            "S2_public_testnet": "S2 Testnet",
            "S3_incentivized_testnet": "S3 Incent.",
            "S4_mainnet_announced": "S4 Announced",
            "S5_early_mainnet": "S5 Mainnet",
            "S6_established_archived": "S6 Establ.",
        }

        for idx, c in enumerate(candidates, offset + 1):
            a_label = c.assessment.intent_label if c.assessment else "A4_no_evidence"
            a_short = a_label.split("_")[0]
            a_color = {
                "A1": "bold red", "A2": "yellow", "A3": "blue", "A5": "magenta"
            }.get(a_short, "dim")

            outreach = c.score.outreach_score if c.score else 0.0
            radar = c.score.radar_score if c.score else 0.0
            state_val = c.score.state if c.score else "—"
            state_c = {
                "HOT": "bold red", "QUALIFIED": "bold yellow", "STALE": "dim", "REJECT": "dim red"
            }.get(state_val, "cyan")

            chain_id = next(
                (n.human_chain_id for n in (c.networks or []) if n.human_chain_id), "—"
            )

            # Activity rank based on real evidence: observations, networks, RPC verification
            obs_count = len(c.observation_links) if c.observation_links else 0
            net_count = len(c.networks) if c.networks else 0
            has_rpc = any(n.rpc_urls for n in (c.networks or []))
            is_verified = bool(c.last_verified_at)

            activity_pts = min(obs_count, 2) + min(net_count, 1) + (1 if has_rpc else 0) + (1 if is_verified else 0)
            if activity_pts >= 4:
                v_style, v_text = "bold green", "●●● high"
            elif activity_pts >= 3:
                v_style, v_text = "green", "●●○ med"
            elif activity_pts >= 2:
                v_style, v_text = "yellow", "●○○ low"
            elif activity_pts >= 1:
                v_style, v_text = "dim yellow", "○○○ min"
            else:
                v_style, v_text = "dim", "—   none"

            # Funding calculation from real FundingRound records
            rounds = c.funding_rounds or []
            total_disclosed = sum(float(r.amount_usd) for r in rounds if r.amount_usd)
            latest_round = max(rounds, key=lambda r: r.announced_at or datetime.min.replace(tzinfo=timezone.utc)) if rounds else None

            if total_disclosed > 0:
                if total_disclosed >= 1_000_000_000:
                    raised_str = f"${total_disclosed/1_000_000_000:.1f}B"
                elif total_disclosed >= 1_000_000:
                    raised_str = f"${total_disclosed/1_000_000:.1f}M"
                else:
                    raised_str = f"${total_disclosed/1_000:.0f}K"
            elif rounds:
                raised_str = "undisc."
            else:
                raised_str = "—"

            raised_on = (latest_round.announced_at.strftime("%Y-%m-%d") if (latest_round and latest_round.announced_at) else "—")
            lead_investor = (latest_round.lead_investor if (latest_round and latest_round.lead_investor) else ("—" if not rounds else (rounds[0].investors[0] if (rounds[0].investors) else "—")))

            table.add_row(
                str(idx),
                c.canonical_name[:24],
                str(chain_id)[:8],
                (c.stack_family or "").upper(),
                stage_map.get(c.stage, c.stage or "—"),
                f"[{a_color}]{a_short}[/{a_color}]",
                f"[{v_style}]{v_text}[/{v_style}]",
                raised_str,
                raised_on,
                str(lead_investor)[:16],
                f"{outreach:.0f}",
                f"{radar:.0f}",
                f"[{state_c}]{state_val}[/{state_c}]",
            )

        console.print(table)
        return page_number

    async def _list():
        async with db_manager.session() as session:
            repo = Repository(session)
            africa_filter = None
            if africa:
                africa_map = {
                    "A1": "A1_explicit_intent", "A2": "A2_active_regional_motion",
                    "A3": "A3_africa_compatible", "A4": "A4_no_evidence",
                    "A5": "A5_already_covered",
                }
                africa_filter = africa_map.get(africa.upper(), africa)

            total = await repo.count_candidates(
                state=state.upper() if state else None,
                stack_family=stack.lower() if stack else None,
                africa_intent=africa_filter,
                search_query=search,
                verified_only=verified_only,
            )
            if total == 0:
                console.print("[yellow]No candidates match those filters.[/yellow]")
                return

            total_pages = max(1, (total + page_size - 1) // page_size)
            current = await _render_page(session, page, total)

            if not (interactive and sys.stdin.isatty()):
                console.print(
                    f"[dim]Page {current}/{total_pages}. "
                    f"Use --page N to jump, or drop --no-interactive to browse.[/dim]"
                )
                return

            while True:
                console.print(
                    f"[dim]([bold]n[/bold])ext  ([bold]p[/bold])rev  "
                    f"([bold]f[/bold])irst  ([bold]l[/bold])ast  "
                    f"([bold]g[/bold])oto  ([bold]q[/bold])uit   —  page {current}/{total_pages}[/dim]"
                )
                try:
                    key = console.input("> ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    console.print()
                    return

                if key in ("q", "quit", "exit"):
                    return
                if key in ("n", "next", ""):
                    if current >= total_pages:
                        console.print("[yellow]Already on the last page.[/yellow]")
                        continue
                    current += 1
                elif key in ("p", "prev", "previous", "b"):
                    if current <= 1:
                        console.print("[yellow]Already on the first page.[/yellow]")
                        continue
                    current -= 1
                elif key in ("f", "first"):
                    current = 1
                elif key in ("l", "last"):
                    current = total_pages
                elif key.startswith("g"):
                    raw = key[1:].strip() or console.input("Go to page: ").strip()
                    if not raw.isdigit():
                        console.print("[yellow]Enter a page number.[/yellow]")
                        continue
                    current = max(1, min(int(raw), total_pages))
                elif key.isdigit():
                    current = max(1, min(int(key), total_pages))
                else:
                    console.print("[yellow]Unrecognized key.[/yellow]")
                    continue

                current = await _render_page(session, current, total)

    asyncio.run(_list())


if __name__ == "__main__":
    app()
