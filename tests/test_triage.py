"""
Unit tests for the deterministic triage evaluator (Task 14, Batch 1).

Covers customer-value + opportunity-value scoring, the verified-value rule,
tier rules, band boundaries (2 -> ROUTINE, 3/5 -> SALES_OPPORTUNITY,
6 -> HIGH_PRIORITY), separate subtotals, and the no-side-effect guarantee.

All tests are pure, offline, and assertion-based.
"""

from app.enquiry_state import EnquiryState
from app.triage import evaluate, TriageResult
from app.triage_config import (
    BAND_ROUTINE,
    BAND_SALES_OPPORTUNITY,
    BAND_HIGH_PRIORITY,
)


def _state(**kwargs):
    """Build an EnquiryState directly (bypassing the LLM path) for scoring."""
    state = EnquiryState()
    for key, value in kwargs.items():
        setattr(state, key, value)
    return state


# ----------------------------------------------------------------------
# 14. Existing customer scoring
# ----------------------------------------------------------------------

def test_existing_customer_scores_one():
    result = evaluate(_state(existing_customer=True))
    assert result.customer_value_score == 1
    assert result.opportunity_value_score == 0
    assert result.total_priority_score == 1
    assert result.priority_band == BAND_ROUTINE


# ----------------------------------------------------------------------
# 15. GOLD scoring
# ----------------------------------------------------------------------

def test_gold_tier_scores_two():
    result = evaluate(_state(customer_tier="GOLD"))
    assert result.customer_value_score == 2


def test_existing_gold_customer_scores_three():
    result = evaluate(_state(existing_customer=True, customer_tier="GOLD"))
    assert result.customer_value_score == 3  # +1 existing, +2 gold


# ----------------------------------------------------------------------
# 16. STANDARD scoring (no tier points)
# ----------------------------------------------------------------------

def test_standard_tier_scores_zero_tier_points():
    result = evaluate(_state(existing_customer=True, customer_tier="STANDARD"))
    assert result.customer_value_score == 1  # only the existing-customer point


# ----------------------------------------------------------------------
# 17. Unknown tier gives no tier points
# ----------------------------------------------------------------------

def test_unknown_tier_scores_zero():
    result = evaluate(_state(customer_tier="PLATINUM"))
    assert result.customer_value_score == 0

    result_none = evaluate(_state(customer_tier=None))
    assert result_none.customer_value_score == 0


# ----------------------------------------------------------------------
# 18. Business customer scoring (explicit True only)
# ----------------------------------------------------------------------

def test_business_customer_scores_one():
    assert evaluate(_state(business_customer=True)).opportunity_value_score == 1
    # None (unknown) and False (personal) score 0.
    assert evaluate(_state(business_customer=None)).opportunity_value_score == 0
    assert evaluate(_state(business_customer=False)).opportunity_value_score == 0


# ----------------------------------------------------------------------
# 19 & 20. Bulk quantity threshold (19 no, 20 yes)
# ----------------------------------------------------------------------

def test_quantity_19_no_bulk_points():
    assert evaluate(_state(quantity=19)).opportunity_value_score == 0


def test_quantity_20_gets_bulk_points():
    assert evaluate(_state(quantity=20)).opportunity_value_score == 2


# ----------------------------------------------------------------------
# 21 & 22 & 23. Verified value threshold + verified-only rule
# ----------------------------------------------------------------------

def test_verified_subtotal_4999_99_no_large_value_points():
    assert evaluate(_state(verified_subtotal=4999.99)).opportunity_value_score == 0


def test_verified_subtotal_5000_gets_large_value_points():
    assert evaluate(_state(verified_subtotal=5000)).opportunity_value_score == 2


def test_claimed_value_without_verified_subtotal_gets_no_points():
    # Customer/LLM "claim" never reaches verified_subtotal; state stays None.
    state = EnquiryState()
    state.apply_candidate({"quantity": 1})  # nothing sets verified_subtotal
    assert state.verified_subtotal is None
    assert evaluate(state).opportunity_value_score == 0


# ----------------------------------------------------------------------
# 24, 25, 26. Quotation / urgent / discount scoring
# ----------------------------------------------------------------------

def test_quotation_requested_scores_two():
    assert evaluate(_state(quotation_requested=True)).opportunity_value_score == 2


def test_urgent_scores_one():
    assert evaluate(_state(urgent=True)).opportunity_value_score == 1


def test_discount_requested_scores_one():
    assert evaluate(_state(discount_requested=True)).opportunity_value_score == 1


# ----------------------------------------------------------------------
# 27 & 28. Combined scoring + independently inspectable subtotals
# ----------------------------------------------------------------------

def test_combined_customer_and_opportunity_scores():
    # Existing GOLD (3) + business(1) + bulk(2) = total 6.
    state = _state(
        existing_customer=True,
        customer_tier="GOLD",
        business_customer=True,
        quantity=30,
    )
    result = evaluate(state)
    assert result.customer_value_score == 3
    assert result.opportunity_value_score == 3
    assert result.total_priority_score == 6
    assert result.priority_band == BAND_HIGH_PRIORITY


def test_subtotals_are_independently_inspectable():
    result = evaluate(_state(customer_tier="GOLD", urgent=True))
    # Two separate fields, each meaningful on its own.
    assert result.customer_value_score == 2
    assert result.opportunity_value_score == 1
    assert result.total_priority_score == 3
    assert result.customer_value_score + result.opportunity_value_score == \
        result.total_priority_score


# ----------------------------------------------------------------------
# 29-32. Band boundaries (mandatory): 2, 3, 5, 6
# ----------------------------------------------------------------------

def test_score_2_is_routine():
    # existing(1) + urgent(1) = 2
    result = evaluate(_state(existing_customer=True, urgent=True))
    assert result.total_priority_score == 2
    assert result.priority_band == BAND_ROUTINE


def test_score_3_is_sales_opportunity():
    # quotation(2) + urgent(1) = 3
    result = evaluate(_state(quotation_requested=True, urgent=True))
    assert result.total_priority_score == 3
    assert result.priority_band == BAND_SALES_OPPORTUNITY


def test_score_5_is_sales_opportunity():
    # GOLD(2) + quotation(2) + urgent(1) = 5
    result = evaluate(_state(
        customer_tier="GOLD", quotation_requested=True, urgent=True,
    ))
    assert result.total_priority_score == 5
    assert result.priority_band == BAND_SALES_OPPORTUNITY


def test_score_6_is_high_priority():
    # business(1) + bulk(2) + quotation(2) + urgent(1) = 6 (guest can reach it)
    result = evaluate(_state(
        business_customer=True, quantity=100,
        quotation_requested=True, urgent=True,
    ))
    assert result.total_priority_score == 6
    assert result.priority_band == BAND_HIGH_PRIORITY


# ----------------------------------------------------------------------
# 33. HIGH_PRIORITY has no side effect (pure evaluator)
# ----------------------------------------------------------------------

def test_evaluator_has_no_side_effects_on_state():
    state = _state(
        business_customer=True, quantity=100,
        quotation_requested=True, urgent=True,
    )
    # Snapshot the state before.
    before = dict(state.__dict__)

    result = evaluate(state)
    assert result.priority_band == BAND_HIGH_PRIORITY

    # The evaluator must NOT mutate the input state (no order creation, no
    # approval, no field changes). last_triage is only set by the caller via
    # set_triage_result, not by evaluate().
    assert state.__dict__ == before
    assert state.last_triage is None
    assert isinstance(result, TriageResult)
