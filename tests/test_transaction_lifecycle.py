"""
Transaction-lifecycle correction (delivery-readiness follow-up).

One SalesAgent is reused across every message from a customer, so a
SUCCESSFUL order must end the current transaction: the completed order's
product / quantity / verified inventory must be cleared
(EnquiryState.reset_after_order_completion) so a later order on the SAME
agent cannot inherit stale readiness - even for an identical SKU + quantity.

A FAILED order must NOT reset the transaction (the customer can retry).

All offline; the committed DB is never written (create_order is stubbed via
the agent's execute_tool seam, mirroring tests/test_approved_order_resume.py).
"""

import pytest

# Import the harness FIRST: it registers offline stubs for anthropic/dotenv/
# requests before app.agent (via app.claude_client) imports them.
from tests._agent_harness import build_agent
import app.agent as agent_module

AVAIL_AREA, AVAIL_DATE = "Jurong", "2026-09-15"
SKU, QTY = "CBL-210", 10
PROCEED = "Would you like to proceed with the order?"


def _stub_create_order_success(monkeypatch, order_id="SO-TEST-001"):
    """Stub create_order with the real tool's successful-result shape."""
    real_execute = agent_module.execute_tool

    def fake_execute_tool(tool_name, tool_input):
        if tool_name == "create_order":
            return {
                "success": True,
                "order_id": order_id,
                "customer_id": tool_input["customer_id"],
                "items": tool_input["items"],
                "product_subtotal": tool_input["product_subtotal"],
                "discount_percent": tool_input["discount_percent"],
                "delivery_fee": tool_input["delivery_fee"],
                "final_total": tool_input["final_total"],
                "delivery_area": tool_input["delivery_area"],
                "delivery_date": tool_input["delivery_date"],
                "status": "CONFIRMED",
            }

        return real_execute(tool_name, tool_input)

    monkeypatch.setattr(agent_module, "execute_tool", fake_execute_tool)


def _stub_create_order_failure(monkeypatch):
    real_execute = agent_module.execute_tool

    def fake_execute_tool(tool_name, tool_input):
        if tool_name == "create_order":
            return {"success": False, "error": "DB_WRITE_FAILED",
                    "message": "simulated failure"}
        return real_execute(tool_name, tool_input)

    monkeypatch.setattr(agent_module, "execute_tool", fake_execute_tool)


def _order_tool_input():
    return {
        "phone": "+6580000000", "customer_id": "CUST-001",
        "items": [{"sku": SKU, "quantity": QTY, "unit_price": 12.0}],
        "product_subtotal": 120.0, "discount_percent": 0.0,
        "delivery_fee": 35.0, "final_total": 155.0,
        "delivery_area": AVAIL_AREA, "delivery_date": AVAIL_DATE,
    }


# ----------------------------------------------------------------------
# SUCCESSFUL order completion clears the completed transaction's readiness.
# ----------------------------------------------------------------------
def test_successful_order_resets_transaction_state(monkeypatch):
    _stub_create_order_success(monkeypatch)
    script = [
        [("check_inventory", {"sku": SKU, "requested_quantity": QTY})],
        "In stock.",
        [("create_order", _order_tool_input())],
        "Order created!",
    ]
    agent, tools = build_agent(monkeypatch, script)
    agent.enquiry.product_sku = SKU
    agent.enquiry.product_name = "Industrial Cable"
    agent.enquiry.quantity = QTY

    agent.send("10 units of Industrial Cable")
    assert agent.enquiry.verified_inventory_can_fulfil is True

def test_successful_order_confirmation_overrides_contradictory_model_draft(
    monkeypatch
):
    """
    Once create_order succeeds, the trusted CONFIRMED order result must be
    authoritative. A contradictory Claude draft must never tell the customer
    that further approval is required.
    """
    _stub_create_order_success(
        monkeypatch,
        order_id="SO-TEST-CONFIRMED-001"
    )

    script = [
        [("create_order", _order_tool_input())],
        (
            "I need to get final approval from our sales team "
            "before I can create this order."
        ),
    ]

    agent, tools = build_agent(monkeypatch, script)

    result = agent.send("Yes, proceed with the order")

    response = result["response"]

    assert "SO-TEST-CONFIRMED-001" in response
    assert "confirmed" in response.lower()

    assert "final approval" not in response.lower()
    assert "before i can create this order" not in response.lower()

    agent.send("Yes, create the order")
    # Completed-transaction readiness is cleared.
    assert agent.enquiry.product_sku is None
    assert agent.enquiry.quantity is None
    assert agent.enquiry.verified_inventory_sku is None
    assert agent.enquiry.verified_inventory_can_fulfil is None
    # And the readiness helper no longer authorizes the completed order.
    assert agent.enquiry.inventory_ready_for(SKU, QTY) is False


