import app.agent as agent_module


def test_order_creation_failure_logs_human_attention_event(monkeypatch):
    """
    If the customer has confirmed an order but order creation fails,
    SalesOps must receive an ORDER_CREATION_FAILED event.
    """

    logged_events = []
    processed_approvals = []

    # Pretend commercial authority allows the transaction.
    monkeypatch.setattr(
        agent_module,
        "evaluate_commercial_authority",
        lambda *args, **kwargs: {
            "success": True,
            "requires_human_approval": False,
            "reasons": [],
        },
    )

    # Force the actual order creation to fail.
    monkeypatch.setattr(
        agent_module,
        "create_order",
        lambda **kwargs: {
            "success": False,
            "error": "ORDER_CREATION_FAILED",
            "message": "Simulated database failure",
        },
    )

    # Capture SalesOps events instead of writing to SQLite.
    monkeypatch.setattr(
        agent_module,
        "log_sales_event",
        lambda **kwargs: logged_events.append(kwargs),
    )

    # Capture approval processing in case it happens accidentally.
    monkeypatch.setattr(
        agent_module,
        "mark_approval_processed",
        lambda approval_id: processed_approvals.append(approval_id),
    )

    result = agent_module.execute_tool(
        "create_order",
        {
            "phone": "+6591234567",
            "customer_id": "CUST-001",
            "items": [
                {
                    "sku": "CBL-210",
                    "quantity": 1,
                    "unit_price": 12.0,
                }
            ],
            "product_subtotal": 12.0,
            "discount_percent": 0,
            "delivery_fee": 35.0,
            "final_total": 47.0,
            "delivery_area": "Jurong",
            "delivery_date": "2026-09-25",
        },
    )

    assert result["success"] is False
    assert result["error"] == "ORDER_CREATION_FAILED"

    assert len(logged_events) == 1

    event = logged_events[0]

    assert event["event_type"] == "ORDER_CREATION_FAILED"
    assert event["phone"] == "+6591234567"
    assert event["customer_id"] == "CUST-001"
    assert event["amount"] == 47.0

    assert "Human follow-up required" in event["details"]
    assert "Simulated database failure" in event["details"]

    # Failed orders must never consume an approval.
    assert processed_approvals == []
    