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

def test_scrum44_late_pricing_consolidates_earlier_discount_hitl(
    monkeypatch,
):
    """
    SCRUM-44 AWS regression.

    Claude may check discount authority BEFORE the pricing tool
    has populated verified_subtotal during the same agent turn.

    Once trusted pricing becomes available later in that turn,
    the earlier discount-only HITL must be reconciled into one
    combined commercial-authority approval.
    """

    agent = _build_agent()

    # Product + quantity are already known, but pricing is NOT.
    agent.enquiry.product_sku = "ADP-120"
    agent.enquiry.quantity = 100
    agent.enquiry.verified_subtotal = None

    # Step 1: discount check happens too early.
    agent.pending_approval = {
        "type": "DISCOUNT",
        "requested_discount_percent": 10.0,
        "ai_authority_limit_percent": 5.0,
        "status": "PENDING",
    }

    # Step 2: later in the SAME turn trusted pricing arrives.
    agent.enquiry.verified_subtotal = 1800.0

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

        return {
            "success": True,
            "requires_human_approval": True,
            "reasons": [
                "HIGH_VALUE",
                "EXCESSIVE_DISCOUNT",
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
            "approval_id": 4407,
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

    # This helper does not exist yet.
    # Step 3 will add it to SalesAgent.
    result = agent._reconcile_pending_commercial_approval()

    assert result["success"] is True
    assert result["combined_commercial_approval"] is True

    assert len(authority_calls) == 1

    assert authority_calls[0] == {
        "sku": "ADP-120",
        "quantity": 100,
        "order_value": 1800.0,
        "discount_percent": 10.0,
    }

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
        "HIGH_VALUE",
        "EXCESSIVE_DISCOUNT",
    }

    # Most important:
    # obsolete legacy discount state must be gone.
    assert agent.pending_approval is None

def test_scrum44_pricing_first_then_discount_stays_combined(
    monkeypatch,
):
    """
    SCRUM-44 reverse-order regression.

    If trusted pricing is already available BEFORE Claude checks
    discount authority, the request must immediately become one
    combined COMMERCIAL_AUTHORITY HITL.

    No legacy DISCOUNT pending state may survive.
    """

    agent = _build_agent()

    # Complete trusted snapshot already exists.
    agent.enquiry.product_sku = "ADP-120"
    agent.enquiry.quantity = 100
    agent.enquiry.verified_subtotal = 1800.0

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

        return {
            "success": True,
            "requires_human_approval": True,
            "reasons": [
                "HIGH_VALUE",
                "EXCESSIVE_DISCOUNT",
            ],
        }

    monkeypatch.setattr(
        agent_module,
        "evaluate_commercial_authority",
        fake_evaluate,
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
            "approval_id": 4408,
            "already_exists": False,
            **kwargs,
        }

    monkeypatch.setattr(
        agent_module,
        "create_approval_request",
        fake_create_approval_request,
    )

    result = agent._handle_tool(
        "check_discount_authority",
        {
            "requested_discount_percent": 10.0,
        },
    )

    assert result["success"] is True
    assert result["requires_human_approval"] is True
    assert result["combined_commercial_approval"] is True

    assert len(authority_calls) == 1

    assert authority_calls[0] == {
        "sku": "ADP-120",
        "quantity": 100,
        "order_value": 1800.0,
        "discount_percent": 10.0,
    }

    assert len(created_approvals) == 1

    approval = created_approvals[0]

    assert (
        approval["approval_type"]
        == "COMMERCIAL_AUTHORITY"
    )

    assert set(
        approval["reason"].split(",")
    ) == {
        "HIGH_VALUE",
        "EXCESSIVE_DISCOUNT",
    }

    # No legacy discount state should exist.
    assert agent.pending_approval is None

def test_scrum44_preconfirmation_approval_survives_delivery_and_confirmation(
    monkeypatch,
):
    """
    SCRUM-44 AWS regression.

    Commercial terms are approved BEFORE customer confirmation using the
    product subtotal. Adding delivery later must not invalidate that approval
    or cause a phantom second HITL.
    """

    agent = _build_agent()

    agent.approved_commercial_discount_percent = 10.0
    agent.approved_commercial_approval_id = 4409
    agent._resuming_approved_commercial_order = False

    order_input = {
        "phone": TEST_PHONE,
        "customer_id": "CUST-001",
        "items": [
            {
                "sku": "ADP-120",
                "quantity": 100,
                "unit_price": 18.0,
            }
        ],
        "product_subtotal": 1800.0,
        "discount_percent": 10.0,
        "delivery_fee": 35.0,
        "final_total": 1655.0,
        "delivery_area": "Tengah",
        "delivery_date": "2026-09-25",
    }

    authority_calls = []
    approval_lookups = []
    created_orders = []
    linked = []
    processed = []

    def fake_authority(
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
                "HIGH_VALUE",
                "EXCESSIVE_DISCOUNT",
            ],
        }

    monkeypatch.setattr(
        agent_module,
        "evaluate_commercial_authority",
        fake_authority,
    )

    def fake_matching_approval(**kwargs):
        approval_lookups.append(kwargs)

        return {
            "approval_id": 4409,
            "phone": TEST_PHONE,
            "approval_type": "COMMERCIAL_AUTHORITY",
            "status": "APPROVED",
            "sku": "ADP-120",
            "requested_quantity": 100,
            "order_value": 1800.0,
            "requested_percent": 10.0,
            "approved_percent": 10.0,
            "reason": "HIGH_VALUE,EXCESSIVE_DISCOUNT",
        }

    monkeypatch.setattr(
        agent_module,
        "get_matching_commercial_approval",
        fake_matching_approval,
    )

    def fake_create_order(**kwargs):
        created_orders.append(kwargs)

        return {
            "success": True,
            "order_id": "SO-SCRUM44-4409",
            "customer_id": kwargs["customer_id"],
            "status": "CONFIRMED",
        }

    monkeypatch.setattr(
        agent_module,
        "create_order",
        fake_create_order,
    )

    monkeypatch.setattr(
        agent_module,
        "set_approval_order_id",
        lambda approval_id, order_id: (
            linked.append((approval_id, order_id))
            or {
                "success": True,
                "approval_id": approval_id,
                "order_id": order_id,
            }
        ),
    )

    monkeypatch.setattr(
        agent_module,
        "mark_approval_processed",
        lambda approval_id: processed.append(
            approval_id
        ),
    )

    agent._ingest_tool_side_effects = (
        lambda tool_name, result: None
    )
    agent._end_current_transaction = lambda: None
    agent.log_activity = lambda *args, **kwargs: None

    result = agent._handle_tool(
        "create_order",
        order_input,
    )

    assert result["success"] is True
    assert result["order_id"] == "SO-SCRUM44-4409"

    # CRITICAL:
    # Commercial authority is evaluated against the stable
    # product subtotal, NOT delivery-adjusted final_total.
    assert authority_calls[0]["order_value"] == 1800.0

    assert approval_lookups[0]["order_value"] == 1800.0

    # Delivery still participates in the actual order total.
    assert created_orders[0]["delivery_fee"] == 35.0
    assert created_orders[0]["final_total"] == 1655.0

    # Existing approval is consumed only after successful order creation.
    assert linked == [
        (4409, "SO-SCRUM44-4409")
    ]
    assert processed == [4409]

    # No phantom second approval.
    assert agent.pending_commercial_order is None

