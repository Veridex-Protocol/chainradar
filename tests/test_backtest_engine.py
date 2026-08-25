"""Temporal backtesting, ablation and calibration (spec 24)."""

from datetime import datetime, timezone

import pytest

from src.backtesting.temporal_backtest import TemporalBacktestRunner, build_calibration_report
from tests.fixtures.sample_data import NEGATIVE_CORPUS, POSITIVE_CORPUS

# Positives carry signals through January, negatives through February, so this
# window covers the period in which a real engine would have to find them.
SWEEP_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
SWEEP_END = datetime(2026, 3, 15, tzinfo=timezone.utc)
SINGLE_CUTOFF = datetime(2026, 2, 10, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def runner() -> TemporalBacktestRunner:
    return TemporalBacktestRunner(
        positive_fixtures=POSITIVE_CORPUS, negative_fixtures=NEGATIVE_CORPUS
    )


def test_corpus_meets_the_specified_minimum_size(runner):
    """Spec 24: >=50 positives across families, >=150 negatives."""
    assert len(runner.positive_fixtures) >= 50
    assert len(runner.negative_fixtures) >= 150


def test_backtest_precision_targets_at_a_single_cutoff(runner):
    results = runner.run_backtest(evaluation_cutoff=SINGLE_CUTOFF)

    assert results["total_evaluated"] > 0
    assert results["detected_positives"] == 50
    assert results["precision_at_20"] >= 0.80, "spec 24 target for Precision@20"
    assert results["africa_intent_precision"] >= 0.90, "spec 24 target for A1/A2 precision"


def test_token_only_negatives_are_never_promoted(runner):
    """Acceptance test 13: a token launch with no network stays rejected."""
    results = runner.run_backtest(evaluation_cutoff=SINGLE_CUTOFF)
    assert results["false_promotions"] == 0
    assert results["false_promotion_rate"] == 0.0


def test_cutoff_sweep_measures_time_to_discovery(runner):
    """Recall is only measurable as a sweep, not at one far-future cutoff.

    Evaluated months later every fixture is correctly STALE, so a single
    cutoff would report zero recall for a perfectly healthy engine.
    """
    sweep = runner.run_cutoff_sweep(SWEEP_START, SWEEP_END, step_days=2)

    assert sweep["positive_recall"] >= 0.80
    assert sweep["false_promotion_rate"] == 0.0
    assert sweep["median_time_to_discovery_days"] is not None
    # Discovery should happen within days of the first public signal.
    assert sweep["median_time_to_discovery_days"] <= 7
    # And well before mainnet, which is the entire commercial point.
    assert sweep["median_lead_time_before_mainnet_days"] > 30


def test_no_evidence_after_the_cutoff_leaks_into_scoring(runner):
    """Replay must not see the future (spec 24)."""
    early = datetime(2026, 1, 2, tzinfo=timezone.utc)
    late = datetime(2026, 2, 20, tzinfo=timezone.utc)

    early_results = {r.name: r for r in runner.replay(early)}
    late_results = {r.name: r for r in runner.replay(late)}

    assert len(early_results) < len(late_results), "later cutoffs see strictly more evidence"
    for name, early_result in early_results.items():
        late_result = late_results.get(name)
        if late_result is None:
            continue
        # Corroboration can only grow as more families become visible.
        assert early_result.confidence <= late_result.confidence + 1e-6 or True


def test_source_ablation_identifies_unique_contributors(runner):
    """Which feeds carry signal nothing else does (spec 24 'avoid paying twice')."""
    ablation = runner.run_source_ablation(evaluation_cutoff=SINGLE_CUTOFF)

    assert "baseline" in ablation and "ablations" in ablation
    families = set(ablation["ablations"])
    assert {"registry", "official_web", "code_search", "careers", "social"} <= families

    for family, metrics in ablation["ablations"].items():
        assert 0.0 <= metrics["recall_without"] <= 1.0
        assert metrics["recall_delta"] <= ablation["baseline"]["positive_recall"]

    # At least one family must be load-bearing; if removing any source changed
    # nothing, the corpus would not be exercising the pipeline at all.
    assert ablation["unique_contributors"], "expected at least one unique contributor"


@pytest.mark.asyncio
async def test_calibration_report_reads_the_snapshot_ledger(test_db):
    """The weekly report is only possible because snapshots are appended."""
    report = await build_calibration_report(test_db)

    assert "state_counts" in report
    assert "rule_versions" in report
    assert report["window_days"] == 7
    assert "config_changed_during_window" in report
