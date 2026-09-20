"""
Central triage configuration for the LionCity sales-triage enhancement.

WHY THIS MODULE EXISTS
----------------------
All sales-triage scoring numbers (weights, thresholds and priority-band
boundaries) live here in ONE place. The deterministic evaluator in
``app/triage.py`` reads these values; it must NOT hard-code any of them.

This keeps two concerns separate on purpose:

    TRIAGE CONFIG (this file)  -> scoring weights, thresholds, priority bands
    DISCOUNT POLICY            -> AI discount authority / human approval
                                  (stays in app/tools/discount.py, unchanged)

They are independent business concepts and may be owned by different team
members, so we do not merge them.

TRUST NOTE
----------
Nothing in this file is customer- or LLM-controlled. These are trusted,
application-owned constants. Changing a number here changes triage behaviour
without editing the evaluator algorithm.
"""

from dataclasses import dataclass, field


# Priority band labels. Kept as named constants so the rest of the code never
# writes the raw strings inline.
BAND_ROUTINE = "ROUTINE"
BAND_SALES_OPPORTUNITY = "SALES_OPPORTUNITY"
BAND_HIGH_PRIORITY = "HIGH_PRIORITY"


@dataclass(frozen=True)
class TriageConfig:
    """
    Immutable container for every triage scoring value.

    A frozen dataclass is used so the baseline defaults cannot be mutated by
    accident at runtime. Tests can still create a *new* TriageConfig with
    different numbers to prove that scoring is config-driven (not hard-coded).
    """

    # -----------------------------------------------------------------
    # CUSTOMER-VALUE WEIGHTS
    # -----------------------------------------------------------------

    # Points for being a known/existing LionCity customer.
    existing_customer_points: int = 1

    # Points per account tier. Any tier NOT listed here scores 0
    # (see tier_points()). We include SILVER / PREFERRED now for future
    # compatibility even though the current database only seeds GOLD and
    # STANDARD. We do NOT modify the database seed data for this.
    tier_points_map: dict = field(
        default_factory=lambda: {
            "GOLD": 2,
            "SILVER": 1,
            "PREFERRED": 1,
            "STANDARD": 0,
        }
    )

    # -----------------------------------------------------------------
    # OPPORTUNITY-VALUE WEIGHTS
    # -----------------------------------------------------------------

    business_customer_points: int = 1
    bulk_quantity_points: int = 2
    verified_value_points: int = 2
    quotation_requested_points: int = 2
    urgent_points: int = 1
    discount_requested_points: int = 1

    # -----------------------------------------------------------------
    # THRESHOLDS
    # -----------------------------------------------------------------

    # Bulk applies when quantity >= this number.
    bulk_quantity_threshold: int = 20

    # Large-value applies when a VERIFIED subtotal >= this number.
    # NOTE: this must be compared against verified_subtotal only, never a
    # figure the customer or LLM merely claimed.
    value_threshold_sgd: float = 5000.0

    # -----------------------------------------------------------------
    # PRIORITY-BAND BOUNDARIES
    # -----------------------------------------------------------------
    #
    #   0 .. (sales_opportunity_min - 1)   -> ROUTINE
    #   sales_opportunity_min .. (high_priority_min - 1) -> SALES_OPPORTUNITY
    #   high_priority_min ..               -> HIGH_PRIORITY
    #
    # Baseline: 0-2 ROUTINE, 3-5 SALES_OPPORTUNITY, 6+ HIGH_PRIORITY.
    sales_opportunity_min: int = 3
    high_priority_min: int = 6

    def tier_points(self, tier):
        """
        Return the customer-value points for an account tier.

        Rules:
        - A known tier returns its configured points.
        - An unknown/unmapped tier returns 0 (no accidental points).
        - ``None`` (unknown / guest) returns 0.

        Matching is case-insensitive so "gold" and "GOLD" behave the same,
        but the caller is expected to pass the verified tier from the
        business tool.
        """
        if tier is None:
            return 0

        normalized = str(tier).strip().upper()
        return self.tier_points_map.get(normalized, 0)

    def band_for_score(self, total_score):
        """
        Map a total priority score to its band label using the configured
        boundaries. Pure function of the score + config.
        """
        if total_score >= self.high_priority_min:
            return BAND_HIGH_PRIORITY
        if total_score >= self.sales_opportunity_min:
            return BAND_SALES_OPPORTUNITY
        return BAND_ROUTINE


# A ready-to-use baseline instance. Callers may import this directly, or
# construct their own TriageConfig(...) to override values (e.g. in tests).
DEFAULT_TRIAGE_CONFIG = TriageConfig()
