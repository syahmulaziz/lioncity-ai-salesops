import app.agent as agent_module
from app.enquiry_state import EnquiryState


TEST_PHONE = "+6599990044"


def _build_agent():
    """
    Minimal SalesAgent for testing commercial approval semantics
    without calling Claude or WhatsApp.
    """
    agent = object.__new__(agent_module.SalesAgent)

    agent.phone = TEST_PHONE
    agent.messages = []
    agent.activity_log = []
    agent.enquiry = EnquiryState()

    agent.pending_approval = None
    agent.pending_commercial_order = None
    agent.approved_discount_percent = None

    agent._order_result_this_cycle = None
    agent._suppress_order_completion_reset = False
    agent._resuming_approved_commercial_order = False

    agent.log_activity = lambda *args, **kwargs: None

    return agent


def _order_input(
    quantity,
    unit_price=18.0,
    discount_percent=0.0,
):
    """
    Build one confirmed ADP-120 transaction.
    """
    product_subtotal = quantity * unit_price

    discounted_subtotal = (
        product_subtotal
        * (1 - discount_percent / 100)
    )

    delivery_fee = 35.0

    return {
        "phone": TEST_PHONE,
        "customer_id": "CUST-TEST-44",
        "items": [
            {
                "sku": "ADP-120",
                "quantity": quantity,
                "unit_price": unit_price,
            }
        ],
        "product_subtotal": product_subtotal,
        "discount_percent": discount_percent,
        "delivery_fee": delivery_fee,
        "final_total": discounted_subtotal + delivery_fee,
        "delivery_area": "Tengah",
        "delivery_date": "2026-09-24",
    }


# ============================================================
# SCENARIO 1
# One HITL dimension -> one approval containing that dimension.
# ============================================================

def test_scrum44_single_threshold_creates_one_commercial_approval(
    monkeypatch,
):
    created_approvals = []

    monkeypatch.setattr(
        agent_module,
        "evaluate_commercial_authority",
        lambda sku, quantity, order_value, discount_percent: {
            "success": True,
            "requires_human_approval": True,
            "reasons": ["HIGH_QUANTITY"],
        },
    )

    monkeypatch.setattr(
        agent_module,
        "get_matching_commercial_approval",
        lambda **kwargs: None,
    )

    def fake_create_approval_request(**kwargs):
        created_approvals.append(kwargs)

        return {
            "success": True,
            "approval_id": 4401,
            "already_exists": False,
            **kwargs,
        }

    monkeypatch.setattr(
        agent_module,
        "create_approval_request",
        fake_create_approval_request,
    )

    result = agent_module.execute_tool(
        "evaluate_commercial_authority",
        {
            "phone": TEST_PHONE,
            "sku": "ADP-120",
            "quantity": 600,
            "order_value": 10800.0,
            "discount_percent": 0.0,
        },
    )

    assert result["success"] is True
    assert result["requires_human_approval"] is True

    assert len(created_approvals) == 1

    approval = created_approvals[0]

    assert (
        approval["approval_type"]
        == "COMMERCIAL_AUTHORITY"
    )

    assert approval["reason"] == "HIGH_QUANTITY"


# ============================================================
# SCENARIO 2
# Two simultaneous HITL dimensions -> ONE combined approval.
# ============================================================

def test_scrum44_two_simultaneous_thresholds_create_one_combined_approval(
    monkeypatch,
):
    created_approvals = []

    monkeypatch.setattr(
        agent_module,
        "evaluate_commercial_authority",
        lambda sku, quantity, order_value, discount_percent: {
            "success": True,
            "requires_human_approval": True,
            "reasons": [
                "HIGH_QUANTITY",
                "HIGH_VALUE",
            ],
        },
    )

    monkeypatch.setattr(
        agent_module,
        "get_matching_commercial_approval",
        lambda **kwargs: None,
    )

    def fake_create_approval_request(**kwargs):
        created_approvals.append(kwargs)

        return {
            "success": True,
            "approval_id": 4402,
            "already_exists": False,
            **kwargs,
        }

    monkeypatch.setattr(
        agent_module,
        "create_approval_request",
        fake_create_approval_request,
    )

    result = agent_module.execute_tool(
        "evaluate_commercial_authority",
        {
            "phone": TEST_PHONE,
            "sku": "ADP-120",
            "quantity": 600,
            "order_value": 10800.0,
            "discount_percent": 0.0,
        },
    )

    assert result["success"] is True
    assert result["requires_human_approval"] is True

    # Critical: one transaction -> one approval.
    assert len(created_approvals) == 1

    approval = created_approvals[0]

    reasons = set(
        approval["reason"].split(",")
    )

    assert reasons == {
        "HIGH_QUANTITY",
        "HIGH_VALUE",
    }


# ============================================================
# SCENARIO 3
# Quantity + value + discount simultaneously exceeded
# -> ONE approval containing ALL THREE reasons.
# ============================================================

