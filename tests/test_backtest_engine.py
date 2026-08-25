"""Tests for the Temporal Backtesting Engine."""

from datetime import datetime, timezone
import pytest
from src.backtesting.temporal_backtest import TemporalBacktestRunner
from tests.fixtures.sample_data import NEGATIVE_CORPUS, POSITIVE_CORPUS


def test_temporal_backtest_execution():
    runner = TemporalBacktestRunner(
        positive_fixtures=POSITIVE_CORPUS,
        negative_fixtures=NEGATIVE_CORPUS,
    )
    
    cutoff = datetime(2026, 7, 1, tzinfo=timezone.utc)
    results = runner.run_backtest(evaluation_cutoff=cutoff)
    
    assert results["total_evaluated"] > 0
    assert results["detected_positives"] == 50
    # Precision@20 must meet or exceed target (>=80%)
    assert results["precision_at_20"] >= 0.80
    assert results["africa_intent_precision"] >= 0.90
