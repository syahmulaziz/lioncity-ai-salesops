"""
Deterministic sales-triage evaluator.

WHY THIS MODULE EXISTS
----------------------
This is the Category C (DERIVED) layer of the trust model. It turns a
validated ``EnquiryState`` into a priority score and band using ONLY the
numbers defined centrally in ``app/triage_config.py``.

HARD RULES
----------
1. Pure and deterministic: same input state + config -> same output.
   No LLM call, no database, no randomness, no I/O.
2. The LLM never decides or invents the score/band. It only ever influenced
   the *inputs* (Category A signals), which were already validated by
   EnquiryState.apply_candidate().
3. The evaluator MUST NOT mutate the EnquiryState it reads. It only computes.
4. All weights/thresholds/band boundaries come from TriageConfig - none are
   hard-coded here. Changing config changes results without touching this
   algorithm.
5. Customer-value and opportunity-value subtotals are kept SEPARATE and are
   independently inspectable on the result.

VERIFIED-VALUE RULE
-------------------
Large-value points use ``verified_subtotal`` only. A monetary figure that the
customer merely claimed never reaches this file, because EnquiryState only
sets verified_subtotal via a trusted pricing tool result.
"""

from dataclasses import dataclass, field

from app.triage_config import DEFAULT_TRIAGE_CONFIG


@dataclass
class TriageResult:
    """
    The Category C output. Subtotals are stored separately so callers (and
    tests) can inspect exactly how the total was reached.

    priority_reasons is an explainable list of (reason, points) tuples, e.g.
        [("existing_customer", 1), ("tier:GOLD", 2), ("bulk>=20", 2)]
    """
    customer_value_score: int = 0
    opportunity_value_score: int = 0
    total_priority_score: int = 0
    priority_band: str = ""
    priority_reasons: list = field(default_factory=list)


def evaluate(state, config=DEFAULT_TRIAGE_CONFIG):
    """
    Compute the triage result for a validated EnquiryState.

    Parameters
    ----------
    state : EnquiryState
        The validated facts. This function reads it but never mutates it.
    config : TriageConfig
        The central scoring configuration (defaults to the baseline).

    Returns
    -------
    TriageResult
    """
    reasons = []

    # ------------------------------------------------------------------
    # CUSTOMER-VALUE SUBTOTAL
    # ------------------------------------------------------------------
    customer_value = 0

    # Existing / known customer (Category B fact).
    if state.existing_customer:
        customer_value += config.existing_customer_points
        reasons.append(("existing_customer", config.existing_customer_points))

    # Account tier points. Unknown/unmapped/None tier -> 0 (handled in config).
    tier_pts = config.tier_points(state.customer_tier)
    if tier_pts:
        reasons.append((f"tier:{state.customer_tier}", tier_pts))
        customer_value += tier_pts

    # ------------------------------------------------------------------
    # OPPORTUNITY-VALUE SUBTOTAL
    # ------------------------------------------------------------------
    opportunity_value = 0

    # Business customer. Only an explicit True counts; None (unknown) and
    # False (explicitly personal) score 0.
    if state.business_customer is True:
        opportunity_value += config.business_customer_points
        reasons.append(("business_customer", config.business_customer_points))

    # Bulk quantity. Applies when quantity >= threshold.
    if (
        isinstance(state.quantity, int)
        and not isinstance(state.quantity, bool)
        and state.quantity >= config.bulk_quantity_threshold
    ):
        opportunity_value += config.bulk_quantity_points
        reasons.append(
            (f"bulk>={config.bulk_quantity_threshold}", config.bulk_quantity_points)
        )

    # Large verified value. Uses verified_subtotal ONLY (never a claimed
    # amount). None -> no points.
    if (
        isinstance(state.verified_subtotal, (int, float))
        and not isinstance(state.verified_subtotal, bool)
        and state.verified_subtotal >= config.value_threshold_sgd
    ):
        opportunity_value += config.verified_value_points
        reasons.append(
            (f"verified_value>={config.value_threshold_sgd}", config.verified_value_points)
        )

    # Quotation requested (explicit True only).
    if state.quotation_requested is True:
        opportunity_value += config.quotation_requested_points
        reasons.append(("quotation_requested", config.quotation_requested_points))

    # Urgent (explicit True only).
    if state.urgent is True:
        opportunity_value += config.urgent_points
        reasons.append(("urgent", config.urgent_points))

    # Discount requested (explicit True only). This adds an opportunity point
    # but has NOTHING to do with discount authority / HITL, which is owned
    # separately by app/tools/discount.py.
    if state.discount_requested is True:
        opportunity_value += config.discount_requested_points
        reasons.append(("discount_requested", config.discount_requested_points))

    # ------------------------------------------------------------------
    # TOTAL + BAND
    # ------------------------------------------------------------------
    total = customer_value + opportunity_value
    band = config.band_for_score(total)

    return TriageResult(
        customer_value_score=customer_value,
        opportunity_value_score=opportunity_value,
        total_priority_score=total,
        priority_band=band,
        priority_reasons=reasons,
    )
