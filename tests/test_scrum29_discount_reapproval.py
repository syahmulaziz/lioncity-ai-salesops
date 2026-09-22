import app.agent as agent_module
from app.enquiry_state import EnquiryState


def _build_agent():
    agent = object.__new__(agent_module.SalesAgent)

    agent.messages = []
    agent.activity_log = []
    agent.enquiry = EnquiryState()

    agent.pending_approval = None
    agent.pending_commercial_order = None

    agent.approved_discount_percent = 8.0

    agent._order_result_this_cycle = None
    agent._suppress_order_completion_reset = False

    agent.log_activity = lambda *args, **kwargs: None

    return agent


def _order_input(quantity):
    product_subtotal = quantity * 12.0
    discount_percent = 8.0

    discounted_subtotal = (
        product_subtotal
        * (1 - discount_percent / 100)
    )

    delivery_fee = 35.0

    return {
        "phone": "+6582094108",
        "customer_id": "CUST-002",
        "items": [
            {
                "sku": "CBL-210",
                "quantity": quantity,
                "unit_price": 12.0,
            }
        ],
        "product_subtotal": product_subtotal,
        "discount_percent": discount_percent,
        "delivery_fee": delivery_fee,
        "final_total": discounted_subtotal + delivery_fee,
        "delivery_area": "Tuas",
        "delivery_date": "2026-09-23",
    }


def test_human_approved_discount_does_not_require_second_approval(
    monkeypatch,
):
    """
    SCRUM-29:

    An exact discount already approved by a human must not
    trigger EXCESSIVE_DISCOUNT again during final order
    creation when quantity/value are otherwise authorised.
    """

    agent = _build_agent()

    order_input = _order_input(12)

    created_orders = []

    def fake_evaluate(
        sku,
        quantity,
        order_value,
        discount_percent,
    ):
        # SCRUM-29 must neutralise only the already-approved
        # discount when checking remaining authority.
        assert discount_percent == 0.0

        return {
            "success": True,
            "requires_human_approval": False,
            "reasons": [],
        }

    def fake_create_order(**kwargs):
        created_orders.append(kwargs)

        return {
            "success": True,
            "order_id": "SO-SCRUM29-001",
            "status": "CONFIRMED",
            "final_total": order_input["final_total"],
            "discount_percent": 8.0,
        }

    monkeypatch.setattr(
        agent_module,
        "evaluate_commercial_authority",
        fake_evaluate,
    )

    monkeypatch.setattr(
        agent_module,
        "create_order",
        fake_create_order,
    )

    result = agent._handle_tool(
        "create_order",
        order_input,
    )

    assert result["success"] is True
    assert result["order_id"] == "SO-SCRUM29-001"

    # Exactly one order was created.
    assert len(created_orders) == 1

    # Successful completion clears transaction-scoped
    # human discount authority.
    assert agent.approved_discount_percent is None


def test_human_approved_discount_does_not_bypass_high_quantity(
    monkeypatch,
):
    """
    SCRUM-29 safety regression:

    Human approval of the discount covers ONLY that discount.
    HIGH_QUANTITY must still require commercial authority.
    """

    agent = _build_agent()

    order_input = _order_input(600)

    create_order_called = []

    def fake_evaluate(
        sku,
        quantity,
        order_value,
        discount_percent,
    ):
        assert discount_percent == 0.0

        return {
            "success": True,
            "requires_human_approval": True,
            "reasons": ["HIGH_QUANTITY"],
        }

    def forbidden_create_order(**kwargs):
        create_order_called.append(kwargs)

        raise AssertionError(
            "HIGH_QUANTITY must not bypass commercial approval"
        )

    monkeypatch.setattr(
        agent_module,
        "evaluate_commercial_authority",
        fake_evaluate,
    )

    monkeypatch.setattr(
        agent_module,
        "create_order",
        forbidden_create_order,
    )

    result = agent._handle_tool(
        "create_order",
        order_input,
    )

    # The special SCRUM-29 path must NOT create the order.
    assert create_order_called == []

    # It should fall through to the existing commercial-
    # authority enforcement, which must still block the
    # transaction without a matching approval.
    assert result["success"] is False
    assert result["error"] == "HUMAN_APPROVAL_REQUIRED"