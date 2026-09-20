from app.database import get_commercial_policies
from app.tools.discount import check_discount_authority

def _get_policy_value(policy_key: str) -> float:
    """
    Retrive one commercial policy value from the database.
    """

    policies = get_commercial_policies()

    for policy in policies:
        if policy["policy_key"] == policy_key:
            return float(policy["policy_value"])

    raise ValueError(f"Commercial policy not found: {policy_key}")

def check_quantity_authority(sku: str, requested_quantity: int):
    """
    Determine whether the requested quantity is within
    the AI's commercial authority.
    """

    max_quantity = _get_policy_value("MAX_QUANTITY_PER_SKU")

    if requested_quantity < 0:
        return {
            "success": False,
            "error": "INVALID_QUANTITY",
            "sku": sku,
            "requested_quantity": requested_quantity,
        }

    requires_human_approval = requested_quantity > max_quantity

    return {
            "success": True,
            "sku": sku,
            "requested_quantity": requested_quantity,
            "authority_limit": max_quantity,
            "requires_human_approval": requires_human_approval,
            "reason": (
                "HIGH_QUANTITY"
                if requires_human_approval
                else None
            )   
    }

def check_order_value_authority(order_value: float):
    """
    Determine whether the order value is within
    the AI's commercial authority
    """

    max_order_value = _get_policy_value("MAX_ORDER_VALUE")

    if order_value < 0:
        return {
            "success": False,
            "error": "INVALID_ORDER_VALUE",
            "order_value": order_value
        }

    requires_human_approval = order_value > max_order_value

    return {
        "success": True,
        "order_value": order_value,
        "authority_limit": max_order_value,
        "requires_human_approval": requires_human_approval,
        "reason": (
            "HIGH_VALUE"
            if requires_human_approval
            else None
        )
    }

def evaluate_commercial_authority(
        sku: str,
        requested_quantity: int,
        order_value: float,
        requested_discount_percent: float
):
    """
    Evaluate whether a proposed transaction in within
    the AI's commercial authority.

    Human approval is required if any commercial
    authority threshold is exceeded.
    """

    quantity_result = check_quantity_authority(sku, requested_quantity)
    value_result = check_order_value_authority(order_value)
    discount_result = check_discount_authority(requested_discount_percent)

    # Stop if any input itself is invalid
    for result in [quantity_result, value_result, discount_result]:
        if not result["success"]:
            return result

    reasons = []

    if quantity_result["requires_human_approval"]:
        reasons.append("HIGH_QUANTITY")

    if value_result["requires_human_approval"]:
        reasons.append("HIGH_VALUE")

    if discount_result["requires_human_approval"]:
        reasons.append("EXCESSIVE_DISCOUNT")

    requires_human_approval = len(reasons) > 0

    return {
        "success": True,
        "requires_human_approval": requires_human_approval,
        "reasons": reasons,
        "checks": {
            "quantity": quantity_result,
            "order_value": value_result,
            "discount": discount_result
        }
    }
         