# ----------------------------------------------------------------------
# TWO ORDERS, SAME SalesAgent, SAME SKU + qty.
# ----------------------------------------------------------------------
def test_second_order_same_sku_qty_requires_fresh_inventory(monkeypatch):
    _stub_create_order_success(monkeypatch)
    script = [
        # ORDER 1
        [("check_inventory", {"sku": SKU, "requested_quantity": QTY})],
        "In stock.",
        [("create_order", _order_tool_input())],
        "Order 1 created!",
        # ORDER 2 - customer restates same product+qty, delivery ONLY first.
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE})],
        "Delivery details.",
        # ORDER 2 - now a fresh inventory check.
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE}),
         ("check_inventory", {"sku": SKU, "requested_quantity": QTY})],
        "Delivery details 2.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    agent.enquiry.product_sku = SKU
    agent.enquiry.product_name = "Industrial Cable"
    agent.enquiry.quantity = QTY

    agent.send("10 units of Industrial Cable")
    agent.send("Yes, create the order")   # ORDER 1 completes -> reset

    # ORDER 2 begins: re-establish the SAME product + quantity as Category A/B
    # would (order 1 cleared them). Simulate the trusted re-identification.
    agent.enquiry.product_sku = SKU
    agent.enquiry.product_name = "Industrial Cable"
    agent.enquiry.quantity = QTY

    # Delivery-only, NO fresh inventory yet -> stale order-1 inventory must
    # NOT authorize; prompt suppressed.
    r_no = agent.send("Deliver to Jurong on 2026-09-15 for my new order?")
    assert PROCEED not in r_no["response"]

    # Fresh inventory verification for order 2 -> prompt now allowed.
    r_yes = agent.send("Please check stock and delivery again")
    assert PROCEED in r_yes["response"]


