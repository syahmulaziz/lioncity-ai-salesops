from app import agent as agent_module


def test_human_approved_transaction_can_create_order(monkeypatch):
    """
    Regression test for the post-commercial-approval flow.

    Once the exact transaction has human approval, the authority
    check must allow it to proceed to create_order. The approval
    is consumed only after order creation succeeds.
    """

    approval = {
        "approval_id": 999,
        "phone": "TEST-PHONE",
        "approval_type": "COMMERCIAL_AUTHORITY",
        "status": "APPROVED",
        "sku": "CBL-210",
        "requested_quantity": 600,
        "order_value": 7200.0,
        "requested_percent": 0.0,
        "approved_percent": 0.0,
        "reason": "HIGH_QUANTITY",
    }

    # ---------------------------------------------------------
    # 1. Commercial authority still detects that this normally
    #    exceeds the AI agent's authority.
    # ---------------------------------------------------------

    monkeypatch.setattr(
        agent_module,
        "evaluate_commercial_authority",
        lambda sku, quantity, order_value, discount_percent: {
            "success": True,
            "requires_human_approval": True,
            "reasons": ["HIGH_QUANTITY"],
        },
    )

    # ---------------------------------------------------------
    # 2. But the exact transaction has already been approved.
    # ---------------------------------------------------------

    monkeypatch.setattr(
        agent_module,
        "get_matching_commercial_approval",
        lambda **kwargs: approval,
    )

    authority_result = agent_module.execute_tool(
        "evaluate_commercial_authority",
        {
            "phone": "TEST-PHONE",
            "sku": "CBL-210",
            "quantity": 600,
            "order_value": 7200.0,
            "discount_percent": 0.0,
        },
    )

    assert authority_result["success"] is True
    assert authority_result["requires_human_approval"] is False
    assert authority_result["human_approved"] is True
    assert authority_result["approval"]["approval_id"] == 999

    # ---------------------------------------------------------
    # 3. Simulate successful real order creation.
    # ---------------------------------------------------------

    created = {}

    def fake_create_order(**kwargs):
        created.update(kwargs)

        return {
            "success": True,
            "order_id": "SO-DEMO-APPROVED-001",
            "customer_id": kwargs["customer_id"],
            "status": "CONFIRMED",
        }

    monkeypatch.setattr(
        agent_module,
        "create_order",
        fake_create_order,
    )

    processed_approvals = []

    monkeypatch.setattr(
        agent_module,
        "mark_approval_processed",
        lambda approval_id: processed_approvals.append(
            approval_id
        ),
    )

    # create_order performs another server-side approval lookup.
    monkeypatch.setattr(
        agent_module,
        "get_matching_commercial_approval",
        lambda **kwargs: approval,
    )

    order_result = agent_module.execute_tool(
        "create_order",
        {
            "phone": "TEST-PHONE",
            "customer_id": "CUST-001",
            "items": [
                {
                    "sku": "CBL-210",
                    "quantity": 600,
                    "unit_price": 12.0,
                }
            ],
            "product_subtotal": 7200.0,
            "discount_percent": 0.0,
            "delivery_fee": 35.0,
            "final_total": 7235.0,
            "delivery_area": "Tengah",
            "delivery_date": "2026-09-22",
        },
    )

    # ---------------------------------------------------------
    # 4. Approved order must actually proceed.
    # ---------------------------------------------------------

    assert order_result["success"] is True
    assert order_result["status"] == "CONFIRMED"
    assert order_result["order_id"] == "SO-DEMO-APPROVED-001"

    assert created["customer_id"] == "CUST-001"
    assert created["items"][0]["sku"] == "CBL-210"
    assert created["items"][0]["quantity"] == 600
    assert created["product_subtotal"] == 7200.0
    assert created["final_total"] == 7235.0
    assert created["delivery_area"] == "Tengah"
    assert created["delivery_date"] == "2026-09-22"

    # _handle_tool("create_order") verifies that human approval
    # exists, but it must NOT consume the approval itself.
    # Approval is consumed only after the successful order is
    # linked back to that approval by the resume workflow.
    assert processed_approvals == []

