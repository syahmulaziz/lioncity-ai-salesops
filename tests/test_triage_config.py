"""
Unit tests for the central triage configuration (Task 14, Batch 1).

Proves case 34: changing configuration thresholds/weights changes scoring
WITHOUT rewriting the triage algorithm. The evaluator code stays untouched;
only a different TriageConfig is passed in.

Also verifies tier_points() and band_for_score() helpers directly.
"""

from app.enquiry_state import EnquiryState
from app.triage import evaluate
from app.triage_config import (
    TriageConfig,
    DEFAULT_TRIAGE_CONFIG,
    BAND_ROUTINE,
    BAND_SALES_OPPORTUNITY,
    BAND_HIGH_PRIORITY,
)


def _state(**kwargs):
    state = EnquiryState()
    for key, value in kwargs.items():
        setattr(state, key, value)
    return state


# ----------------------------------------------------------------------
# tier_points helper
# ----------------------------------------------------------------------

def test_tier_points_baseline():
    cfg = DEFAULT_TRIAGE_CONFIG
    assert cfg.tier_points("GOLD") == 2
    assert cfg.tier_points("SILVER") == 1
    assert cfg.tier_points("PREFERRED") == 1
    assert cfg.tier_points("STANDARD") == 0
    assert cfg.tier_points("UNKNOWN_TIER") == 0
    assert cfg.tier_points(None) == 0
    # case-insensitive
    assert cfg.tier_points("gold") == 2


# ----------------------------------------------------------------------
# band_for_score helper (boundary math independent of signals)
# ----------------------------------------------------------------------

def test_band_for_score_boundaries():
    cfg = DEFAULT_TRIAGE_CONFIG
    assert cfg.band_for_score(0) == BAND_ROUTINE
    assert cfg.band_for_score(2) == BAND_ROUTINE
    assert cfg.band_for_score(3) == BAND_SALES_OPPORTUNITY
    assert cfg.band_for_score(5) == BAND_SALES_OPPORTUNITY
    assert cfg.band_for_score(6) == BAND_HIGH_PRIORITY
    assert cfg.band_for_score(10) == BAND_HIGH_PRIORITY


# ----------------------------------------------------------------------
# 34. Config-driven scoring: change weights/thresholds, not the algorithm
# ----------------------------------------------------------------------

def test_changing_weight_changes_score():
    state = _state(urgent=True)

    # Baseline: urgent = +1.
    assert evaluate(state).opportunity_value_score == 1

    # Reconfigure urgent to be worth 5, without touching triage.py.
    custom = TriageConfig(urgent_points=5)
    assert evaluate(state, custom).opportunity_value_score == 5


def test_changing_bulk_threshold_changes_outcome():
    state = _state(quantity=10)

    # Baseline threshold 20: qty 10 gets no bulk points.
    assert evaluate(state).opportunity_value_score == 0

    # Lower the threshold to 10 via config only.
    custom = TriageConfig(bulk_quantity_threshold=10)
    assert evaluate(state, custom).opportunity_value_score == 2


def test_changing_band_boundaries_changes_band():
    # existing(1) + urgent(1) = total 2. Baseline => ROUTINE.
    state = _state(existing_customer=True, urgent=True)
    assert evaluate(state).priority_band == BAND_ROUTINE

    # Make SALES_OPPORTUNITY start at 2 via config only.
    custom = TriageConfig(sales_opportunity_min=2, high_priority_min=4)
    assert evaluate(state, custom).priority_band == BAND_SALES_OPPORTUNITY


def test_changing_tier_map_changes_score():
    state = _state(customer_tier="STANDARD")

    # Baseline: STANDARD => 0.
    assert evaluate(state).customer_value_score == 0

    # Promote STANDARD to +1 via config only.
    custom = TriageConfig(tier_points_map={"STANDARD": 1})
    assert evaluate(state, custom).customer_value_score == 1
