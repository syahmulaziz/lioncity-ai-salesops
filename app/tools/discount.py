from app.database import get_commercial_policies

# HAFIZAH: REPLACE WITH ai_discount_limit
# AI_DISCOUNT_LIMIT = 5.0

# HAFIZAH: ADDED _GET_DISCOUNT_LIMIT()
def _get_discount_limit() -> float:
    """
    Get the current AI discount authority limit
    from the commercial policies database.
    """

    policies = get_commercial_policies()

    for policy in policies:
        if policy["policy_key"] == "MAX_DISCOUNT_PERCENT":
            return float(policy["policy_value"])

    raise ValueError("Commercial policy not found: MAX_DISCOUNT_PERCENT")



def check_discount_authority(
    requested_discount_percent: float
):
    """
    Determine whether the AI is authorised to approve
    the requested discount.
    """

    # HAFIZAH: ADDED GET DISCOUNT LIMIT
    ai_discount_limit = _get_discount_limit()

    if requested_discount_percent < 0:
        return {
            "success": False,
            "error": "INVALID_DISCOUNT"
        }

    # HAFIZAH: REPLACE AI_DISOCUNT_LIMIT WITH ai_discount_limit
    if requested_discount_percent <= ai_discount_limit:

        return {
            "success": True,
            "requested_discount_percent":
                requested_discount_percent,
            "ai_authority_limit_percent":
                ai_discount_limit,
            "requires_human_approval": False
        }

    return {
        "success": True,
        "requested_discount_percent":
            requested_discount_percent,
        "ai_authority_limit_percent":
            ai_discount_limit,
        "requires_human_approval": True
    }