# ----------------------------------------------------------------------
# FAILED order must NOT reset the transaction (retry stays possible).
# ----------------------------------------------------------------------
def test_failed_order_does_not_reset_transaction(monkeypatch):
    _stub_create_order_failure(monkeypatch)
    script = [
        [("check_inventory", {"sku": SKU, "requested_quantity": QTY})],
        "In stock.",
        [("create_order", _order_tool_input())],
        "Trying to create order.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    agent.enquiry.product_sku = SKU
    agent.enquiry.product_name = "Industrial Cable"
    agent.enquiry.quantity = QTY

    agent.send("10 units of Industrial Cable")
    assert agent.enquiry.verified_inventory_can_fulfil is True

    agent.send("Yes, create the order")   # create_order FAILS
    # Transaction state must be INTACT for retry.
    assert agent.enquiry.product_sku == SKU
    assert agent.enquiry.quantity == QTY
    assert agent.enquiry.verified_inventory_sku == SKU
    assert agent.enquiry.inventory_ready_for(SKU, QTY) is True



# ----------------------------------------------------------------------
# COMMERCIAL-AUTHORITY resume: cleanup occurs only AFTER link + processed,
# and SCRUM-19 idempotency (no duplicate order on retry) is preserved.
# ----------------------------------------------------------------------
from app.enquiry_state import EnquiryState


def _bare_commercial_agent():
    agent = object.__new__(agent_module.SalesAgent)
    agent.messages = []
    agent.pending_commercial_order = {
        "phone": "TEST-PHONE", "customer_id": "CUST-001",
        "items": [{"sku": "CBL-210", "quantity": 600, "unit_price": 12.0}],
        "product_subtotal": 7200.0, "discount_percent": 0.0,
        "delivery_fee": 35.0, "final_total": 7235.0,
        "delivery_area": "Tengah", "delivery_date": "2026-09-22",
    }
    agent.log_activity = lambda *a, **k: None
    agent._reset_response_grounding = lambda: None
    agent._ingest_tool_side_effects = lambda tool_name, result: None
    # Real EnquiryState populated as if this order had been established.
    agent.enquiry = EnquiryState()
    agent.enquiry.product_sku = "CBL-210"
    agent.enquiry.product_name = "Industrial Cable"
    agent.enquiry.quantity = 600
    agent.enquiry.set_verified_inventory({
        "success": True, "sku": "CBL-210", "requested_quantity": 600,
        "available_quantity": 1000, "can_fulfil": True,
    })
    return agent


def test_commercial_resume_cleanup_after_link_and_processed(monkeypatch):
    agent = _bare_commercial_agent()

    linked, processed = [], []
    monkeypatch.setattr(agent_module, "get_approval_by_id",
                        lambda approval_id: {"approval_id": approval_id,
                                             "status": "APPROVED",
                                             "order_id": None})
    monkeypatch.setattr(agent_module, "set_approval_order_id",
                        lambda approval_id, order_id: linked.append(order_id)
                        or {"success": True})
    monkeypatch.setattr(agent_module, "mark_approval_processed",
                        lambda approval_id: processed.append(approval_id))

    def fake_handle_tool(tool_name, tool_input):
        assert tool_name == "create_order"
        return {"success": True, "order_id": "SO-DEMO-APPROVED-002"}

    agent._handle_tool = fake_handle_tool

    approval = {"approval_id": 999, "phone": "TEST-PHONE",
                "approval_type": "COMMERCIAL_AUTHORITY", "status": "APPROVED",
                "sku": "CBL-210", "requested_quantity": 600,
                "order_value": 7200.0, "requested_percent": 0.0,
                "approved_percent": 0.0, "reason": "HIGH_QUANTITY"}

    result = agent.apply_commercial_authority_approval(approval)
    assert result["success"] is True
    # SCRUM-19 ordering preserved: linked then processed.
    assert linked == ["SO-DEMO-APPROVED-002"]
    assert processed == [999]
    # Transaction cleanup happened only after success.
    assert agent.pending_commercial_order is None
    assert agent.enquiry.product_sku is None
    assert agent.enquiry.quantity is None
    assert agent.enquiry.verified_inventory_sku is None


def test_commercial_resume_existing_order_no_duplicate_and_cleanup(monkeypatch):
    agent = _bare_commercial_agent()

    monkeypatch.setattr(agent_module, "get_approval_by_id",
                        lambda approval_id: {"approval_id": approval_id,
                                             "status": "PROCESSED",
                                             "order_id": "SO-EXISTING-001"})

    def fake_handle_tool(tool_name, tool_input):
        raise AssertionError("create_order must not run for an existing order")

    agent._handle_tool = fake_handle_tool

    approval = {"approval_id": 999, "phone": "TEST-PHONE",
                "approval_type": "COMMERCIAL_AUTHORITY", "status": "PROCESSED",
                "sku": "CBL-210", "requested_quantity": 600,
                "order_value": 7200.0, "requested_percent": 0.0,
                "approved_percent": 0.0, "reason": "HIGH_QUANTITY",
                "order_id": "SO-EXISTING-001"}

    result = agent.apply_commercial_authority_approval(approval)
    assert result["success"] is True
    assert result["order"]["already_created"] is True
    assert result["order"]["order_id"] == "SO-EXISTING-001"
    # Existing-order retry also ends the transaction (no duplicate create).
    assert agent.pending_commercial_order is None
    assert agent.enquiry.product_sku is None
    assert agent.enquiry.verified_inventory_sku is None


def test_commercial_resume_link_failure_does_not_reset(monkeypatch):
    agent = _bare_commercial_agent()

    monkeypatch.setattr(agent_module, "get_approval_by_id",
                        lambda approval_id: {"approval_id": approval_id,
                                             "status": "APPROVED",
                                             "order_id": None})
    # Linking FAILS -> must not mark processed, must not reset transaction.
    monkeypatch.setattr(agent_module, "set_approval_order_id",
                        lambda approval_id, order_id: {"success": False})
    processed = []
    monkeypatch.setattr(agent_module, "mark_approval_processed",
                        lambda approval_id: processed.append(approval_id))

    agent._handle_tool = lambda t, i: {"success": True,
                                       "order_id": "SO-DEMO-APPROVED-002"}

    approval = {"approval_id": 999, "phone": "TEST-PHONE",
                "approval_type": "COMMERCIAL_AUTHORITY", "status": "APPROVED",
                "sku": "CBL-210", "requested_quantity": 600,
                "order_value": 7200.0, "requested_percent": 0.0,
                "approved_percent": 0.0, "reason": "HIGH_QUANTITY"}

    result = agent.apply_commercial_authority_approval(approval)
    assert result["success"] is False
    assert result["error"] == "APPROVAL_ORDER_LINK_FAILED"
    # Not processed, transaction NOT reset (retry must remain possible).
    assert processed == []
    assert agent.enquiry.product_sku == "CBL-210"
    assert agent.enquiry.verified_inventory_sku == "CBL-210"
