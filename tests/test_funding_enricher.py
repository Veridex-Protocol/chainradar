"""Tests for the Funding Enrichment Engine and verifiable capital extraction."""

import pytest
import pytest_asyncio
from datetime import datetime, timezone

from src.enrichment.funding import FundingEnricher
from src.classifiers.funding import funding_extractor
from src.storage.models import ChainProduct, FundingRound, Organization, Network
from src.storage.repository import Repository


@pytest.mark.asyncio
async def test_funding_extractor_verifiable_announcement():
    text = (
        "Crypto-AI startup 0G Labs raises $40 million seed and receives $250 million token "
        "purchase commitment led by Hack VC with participation from Delphi Digital."
    )
    signals = funding_extractor.extract(text, is_official_source=True)
    assert len(signals) >= 1
    sig = signals[0]
    assert sig.round_type == "seed"
    assert sig.amount_usd == 40_000_000.0
    assert sig.amount_as_published == "$40 million"
    assert sig.lead_investor == "Hack VC"
    assert "Delphi Digital" in sig.investors
    assert sig.confidence >= 0.85


@pytest.mark.asyncio
async def test_funding_enricher_persists_traceable_round(test_db):
    repo = Repository(test_db)
    enricher = FundingEnricher(test_db)

    org = Organization(
        org_id="org_0g_test",
        display_name="0G Labs",
        official_domains=["0g.ai"],
    )
    test_db.add(org)
    await test_db.flush()

    chain = ChainProduct(
        id="chain_0g_test",
        organization_id=org.org_id,
        canonical_name="0G Galileo Testnet",
        slug="0g-galileo-testnet",
        first_seen_at=datetime.now(timezone.utc),
    )
    test_db.add(chain)
    await test_db.flush()

    rounds = await enricher.enrich_candidate(chain, allow_live_network=False)
    assert len(rounds) >= 1
    r = rounds[0]
    assert r.candidate_id == chain.id
    assert r.amount_usd == 40_000_000.0
    assert r.lead_investor == "Hack VC"
    assert r.source_url.startswith("https://")
    assert r.quote is not None

    # Verify idempotency (no duplication on re-run)
    rounds2 = await enricher.enrich_candidate(chain, allow_live_network=False)
    assert len(rounds2) >= 1
    all_stored = await repo.get_funding_rounds_for_candidate(chain.id)
    assert len(all_stored) == 1
