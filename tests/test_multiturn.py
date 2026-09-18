"""
Batch 4 tests: multi-turn agent behaviour, corrections, quotation cancellation,
and FAQ topic switching that preserves accumulated sales-enquiry state.

Offline only, scripted mock Claude client. Each agent.send() call consumes one
scripted "turn" (a tool_use list followed by a final text, or just text).
"""

import pytest

from tests._agent_harness import build_agent
from app.triage_config import (
    BAND_ROUTINE,
    BAND_SALES_OPPORTUNITY,
    BAND_HIGH_PRIORITY,
)


# ----------------------------------------------------------------------
# 27. Multi-turn sales signals accumulate across turns
# ----------------------------------------------------------------------

def test_multiturn_accumulation(monkeypatch):
    script = [
        # Turn 1: "I need Industrial Cable." -> discovery
        [("find_product", {"query": "Industrial Cable"})],
        "Sure - how many units?",
        # Turn 2: "30 units."
        [("update_enquiry_signals", {"quantity": 30})],
        "Got it, 30 units. Is this for a business?",
        # Turn 3: "For ABC Construction."
        [("update_enquiry_signals", {"business_customer": True,
                                      "company_name": "ABC Construction"})],
        "Thanks. Anything else you need?",
        # Turn 4: "I need a quotation urgently."
        [("update_enquiry_signals", {"quotation_requested": True, "urgent": True})],
        "Noted - I'll prepare that with the details I have.",
    ]
    agent, tools = build_agent(monkeypatch, script)

    agent.send("I need Industrial Cable.")
    agent.send("30 units.")
    agent.send("For ABC Construction.")
    agent.send("I need a quotation urgently.")

    e = agent.enquiry
    assert e.product_sku == "CBL-210"        # verified once discovery succeeded
    assert e.product_name == "Industrial Cable"
    assert e.quantity == 30
    assert e.business_customer is True
    assert e.company_name == "ABC Construction"
    assert e.quotation_requested is True
    assert e.urgent is True

    # business1 + bulk2 + quotation2 + urgent1 = 6 (guest) -> HIGH_PRIORITY
    assert agent.last_triage.opportunity_value_score == 6
    assert agent.last_triage.priority_band == BAND_HIGH_PRIORITY


# ----------------------------------------------------------------------
# 28. Quantity correction updates current state (and re-triages)
# ----------------------------------------------------------------------

def test_quantity_correction_updates_state(monkeypatch):
    script = [
        [("update_enquiry_signals", {"quantity": 30})],
        "Noted, 30 units.",
        [("update_enquiry_signals", {"quantity": 50})],
        "Updated to 50 units.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    agent.send("30 units.")
    assert agent.enquiry.quantity == 30
    agent.send("Actually make that 50.")
    assert agent.enquiry.quantity == 50


# ----------------------------------------------------------------------
# 29. Quotation cancellation removes the current quotation signal + points
# ----------------------------------------------------------------------

def test_quotation_cancellation(monkeypatch):
    script = [
        [("update_enquiry_signals", {"quotation_requested": True})],
        "I'll prepare a quotation.",
        [("update_enquiry_signals", {"quotation_requested": False})],
        "No problem, I won't prepare a quotation.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    agent.send("I need a quotation.")
    assert agent.enquiry.quotation_requested is True
    assert agent.last_triage.opportunity_value_score == 2  # quotation point

    agent.send("I don't need a quotation anymore.")
    assert agent.enquiry.quotation_requested is False
    assert agent.last_triage.opportunity_value_score == 0  # point removed


# ----------------------------------------------------------------------
# 30 & 31. Temporary FAQ topic switch preserves sales-enquiry state
# ----------------------------------------------------------------------

def test_faq_topic_switch_preserves_state(monkeypatch):
    script = [
        # Build up a sales enquiry.
        [("find_product", {"query": "Industrial Cable"})],
        "How many units?",
        [("update_enquiry_signals", {"quantity": 30, "business_customer": True})],
        "Got it.",
        # Customer temporarily asks an FAQ.
        [("lookup_faq", {"query": "What time do you close?"})],
        "I can't confirm our hours right now.",
        # Customer returns to the sales enquiry.
        [("update_enquiry_signals", {"quotation_requested": True})],
        "I'll continue with your order details.",
    ]
    agent, tools = build_agent(monkeypatch, script)

    agent.send("I need Industrial Cable.")
    agent.send("30 units, for my business.")

    # Snapshot before the FAQ detour.
    assert agent.enquiry.product_sku == "CBL-210"
    assert agent.enquiry.quantity == 30
    assert agent.enquiry.business_customer is True

    # FAQ detour must NOT wipe accumulated sales state.
    agent.send("What time do you close?")
    assert agent.enquiry.product_sku == "CBL-210"
    assert agent.enquiry.quantity == 30
    assert agent.enquiry.business_customer is True

    # Returning to the enquiry continues using previous state.
    agent.send("Okay, and I need a quotation.")
    assert agent.enquiry.quantity == 30            # still there
    assert agent.enquiry.business_customer is True
    assert agent.enquiry.quotation_requested is True
    # business1 + bulk2 + quotation2 = 5 -> SALES_OPPORTUNITY (guest)
    assert agent.last_triage.opportunity_value_score == 5
    assert agent.last_triage.priority_band == BAND_SALES_OPPORTUNITY