def test_scrum44_combined_approval_preserves_human_counter_discount(
    monkeypatch,
):
    """
    SCRUM-44 regression.

    Customer requests 10%, but human approves only 8% as part of a combined
    COMMERCIAL_AUTHORITY decision.

    Subsequent order creation must use the trusted 8%, never the original 10%.
    """

    agent = _build_agent()

    agent.approved_commercial_discount_percent = 8.0
    agent.approved_commercial_approval_id = 4410
    agent._resuming_approved_commercial_order = False

    order_input = {
        "phone": TEST_PHONE,
        "customer_id": "CUST-001",
        "items": [
            {
                "sku": "ADP-120",
                "quantity": 100,
                "unit_price": 18.0,
            }
        ],
        "product_subtotal": 1800.0,

        # Claude/customer history may still carry the original request.
        "discount_percent": 10.0,

        "delivery_fee": 35.0,

        # Likewise this may still reflect the old 10%.
        "final_total": 1655.0,

        "delivery_area": "Tengah",
        "delivery_date": "2026-09-25",
    }

    created_orders = []

    monkeypatch.setattr(
        agent_module,
        "evaluate_commercial_authority",
        lambda sku, quantity, order_value, discount_percent: {
            "success": True,
            "requires_human_approval": True,
            "reasons": [
                "HIGH_VALUE",
                "EXCESSIVE_DISCOUNT",
            ],
        },
    )

    monkeypatch.setattr(
        agent_module,
        "get_matching_commercial_approval",
        lambda **kwargs: {
            "approval_id": 4410,
            "phone": TEST_PHONE,
            "approval_type": "COMMERCIAL_AUTHORITY",
            "status": "APPROVED",
            "sku": "ADP-120",
            "requested_quantity": 100,
            "order_value": 1800.0,
            "requested_percent": 10.0,
            "approved_percent": 8.0,
            "reason": "HIGH_VALUE,EXCESSIVE_DISCOUNT",
        },
    )

    def fake_create_order(**kwargs):
        created_orders.append(kwargs)

        return {
            "success": True,
            "order_id": "SO-SCRUM44-4410",
            "customer_id": kwargs["customer_id"],
            "status": "CONFIRMED",
        }

    monkeypatch.setattr(
        agent_module,
        "create_order",
        fake_create_order,
    )

    monkeypatch.setattr(
        agent_module,
        "set_approval_order_id",
        lambda approval_id, order_id: {
            "success": True,
            "approval_id": approval_id,
            "order_id": order_id,
        },
    )

    monkeypatch.setattr(
        agent_module,
        "mark_approval_processed",
        lambda approval_id: None,
    )

    agent._ingest_tool_side_effects = (
        lambda tool_name, result: None
    )
    agent._end_current_transaction = lambda: None
    agent.log_activity = lambda *args, **kwargs: None

    result = agent._handle_tool(
        "create_order",
        order_input,
    )

    assert result["success"] is True
    assert len(created_orders) == 1

    created = created_orders[0]

    # Human decision wins over the originally requested 10%.
    assert created["discount_percent"] == 8.0

    # 1800 less 8% = 1656
    # + S$35 delivery = S$1691.
    assert created["final_total"] == 1691.0

    # Original caller dictionary should not be silently mutated.
    assert order_input["discount_percent"] == 10.0
    assert order_input["final_total"] == 1655.0

