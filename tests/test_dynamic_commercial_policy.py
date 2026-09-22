from app.tools.discount import check_discount_authority
from app.tools.commercial_policy import (
    check_quantity_authority,
    check_order_value_authority,
)


def test_discount_authority_uses_current_database_policy(monkeypatch):
    """
    SCRUM-20 regression test.

    Discount authority must use the CURRENT commercial policy
    value rather than a hard-coded discount limit.
    """

    policies = [
        {
            "policy_key": "MAX_DISCOUNT_PERCENT",
            "policy_value": 8.0,
        }
    ]

    monkeypatch.setattr(
        "app.tools.discount.get_commercial_policies",
        lambda: policies,
    )

    within = check_discount_authority(8.0)
    over = check_discount_authority(10.0)

    assert within["success"] is True
    assert within["requires_human_approval"] is False
    assert within["ai_authority_limit_percent"] == 8.0

    assert over["success"] is True
    assert over["requires_human_approval"] is True
    assert over["ai_authority_limit_percent"] == 8.0


def test_quantity_authority_uses_current_database_policy(monkeypatch):
    """
    Quantity authority must use the current configured value.
    """

    policies = [
        {
            "policy_key": "MAX_QUANTITY_PER_SKU",
            "policy_value": 600,
        }
    ]

    monkeypatch.setattr(
        "app.tools.commercial_policy.get_commercial_policies",
        lambda: policies,
    )

    within = check_quantity_authority("CBL-210", 600)
    over = check_quantity_authority("CBL-210", 601)

    assert within["success"] is True
    assert within["requires_human_approval"] is False
    assert within["authority_limit"] == 600

    assert over["success"] is True
    assert over["requires_human_approval"] is True
    assert over["authority_limit"] == 600


def test_order_value_authority_uses_current_database_policy(monkeypatch):
    """
    Order-value authority must use the current configured value.
    """

    policies = [
        {
            "policy_key": "MAX_ORDER_VALUE",
            "policy_value": 5000,
        }
    ]

    monkeypatch.setattr(
        "app.tools.commercial_policy.get_commercial_policies",
        lambda: policies,
    )

    within = check_order_value_authority(5000)
    over = check_order_value_authority(5001)

    assert within["success"] is True
    assert within["requires_human_approval"] is False
    assert within["authority_limit"] == 5000

    assert over["success"] is True
    assert over["requires_human_approval"] is True
    assert over["authority_limit"] == 5000