def test_scrum44_three_simultaneous_thresholds_create_one_combined_approval(
    monkeypatch,
):
    created_approvals = []

    monkeypatch.setattr(
        agent_module,
        "evaluate_commercial_authority",
        lambda sku, quantity, order_value, discount_percent: {
            "success": True,
            "requires_human_approval": True,
            "reasons": [
                "HIGH_QUANTITY",
                "HIGH_VALUE",
                "EXCESSIVE_DISCOUNT",
            ],
        },
    )

    monkeypatch.setattr(
        agent_module,
        "get_matching_commercial_approval",
        lambda **kwargs: None,
    )

    def fake_create_approval_request(**kwargs):
        created_approvals.append(kwargs)

        return {
            "success": True,
            "approval_id": 4403,
            "already_exists": False,
            **kwargs,
        }

    monkeypatch.setattr(
        agent_module,
        "create_approval_request",
        fake_create_approval_request,
    )

    result = agent_module.execute_tool(
        "evaluate_commercial_authority",
        {
            "phone": TEST_PHONE,
            "sku": "ADP-120",
            "quantity": 700,
            "order_value": 11340.0,
            "discount_percent": 10.0,
        },
    )

    assert result["success"] is True
    assert result["requires_human_approval"] is True

    # NOT one approval per reason.
    assert len(created_approvals) == 1

    approval = created_approvals[0]

    assert (
        approval["approval_type"]
        == "COMMERCIAL_AUTHORITY"
    )

    assert approval["requested_percent"] == 10.0

    reasons = set(
        approval["reason"].split(",")
    )

    assert reasons == {
        "HIGH_QUANTITY",
        "HIGH_VALUE",
        "EXCESSIVE_DISCOUNT",
    }


# ============================================================
# SCENARIO 4
# Previously approved dimension must remain approved,
# but a NEW transaction change may require another approval.
# ============================================================

def test_scrum44_later_transaction_change_requests_only_new_authority(
    monkeypatch,
):
    agent = _build_agent()

    # Customer already received human approval for 10% discount.
    agent.approved_discount_percent = 10.0

    # Later the customer increases quantity.
    order_input = _order_input(
        quantity=700,
        unit_price=18.0,
        discount_percent=10.0,
    )

    authority_calls = []
    created_approvals = []

    def fake_evaluate(
        sku,
        quantity,
        order_value,
        discount_percent,
    ):
        authority_calls.append({
            "sku": sku,
            "quantity": quantity,
            "order_value": order_value,
            "discount_percent": discount_percent,
        })

        # The already-approved 10% discount must be neutralised.
        assert discount_percent == 0.0

        return {
            "success": True,
            "requires_human_approval": True,
            "reasons": [
                "HIGH_QUANTITY",
                "HIGH_VALUE",
            ],
        }

    monkeypatch.setattr(
        agent_module,
        "evaluate_commercial_authority",
        fake_evaluate,
    )

    def fake_create_approval_request(**kwargs):
        created_approvals.append(kwargs)

        return {
            "success": True,
            "approval_id": 4404,
            "already_exists": False,
            **kwargs,
        }

    monkeypatch.setattr(
        agent_module,
        "create_approval_request",
        fake_create_approval_request,
    )

    result = agent._handle_tool(
        "create_order",
        order_input,
    )

    assert result["error"] == "HUMAN_APPROVAL_REQUIRED"

    assert len(authority_calls) == 1
    assert len(created_approvals) == 1

    reasons = set(
        created_approvals[0]["reason"].split(",")
    )

    # Discount must NOT be requested for approval again.
    assert "EXCESSIVE_DISCOUNT" not in reasons

    # Newly exceeded authority dimensions still require approval.
    assert reasons == {
        "HIGH_QUANTITY",
        "HIGH_VALUE",
    }

    # The actual customer-approved discount must still be
    # preserved on the transaction itself.
    assert (
        agent.pending_commercial_order[
            "discount_percent"
        ]
        == 10.0
    )