def test_scrum44_successful_preapproval_order_returns_authoritative_confirmation(
    monkeypatch,
):
    """
    SCRUM-44 regression.

    A commercial approval was granted before customer confirmation.
    The customer later confirms, and create_order succeeds.

    Once the order exists, the customer-facing response must be an
    authoritative order confirmation containing the real order ID.
    It must NOT claim that a salesperson still needs to finalize it.
    """

    agent = _build_agent()

    agent.approved_commercial_discount_percent = 8.0
    agent.approved_commercial_approval_id = 4411
    agent._resuming_approved_commercial_order = False

    # _handle_tool stores successful create_order results here for
    # deterministic confirmation rendering.
    agent._order_result_this_cycle = None

    order_input = {
        "phone": TEST_PHONE,
        "customer_id": "CUST-001",
        "items": [
            {
                "sku": "ADP-120",
                "quantity": 100,
                "unit_price": 18.0,
            }
        ],
        "product_subtotal": 1800.0,
        "discount_percent": 10.0,
        "delivery_fee": 35.0,
        "final_total": 1655.0,
        "delivery_area": "Tengah",
        "delivery_date": "2026-09-25",
    }

    monkeypatch.setattr(
        agent_module,
        "evaluate_commercial_authority",
        lambda sku, quantity, order_value, discount_percent: {
            "success": True,
            "requires_human_approval": True,
            "reasons": [
                "HIGH_VALUE",
                "EXCESSIVE_DISCOUNT",
            ],
        },
    )

    monkeypatch.setattr(
        agent_module,
        "get_matching_commercial_approval",
        lambda **kwargs: {
            "approval_id": 4411,
            "phone": TEST_PHONE,
            "approval_type": "COMMERCIAL_AUTHORITY",
            "status": "APPROVED",
            "sku": "ADP-120",
            "requested_quantity": 100,
            "order_value": 1800.0,
            "requested_percent": 10.0,
            "approved_percent": 8.0,
            "reason": "HIGH_VALUE,EXCESSIVE_DISCOUNT",
        },
    )

    monkeypatch.setattr(
        agent_module,
        "create_order",
        lambda **kwargs: {
            "success": True,
            "order_id": "SO-SCRUM44-4411",
            "customer_id": "CUST-001",
            "status": "CONFIRMED",
            "items": kwargs["items"],
            "product_subtotal": kwargs["product_subtotal"],
            "discount_percent": kwargs["discount_percent"],
            "delivery_fee": kwargs["delivery_fee"],
            "final_total": kwargs["final_total"],
            "delivery_area": kwargs["delivery_area"],
            "delivery_date": kwargs["delivery_date"],
        },
    )

    monkeypatch.setattr(
        agent_module,
        "set_approval_order_id",
        lambda approval_id, order_id: {
            "success": True,
            "approval_id": approval_id,
            "order_id": order_id,
        },
    )

    monkeypatch.setattr(
        agent_module,
        "mark_approval_processed",
        lambda approval_id: None,
    )

    agent._ingest_tool_side_effects = (
        lambda tool_name, result: None
    )
    agent._end_current_transaction = lambda: None
    agent.log_activity = lambda *args, **kwargs: None

    result = agent._handle_tool(
        "create_order",
        order_input,
    )

    assert result["success"] is True

    # Human counter-discount must still win.
    assert result["discount_percent"] == 8.0
    assert result["final_total"] == 1691.0

    # Successful order must be captured for deterministic
    # customer-facing confirmation.
    assert agent._order_result_this_cycle is not None

    confirmation = agent._render_order_confirmation_section()

    assert "SO-SCRUM44-4411" in confirmation
    assert "8%" in confirmation
    assert "1,691" in confirmation

    lower = confirmation.lower()

    assert "sales representative" not in lower
    assert "finalize" not in lower
    assert "finalise" not in lower

