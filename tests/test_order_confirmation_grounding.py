"""
Regression: customer-facing reply AFTER a SUCCESSFUL create_order.

LIVE BUG (staging 89bf0cc): after a human approved an 8% discount, the
customer said "yes, proceed", the trusted create_order tool returned
success=True / status=CONFIRMED / a real order_id (SalesOps showed the order
CONFIRMED), but the customer-facing WhatsApp reply was Claude's stale
"I need to get final approval ... sent for review ... confirm with you
shortly." message. That is wrong - the order already exists.

Root cause: _finalize_customer_response had NO deterministic order-confirmation
rendering for the normal create_order-success path; it returned Claude's raw
draft, which followed the SYSTEM_PROMPT's escalation wording.

Fix: when create_order succeeds THIS response cycle, the finalizer must
render an AUTHORITATIVE trusted confirmation (order reference + status) from
the trusted create_order result, discarding any contradicting model draft.

All offline; create_order is stubbed at the execute_tool seam so the
committed DB is never written.
"""

import pytest

from tests._agent_harness import build_agent
import app.agent as agent_module

SKU, QTY = "CBL-210", 12
AREA, DATE = "Tuas", "2026-09-23"
ORDER_ID = "SO-DEMO-TESTORDER-1"


def _order_input():
    return {
        "phone": "+6580000000",
        "customer_id": "CUST-001",
        "items": [{"sku": SKU, "quantity": QTY, "unit_price": 12.0}],
        "product_subtotal": 144.0,
        "discount_percent": 8.0,
        "delivery_fee": 35.0,
        "final_total": 167.48,
        "delivery_area": AREA,
        "delivery_date": DATE,
    }


def _stub_create_order_success(monkeypatch):
    real_execute = agent_module.execute_tool

    def fake_execute_tool(tool_name, tool_input):
        if tool_name == "create_order":
            # Mirror the real create_order success contract.
            return {
                "success": True,
                "order_id": ORDER_ID,
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


# The exact live failure: create_order succeeds, model draft wrongly claims
# the order still needs approval -> customer must NOT see that claim; must
# see a trusted confirmation with the real order reference.
def test_successful_order_yields_trusted_confirmation_not_needs_approval(
    monkeypatch,
):
    _stub_create_order_success(monkeypatch)
    script = [
        [("create_order", _order_input())],
        # HOSTILE / stale model draft (reproduces the live wrong message):
        "I need to get final approval from our sales team before I can "
        "create this order. Your request has been sent for review and "
        "we'll confirm with you shortly.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("Yes, proceed with the order.")
    reply = result["response"]

    # The wrong "needs approval / sent for review" claim must be gone.
    assert "final approval" not in reply.lower()
    assert "sent for review" not in reply.lower()
    assert "confirm with you shortly" not in reply.lower()

    # The customer must receive a trusted confirmation referencing the real
    # order id, treating the CONFIRMED create_order result as authoritative.
    assert ORDER_ID in reply
    lower = reply.lower()
    assert ("order" in lower and ("confirm" in lower or "created" in lower))

    # returned == stored assistant history.
    stored = None
    for m in reversed(agent.messages):
        if m["role"] == "assistant" and isinstance(m["content"], str):
            stored = m["content"]
            break
    assert stored == reply


# A FAILED create_order must NOT produce a false confirmation.
def test_failed_order_does_not_produce_confirmation(monkeypatch):
    real_execute = agent_module.execute_tool

    def fake_execute_tool(tool_name, tool_input):
        if tool_name == "create_order":
            return {"success": False, "error": "ORDER_CREATION_FAILED",
                    "message": "db error"}
        return real_execute(tool_name, tool_input)

    monkeypatch.setattr(agent_module, "execute_tool", fake_execute_tool)

    script = [
        [("create_order", _order_input())],
        "Sorry, something went wrong creating your order.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("Yes, proceed with the order.")
    reply = result["response"]
    # No fabricated order reference / confirmation on failure.
    assert ORDER_ID not in reply
    # Claude's own (non-confirmation) text is preserved on failure.
    assert reply == "Sorry, something went wrong creating your order."


# A normal turn with NO create_order must be unaffected (draft passthrough).
def test_non_order_turn_unaffected(monkeypatch):
    script = ["Sure, how many units would you like?"]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("Do you sell industrial cable?")
    assert result["response"] == "Sure, how many units would you like?"
