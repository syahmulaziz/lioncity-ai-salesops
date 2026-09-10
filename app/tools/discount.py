AI_DISCOUNT_LIMIT = 5.0


def check_discount_authority(
    requested_discount_percent: float
):
    """
    Determine whether the AI is authorised to approve
    the requested discount.
    """

    if requested_discount_percent < 0:
        return {
            "success": False,
            "error": "INVALID_DISCOUNT"
        }

    if requested_discount_percent <= AI_DISCOUNT_LIMIT:

        return {
            "success": True,
            "requested_discount_percent":
                requested_discount_percent,
            "ai_authority_limit_percent":
                AI_DISCOUNT_LIMIT,
            "requires_human_approval": False
        }

    return {
        "success": True,
        "requested_discount_percent":
            requested_discount_percent,
        "ai_authority_limit_percent":
            AI_DISCOUNT_LIMIT,
        "requires_human_approval": True
    }