def test_pending_commercial_order_resumes_after_human_approval(
    monkeypatch
):
    """
    Regression test for the full interrupted-order lifecycle.

    A customer-confirmed order blocked by commercial authority
    must be preserved on the SalesAgent. After human approval,
    the exact stored transaction must be retried, successfully
    created, and then cleared from pending state.
    """

    agent = object.__new__(agent_module.SalesAgent)

    agent.messages = []
    agent.pending_commercial_order = None

    logged = []

    def fake_log_activity(
        activity_type,
        message,
        details=None
    ):
        logged.append({
            "activity_type": activity_type,
            "message": message,
            "details": details,
        })

    agent.log_activity = fake_log_activity

    # This test bypasses __init__, so provide the grounding
    # reset method required by the approval path.
    agent._reset_response_grounding = lambda: None

    order_input = {
        "phone": "TEST-PHONE",
        "customer_id": "CUST-001",
        "items": [
            {
                "sku": "CBL-210",
                "quantity": 600,
                "unit_price": 12.0,
            }
        ],
        "product_subtotal": 7200.0,
        "discount_percent": 0.0,
        "delivery_fee": 35.0,
        "final_total": 7235.0,
        "delivery_area": "Tengah",
        "delivery_date": "2026-09-22",
    }

    # ---------------------------------------------------------
    # 1. First create_order attempt is blocked by authority.
    # ---------------------------------------------------------

    calls = []

    def fake_execute_tool(tool_name, tool_input):
        calls.append({
            "tool_name": tool_name,
            "tool_input": dict(tool_input),
        })

        if len(calls) == 1:
            return {
                "success": False,
                "error": "HUMAN_APPROVAL_REQUIRED",
                "reasons": ["HIGH_QUANTITY"],
            }

        return {
            "success": True,
            "order_id": "SO-DEMO-APPROVED-002",
            "customer_id": "CUST-001",
            "status": "CONFIRMED",
        }

    monkeypatch.setattr(
        agent_module,
        "execute_tool",
        fake_execute_tool,
    )

    # _handle_tool normally performs this after execute_tool.
    # It is irrelevant to this regression test.
    agent._ingest_tool_side_effects = (
        lambda tool_name, result: None
    )

    first_result = agent._handle_tool(
        "create_order",
        order_input,
    )

    assert first_result["success"] is False
    assert (
        first_result["error"]
        == "HUMAN_APPROVAL_REQUIRED"
    )

    # Exact transaction must now be preserved.
    assert agent.pending_commercial_order == order_input

    # ---------------------------------------------------------
    # 2. Human approves the commercial transaction.
    # ---------------------------------------------------------

    approval = {
        "approval_id": 999,
        "phone": "TEST-PHONE",
        "approval_type": "COMMERCIAL_AUTHORITY",
        "status": "APPROVED",
        "sku": "CBL-210",
        "requested_quantity": 600,
        "order_value": 7200.0,
        "requested_percent": 0.0,
        "approved_percent": 0.0,
        "reason": "HIGH_QUANTITY",
    }

    # SCRUM-19:
    # The production approval-resume flow now checks the
    # persisted approval for an existing order link before
    # creating anything, then links the newly created order
    # and marks the approval processed after success.

    linked_orders = []
    processed_approvals = []

    monkeypatch.setattr(
        agent_module,
        "get_approval_by_id",
        lambda approval_id: {
            "approval_id": approval_id,
            "status": "APPROVED",
            "order_id": None,
        },
    )

    monkeypatch.setattr(
        agent_module,
        "set_approval_order_id",
        lambda approval_id, order_id: (
            linked_orders.append(
                {
                    "approval_id": approval_id,
                    "order_id": order_id,
                }
            )
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
        lambda approval_id: (
            processed_approvals.append(
                approval_id
            )
        ),
    )

    result = agent.apply_commercial_authority_approval(
        approval
    )

    # ---------------------------------------------------------
    # 3. Approval must resume the SAME exact order.
    # ---------------------------------------------------------

    assert result["success"] is True

    assert linked_orders == [
        {
            "approval_id": 999,
            "order_id": "SO-DEMO-APPROVED-002",
        }
    ]

    assert processed_approvals == [999]

    assert len(calls) == 2

    assert calls[0]["tool_name"] == "create_order"
    assert calls[1]["tool_name"] == "create_order"

    assert calls[0]["tool_input"] == order_input
    assert calls[1]["tool_input"] == order_input

    # ---------------------------------------------------------
    # 4. Successful creation clears pending state.
    # ---------------------------------------------------------

    assert agent.pending_commercial_order is None

    assert result["order"]["success"] is True
    assert (
        result["order"]["order_id"]
        == "SO-DEMO-APPROVED-002"
    )

    # ---------------------------------------------------------
    # 5. Lifecycle should be observable.
    # ---------------------------------------------------------

    activity_types = [
        entry["activity_type"]
        for entry in logged
    ]

    assert (
        "commercial_order_pending_approval"
        in activity_types
    )

    assert (
        "commercial_authority_approval"
        in activity_types
    )

    assert (
        "commercial_order_resumed"
        in activity_types
    )

def test_processed_commercial_approval_does_not_create_duplicate_order(
    monkeypatch
):
    """
    SCRUM-19 regression:

    If a commercial approval already has an order_id,
    retrying the approval must return the existing order
    instead of creating another order.
    """

    agent = object.__new__(agent_module.SalesAgent)

    agent.messages = []
    agent.pending_commercial_order = {
        "phone": "TEST-PHONE",
        "customer_id": "CUST-001",
        "items": [
            {
                "sku": "CBL-210",
                "quantity": 600,
                "unit_price": 12.0,
            }
        ],
        "product_subtotal": 7200.0,
        "discount_percent": 0.0,
        "delivery_fee": 35.0,
        "final_total": 7235.0,
        "delivery_area": "Tengah",
        "delivery_date": "2026-09-23",
    }

    agent.log_activity = lambda *args, **kwargs: None
    agent._reset_response_grounding = lambda: None

    approval = {
        "approval_id": 999,
        "phone": "TEST-PHONE",
        "approval_type": "COMMERCIAL_AUTHORITY",
        "status": "PROCESSED",
        "sku": "CBL-210",
        "requested_quantity": 600,
        "order_value": 7235.0,
        "requested_percent": 0.0,
        "approved_percent": 0.0,
        "reason": "HIGH_QUANTITY",
        "order_id": "SO-DEMO-EXISTING-001",
    }

    monkeypatch.setattr(
        agent_module,
        "get_approval_by_id",
        lambda approval_id: approval,
    )

    create_order_calls = []

    def fake_handle_tool(tool_name, tool_input):
        create_order_calls.append(
            {
                "tool_name": tool_name,
                "tool_input": tool_input,
            }
        )

        raise AssertionError(
            "create_order must not run again for an "
            "approval that already has an order_id"
        )

    agent._handle_tool = fake_handle_tool

    result = agent.apply_commercial_authority_approval(
        approval
    )

    assert result["success"] is True

    assert (
        result["order"]["order_id"]
        == "SO-DEMO-EXISTING-001"
    )

    assert result["order"]["already_created"] is True

    assert create_order_calls == []

    assert agent.pending_commercial_order is None