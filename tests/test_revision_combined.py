"""
REVISION Gate 3 - combined quotation preview + HIGH_PRIORITY handoff, plus
stale-data safety and guest high-value behaviour.

Offline; handoff log patched to keep the DB clean and count events.
"""

import json

import pytest

from tests._agent_harness import build_agent
from app.triage_config import BAND_HIGH_PRIORITY
from app.quotation import TBC
from app.agent import execute_tool as _real_execute


def _capture_handoffs(monkeypatch):
    """Install a handoff-event sink AFTER build_agent (overrides harness no-op)."""
    events = []
    monkeypatch.setattr(
        "app.handoff.log_sales_event",
        lambda **kw: events.append(kw) or {"success": True},
    )
    return events


def _price_result(subtotal):
    return {
        "success": True, "customer_id": "CUST-001", "sku": "CBL-210",
        "product_name": "Industrial Cable", "quantity": 100,
        "unit_price": subtotal / 100, "price_source": "CUSTOMER_CONTRACT",
        "subtotal": subtotal,
    }


def _preview_payloads(agent):
    out = []
    for m in agent.messages:
        if m["role"] == "user" and isinstance(m["content"], list):
            for b in m["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    try:
                        p = json.loads(b["content"])
                    except Exception:
                        continue
                    if p.get("status") == "PREVIEW":
                        out.append(p)
    return out


# ----------------------------------------------------------------------
# 1. quotation request + verified pricing + HIGH_PRIORITY
#    -> quotation preview + ONE human handoff
# ----------------------------------------------------------------------

def test_quotation_and_high_priority(monkeypatch):
    monkeypatch.setattr(
        "app.agent.execute_tool",
        lambda n, i: (_price_result(6000) if n == "get_customer_price"
                      else _real_execute(n, i)),
    )
    script = [
        [("find_customer", {"phone": "+6581658457"})],            # GOLD
        [("find_product", {"query": "Industrial Cable"})],
        [("update_enquiry_signals", {"business_customer": True, "quantity": 100,
                                      "quotation_requested": True, "urgent": True})],
        [("get_customer_price", {"customer_id": "CUST-001", "sku": "CBL-210",
                                 "quantity": 100})],
        [("generate_quotation_preview", {})],
        "Here is your preview. I've also referred this to our sales team.",
    ]
    agent, tools = build_agent(monkeypatch, script, phone="+6581658457")
    handoff_log = _capture_handoffs(monkeypatch)
    agent.send("100 Industrial Cable for ABC Construction, quotation urgently.")

    assert agent.last_triage.priority_band == BAND_HIGH_PRIORITY
    # Exactly one automatic handoff.
    high = [e for e in handoff_log if "[high_priority]" in e["details"]]
    assert len(high) == 1
    # Preview produced from verified data.
    previews = _preview_payloads(agent)
    assert previews
    assert previews[-1]["fields"]["sku"] == "CBL-210"
    assert previews[-1]["fields"]["subtotal"] == "SGD 6000.00"
    # No order / no discount approval.
    assert "create_order" not in tools
    assert agent.pending_approval is None


# ----------------------------------------------------------------------
# 2. Quantity correction -> stale subtotal removed -> old amount not shown
# ----------------------------------------------------------------------

def test_quantity_correction_no_stale_amount(monkeypatch):
    monkeypatch.setattr(
        "app.agent.execute_tool",
        lambda n, i: (_price_result(6000) if n == "get_customer_price"
                      else _real_execute(n, i)),
    )
    script = [
        [("find_product", {"query": "Industrial Cable"})],
        [("update_enquiry_signals", {"quantity": 100})],
        [("get_customer_price", {"customer_id": "CUST-001", "sku": "CBL-210",
                                 "quantity": 100})],
        "Priced.",
        # Correction: quantity changes -> verified_subtotal invalidated.
        [("update_enquiry_signals", {"quantity": 5})],
        [("generate_quotation_preview", {})],
        "Updated preview.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _capture_handoffs(monkeypatch)
    agent.send("Industrial Cable, 100 units, price it.")
    assert agent.enquiry.verified_subtotal == 6000.0
    agent.send("Actually make that 5.")
    assert agent.enquiry.verified_subtotal is None
    preview = _preview_payloads(agent)[-1]
    assert preview["fields"]["subtotal"] == TBC
    assert "6000" not in preview["message"]


# ----------------------------------------------------------------------
# 3. Product correction -> stale product/subtotal removed -> not shown
# ----------------------------------------------------------------------

def test_product_correction_no_stale_info(monkeypatch):
    monkeypatch.setattr(
        "app.agent.execute_tool",
        lambda n, i: (_price_result(6000) if n == "get_customer_price"
                      else _real_execute(n, i)),
    )
    script = [
        [("find_product", {"query": "Industrial Cable"})],
        [("update_enquiry_signals", {"quantity": 100})],
        [("get_customer_price", {"customer_id": "CUST-001", "sku": "CBL-210",
                                 "quantity": 100})],
        "Priced.",
        # Genuine product switch -> product + subtotal invalidated.
        [("update_enquiry_signals", {"product_query": "Industrial Adapter"})],
        [("generate_quotation_preview", {})],
        "Updated preview.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _capture_handoffs(monkeypatch)
    agent.send("Industrial Cable, 100 units, price it.")
    assert agent.enquiry.product_sku == "CBL-210"
    agent.send("Actually I mean Industrial Adapter.")
    assert agent.enquiry.product_sku is None
    assert agent.enquiry.verified_subtotal is None
    preview = _preview_payloads(agent)[-1]
    assert preview["fields"]["sku"] == TBC
    assert preview["fields"]["subtotal"] == TBC
    assert "CBL-210" not in preview["message"]
    assert "6000" not in preview["message"]


# ----------------------------------------------------------------------
# 4. Subsequent HIGH_PRIORITY messages -> no duplicate handoff
# ----------------------------------------------------------------------

def test_subsequent_high_priority_no_duplicate(monkeypatch):
    script = [
        [("update_enquiry_signals", {"business_customer": True, "quantity": 100,
                                      "quotation_requested": True, "urgent": True})],
        "Referred.",
        [("update_enquiry_signals", {"urgent": True})],
        "Noted.",
        [("update_enquiry_signals", {"business_customer": True})],
        "Noted.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    handoff_log = _capture_handoffs(monkeypatch)
    agent.send("Business, 100 units, quotation, urgent.")
    agent.send("Still urgent.")
    agent.send("Still a business.")
    high = [e for e in handoff_log if "[high_priority]" in e["details"]]
    assert len(high) == 1


# ----------------------------------------------------------------------
# 5. New/guest high-value business customer -> HIGH_PRIORITY + handoff,
#    no invented customer_id
# ----------------------------------------------------------------------

def test_guest_high_value_handoff_no_invented_id(monkeypatch):
    script = [
        [("find_customer", {"phone": "+6599990002"})],   # not found -> guest
        [("update_enquiry_signals", {"company_name": "ABC Construction",
                                      "business_customer": True, "quantity": 100,
                                      "quotation_requested": True, "urgent": True})],
        "Referred to sales.",
    ]
    agent, tools = build_agent(monkeypatch, script, phone="+6599990002")
    handoff_log = _capture_handoffs(monkeypatch)
    agent.send("We're ABC Construction, 100 units, quotation urgently.")
    assert agent.enquiry.existing_customer is False
    assert agent.enquiry.customer_id is None            # not invented
    assert agent.last_triage.priority_band == BAND_HIGH_PRIORITY
    high = [e for e in handoff_log if "[high_priority]" in e["details"]]
    assert len(high) == 1
    # handoff context reflects guest, not a fabricated id.
    assert "customer=guest" in high[0]["details"]