def test_scrum44_complete_known_transaction_uses_combined_authority(
    monkeypatch,
):
    """
    SCRUM-44 regression.

    If product, quantity, verified value and requested discount
    are already known together, the transaction must be evaluated
    as one commercial snapshot.

    A legacy discount approval must not cause already-known
    HIGH_VALUE / HIGH_QUANTITY conditions to be deferred into
    another human approval later.
    """

    agent = _build_agent()

        # Keep this regression isolated from the real commercial-policy
    # database. The customer requested 10%, which requires HITL.
    monkeypatch.setattr(
        agent_module,
        "check_discount_authority",
        lambda requested_discount_percent: {
            "success": True,
            "requested_discount_percent":
                requested_discount_percent,
            "ai_authority_limit_percent": 5.0,
            "requires_human_approval": True,
        },
    )

    # Simulate the complete transaction already being known:
    #
    # ADP-120
    # quantity 700
    # subtotal/value 12,600
    # requested discount 10%
    #
    # All three authority dimensions are therefore knowable NOW.
    agent.enquiry.product_sku = "ADP-120"
    agent.enquiry.quantity = 700
    agent.enquiry.verified_subtotal = 12600.0

    authority_calls = []

    def fake_evaluate(
        sku,
        quantity,
        order_value,
        discount_percent,
    ):
        authority_calls.append({
            "sku": sku,
            "quantity": quantity,
            "order_value": order_value,
            "discount_percent": discount_percent,
        })

        return {
            "success": True,
            "requires_human_approval": True,
            "reasons": [
                "HIGH_QUANTITY",
                "HIGH_VALUE",
                "EXCESSIVE_DISCOUNT",
            ],
        }

    monkeypatch.setattr(
        agent_module,
        "evaluate_commercial_authority",
        fake_evaluate,
    )

    created_approvals = []

    def fake_create_approval_request(**kwargs):
        created_approvals.append(kwargs)

        return {
            "success": True,
            "approval_id": 4405,
            "already_exists": False,
            **kwargs,
        }

    monkeypatch.setattr(
        agent_module,
        "create_approval_request",
        fake_create_approval_request,
    )

    monkeypatch.setattr(
        agent_module,
        "get_matching_commercial_approval",
        lambda **kwargs: None,
    )

    # This is the critical boundary:
    # customer asks for a 10% discount while all other commercial
    # dimensions are already trusted/known.
    result = agent._handle_tool(
        "check_discount_authority",
        {
            "requested_discount_percent": 10.0,
        },
    )

    # New SCRUM-44 contract:
    #
    # Once the complete commercial snapshot is available, discount
    # authority must be consolidated with quantity/value authority.
    assert len(authority_calls) == 1

    authority_call = authority_calls[0]

    assert authority_call == {
        "sku": "ADP-120",
        "quantity": 700,
        "order_value": 12600.0,
        "discount_percent": 10.0,
    }

    # The result should still require HITL.
    assert result["requires_human_approval"] is True

    # ONE combined commercial approval, not a discount-only approval.
    assert len(created_approvals) == 1

    approval = created_approvals[0]

    assert (
        approval["approval_type"]
        == "COMMERCIAL_AUTHORITY"
    )

    reasons = set(
        approval["reason"].split(",")
    )

    assert reasons == {
        "HIGH_QUANTITY",
        "HIGH_VALUE",
        "EXCESSIVE_DISCOUNT",
    }

def test_scrum44_combined_approval_does_not_create_legacy_discount_pending_state(
    monkeypatch,
):
    """
    SCRUM-44 orchestration regression.

    When check_discount_authority has already consolidated the
    complete transaction into COMMERCIAL_AUTHORITY HITL, send()
    must NOT also create the legacy DISCOUNT pending_approval.
    """

    import types

    agent = _build_agent()

    agent.max_iterations = 2
    agent.system_prompt = "TEST SYSTEM PROMPT"

    # Simulate the trusted transaction already being known.
    agent.enquiry.product_sku = "ADP-120"
    agent.enquiry.quantity = 700
    agent.enquiry.verified_subtotal = 12600.0

    tool_block = types.SimpleNamespace(
        type="tool_use",
        id="tool-scrum44",
        name="check_discount_authority",
        input={
            "requested_discount_percent": 10.0,
        },
    )

    first_response = types.SimpleNamespace(
        stop_reason="tool_use",
        content=[tool_block],
    )

    final_response = types.SimpleNamespace(
        stop_reason="end_turn",
        content=[
            types.SimpleNamespace(
                type="text",
                text=(
                    "Your transaction has been sent "
                    "for human approval."
                ),
            )
        ],
    )

    responses = iter([
        first_response,
        final_response,
    ])

    agent.client = types.SimpleNamespace(
        messages=types.SimpleNamespace(
            create=lambda **kwargs: next(responses)
        )
    )

    # This is the Step-2 result contract.
    monkeypatch.setattr(
        agent,
        "_handle_tool",
        lambda tool_name, tool_input: {
            "success": True,
            "requires_human_approval": True,
            "requested_discount_percent": 10.0,
            "ai_authority_limit_percent": 5.0,
            "approval_type": "COMMERCIAL_AUTHORITY",
            "combined_commercial_approval": True,
            "reasons": [
                "HIGH_QUANTITY",
                "HIGH_VALUE",
                "EXCESSIVE_DISCOUNT",
            ],
            "approval": {
                "success": True,
                "approval_id": 4406,
                "approval_type": "COMMERCIAL_AUTHORITY",
            },
        },
    )

    # Keep this test focused on HITL orchestration.
    agent._finalize_customer_response = (
        lambda content: content[0].text
    )

    result = agent.send(
        "I would like to order 700 units of ADP-120. "
        "Can you give me a 10% discount?"
    )

    assert result["success"] is True

    # CRITICAL:
    # combined commercial HITL must not manufacture the
    # old second DISCOUNT state.
    assert agent.pending_approval is None