import types

def test_scrum44_successful_order_overrides_stale_claude_finalization_message(
    monkeypatch,
):
    """
    SCRUM-44 AWS regression.

    Once create_order has succeeded, trusted order state must override
    contradictory Claude prose claiming that a salesperson still needs
    to finalize the order.
    """

    agent = _build_agent()

        # _build_agent() bypasses SalesAgent.__init__().
    # Initialise the normal per-response grounding fields
    # required by the shared finalizer.
    agent._reset_response_grounding()

    agent._order_result_this_cycle = {
        "success": True,
        "order_id": "SO-SCRUM44-4412",
        "customer_id": "CUST-001",
        "status": "CONFIRMED",
        "items": [
            {
                "sku": "ADP-120",
                "quantity": 100,
                "unit_price": 18.0,
            }
        ],
        "product_subtotal": 1800.0,
        "discount_percent": 8.0,
        "delivery_fee": 35.0,
        "final_total": 1691.0,
        "delivery_area": "Tengah",
        "delivery_date": "2026-09-25",
    }

    agent._order_result_this_cycle = {
        "success": True,
        "order_id": "SO-SCRUM44-4412",
        "customer_id": "CUST-001",
        "status": "CONFIRMED",
        "items": [
            {
                "sku": "ADP-120",
                "quantity": 100,
                "unit_price": 18.0,
            }
        ],
        "product_subtotal": 1800.0,
        "discount_percent": 8.0,
        "delivery_fee": 35.0,
        "final_total": 1691.0,
        "delivery_area": "Tengah",
        "delivery_date": "2026-09-25",
    }

    # Simulate the incorrect model prose observed on AWS.
    claude_draft = [
        types.SimpleNamespace(
            type="text",
            text=(
                "Your order details are confirmed. "
                "Your sales representative Xin Xian will be in touch "
                "shortly to finalize this order for you."
            ),
        )
    ]

    finalized = agent._finalize_customer_response(
        claude_draft
    )

    # Trusted order confirmation must win.
    assert "SO-SCRUM44-4412" in finalized
    assert "8%" in finalized
    assert "1,691" in finalized

    lower = finalized.lower()

    assert "sales representative" not in lower
    assert "will be in touch" not in lower
    assert "finalize this order" not in lower
    assert "finalise this order" not in lower

def test_scrum44_order_success_cannot_be_retried_when_approval_link_fails(
    monkeypatch,
):
    """
    SCRUM-44 AWS regression.

    Once create_order has successfully persisted an order, a later
    approval-link/bookkeeping failure must NEVER turn that successful
    order into a tool failure that Claude can retry.

    AWS previously created TWO real orders from one customer
    confirmation because:
        create_order succeeded
        -> set_approval_order_id failed
        -> tool reported failure
        -> Claude called create_order again.
    """

    import types

    agent = _build_agent()
    agent._reset_response_grounding()

    agent.max_iterations = 10
    agent.system_prompt = agent_module.SYSTEM_PROMPT

    agent.approved_commercial_discount_percent = 8.0
    agent.approved_commercial_approval_id = 4413
    agent._resuming_approved_commercial_order = False

    # Trusted transaction state needed by the finalizer / lifecycle.
    agent.enquiry.product_sku = "ADP-120"
    agent.enquiry.quantity = 100
    agent.enquiry.verified_subtotal = 1800.0

    create_order_calls = []

    monkeypatch.setattr(
        agent_module,
        "evaluate_commercial_authority",
        lambda sku, quantity, order_value, discount_percent: {
            "success": True,
            "requires_human_approval": True,
            "reasons": [
                "HIGH_VALUE",
                "EXCESSIVE_DISCOUNT",
            ],
        },
    )

    monkeypatch.setattr(
        agent_module,
        "get_matching_commercial_approval",
        lambda **kwargs: {
            "approval_id": 4413,
            "phone": TEST_PHONE,
            "approval_type": "COMMERCIAL_AUTHORITY",
            "status": "APPROVED",
            "sku": "ADP-120",
            "requested_quantity": 100,
            "order_value": 1800.0,
            "requested_percent": 10.0,
            "approved_percent": 8.0,
            "reason": "HIGH_VALUE,EXCESSIVE_DISCOUNT",
        },
    )

    def fake_create_order(**kwargs):
        create_order_calls.append(kwargs)

        return {
            "success": True,
            "order_id": "SO-SCRUM44-4413",
            "customer_id": "CUST-001",
            "status": "CONFIRMED",
            "items": kwargs["items"],
            "product_subtotal": kwargs["product_subtotal"],
            "discount_percent": kwargs["discount_percent"],
            "delivery_fee": kwargs["delivery_fee"],
            "final_total": kwargs["final_total"],
            "delivery_area": kwargs["delivery_area"],
            "delivery_date": kwargs["delivery_date"],
        }

    monkeypatch.setattr(
        agent_module,
        "create_order",
        fake_create_order,
    )

    # Reproduce the exact AWS failure:
    # order persistence succeeds, but approval bookkeeping fails AFTERWARD.
    def failing_approval_link(approval_id, order_id):
        raise RuntimeError("simulated approval-link failure")

    monkeypatch.setattr(
        agent_module,
        "set_approval_order_id",
        failing_approval_link,
    )

    monkeypatch.setattr(
        agent_module,
        "mark_approval_processed",
        lambda approval_id: None,
    )

    agent.log_activity = lambda *args, **kwargs: None

    order_tool_use = types.SimpleNamespace(
        type="tool_use",
        id="toolu_scrum44_4413",
        name="create_order",
        input={
            "phone": TEST_PHONE,
            "customer_id": "CUST-001",
            "items": [
                {
                    "sku": "ADP-120",
                    "quantity": 100,
                    "unit_price": 18.0,
                }
            ],
            "product_subtotal": 1800.0,
            "discount_percent": 8.0,
            "delivery_fee": 30.0,
            "final_total": 1686.0,
            "delivery_area": "Tengah",
            "delivery_date": "2026-09-26",
        },
    )

    first_response = types.SimpleNamespace(
        stop_reason="tool_use",
        content=[order_tool_use],
    )

    # This represents what happened on AWS: if the first successful order
    # is incorrectly reported as a tool failure, Claude gets another turn
    # and attempts create_order again.
    second_order_tool_use = types.SimpleNamespace(
        type="tool_use",
        id="toolu_scrum44_4413_retry",
        name="create_order",
        input=order_tool_use.input.copy(),
    )

    second_response = types.SimpleNamespace(
        stop_reason="tool_use",
        content=[second_order_tool_use],
    )

    responses = iter([
        first_response,
        second_response,
    ])

    agent.client = types.SimpleNamespace(
        messages=types.SimpleNamespace(
            create=lambda **kwargs: next(responses)
        )
    )

    result = agent.send("Yes please proceed.")

    # The persisted order is authoritative even though subsequent
    # approval bookkeeping failed.
    assert result["success"] is True

    # CRITICAL IDEMPOTENCY CONTRACT:
    # one customer confirmation may persist at most ONE order.
    assert len(create_order_calls) == 1

    assert agent._order_result_this_cycle is not None
    assert (
        agent._order_result_this_cycle["order_id"]
        == "SO-SCRUM44-4413"
    )

    response = result["response"]

    assert "SO-SCRUM44-4413" in response
    assert "8%" in response
    assert "1,686" in response

    lower = response.lower()

    assert "technical issue creating" not in lower
    assert "finalize" not in lower
    assert "finalise" not in lower