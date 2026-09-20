"""
Batch 5 - Task 21: end-to-end mocked SalesAgent scenarios (A-J) plus order
safety, handoff safety, and response hygiene.

Offline only: a scripted mock Claude client returns predetermined tool_use
sequences and final text. We assert on tools invoked (present AND absent),
resulting EnquiryState / triage, side-effect absence, and reply hygiene.
We do NOT test a live model's intelligence.
"""

import pytest

from tests._agent_harness import build_agent
from app.triage_config import (
    BAND_ROUTINE,
    BAND_SALES_OPPORTUNITY,
    BAND_HIGH_PRIORITY,
)
from app.handoff import EVENT_HUMAN_HANDOFF_REQUESTED


BANNED_LEAKS = [
    "ROUTINE", "SALES_OPPORTUNITY", "HIGH_PRIORITY",
    "priority", "score", "priority_reasons",
    "update_enquiry_signals", "lookup_faq", "find_product",
    "check_inventory", "get_customer_price", "request_human_handoff",
    "Traceback", "Exception",
]


def _assert_clean(reply):
    low = reply.lower()
    for banned in BANNED_LEAKS:
        assert banned.lower() not in low, banned


# ======================================================================
# SCENARIO A - ROUTINE FAQ
# ======================================================================

def test_scenario_a_routine_faq(monkeypatch):
    script = [
        [("lookup_faq", {"query": "What time do you close?"})],
        "I'm not able to confirm our opening hours right now, but I can help "
        "with anything else.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("What time do you close?")
    assert "lookup_faq" in tools
    for t in ["find_customer", "check_inventory", "get_customer_price",
              "create_order", "request_human_handoff"]:
        assert t not in tools
    # unconfirmed FAQ -> no fabricated hours, no leak
    assert "UNCONFIRMED" not in result["response"]
    _assert_clean(result["response"])


# ======================================================================
# SCENARIO B - ROUTINE PRODUCT ENQUIRY (guest)
# ======================================================================

def test_scenario_b_routine_product_enquiry(monkeypatch):
    script = [
        [("find_product", {"query": "Industrial Cable"})],
        [("check_inventory", {"sku": "CBL-210", "requested_quantity": 5})],
        "Yes, we can supply 5 of those.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("Do you have 5 Industrial Cable?")
    assert tools.index("find_product") < tools.index("check_inventory")
    assert agent.enquiry.product_sku == "CBL-210"
    # guest, no invented id, no order
    assert agent.enquiry.existing_customer is False
    assert agent.enquiry.customer_id is None
    assert "create_order" not in tools
    _assert_clean(result["response"])


# ======================================================================
# SCENARIO C - SALES OPPORTUNITY (existing STANDARD customer)
# ======================================================================

def test_scenario_c_sales_opportunity(monkeypatch):
    script = [
        [("find_customer", {"phone": "+6582094108"})],   # STANDARD (CUST-002)
        [("find_product", {"query": "Industrial Cable"})],
        [("update_enquiry_signals", {"quantity": 30, "business_customer": True})],
        "Thanks - I've noted 30 units for your company.",
    ]
    agent, tools = build_agent(monkeypatch, script, phone="+6582094108")
    result = agent.send("I need 30 Industrial Cable for my company.")

    t = agent.last_triage
    assert t.customer_value_score == 1        # existing(1) + STANDARD(0)
    assert t.opportunity_value_score == 3     # business(1) + bulk(2)
    assert t.total_priority_score == 4
    assert t.priority_band == BAND_SALES_OPPORTUNITY
    # no auto side effects
    assert "create_order" not in tools
    assert "request_human_handoff" not in tools
    _assert_clean(result["response"])


# ======================================================================
# SCENARIO D - NEW HIGH-PRIORITY ENQUIRY (guest)
# ======================================================================

def test_scenario_d_new_high_priority(monkeypatch):
    script = [
        [("find_customer", {"phone": "+6599990001"})],   # not found -> guest
        [("update_enquiry_signals", {
            "company_name": "ABC Construction", "business_customer": True,
            "quantity": 100, "quotation_requested": True, "urgent": True})],
        [("find_product", {"query": "Industrial Cable"})],
        "Thanks - I have your requirements and I'll proceed with the details.",
    ]
    agent, tools = build_agent(monkeypatch, script, phone="+6599990001")
    result = agent.send(
        "We're ABC Construction. We need 100 Industrial Cable and a "
        "quotation urgently."
    )

    e = agent.enquiry
    assert e.existing_customer is False
    assert e.customer_id is None
    assert e.company_name == "ABC Construction"
    assert e.business_customer is True
    assert e.quantity == 100
    assert e.quotation_requested is True
    assert e.urgent is True
    assert e.product_sku == "CBL-210"

    t = agent.last_triage
    assert t.customer_value_score == 0
    assert t.opportunity_value_score == 6     # business1+bulk2+quote2+urgent1
    assert t.total_priority_score == 6
    assert t.priority_band == BAND_HIGH_PRIORITY

    # DECOUPLED behaviour: HIGH_PRIORITY is sales-priority only. It does NOT
    # create a handoff, an order, or a discount approval. The AI continues.
    assert "create_order" not in tools
    assert "check_discount_authority" not in tools
    assert "request_human_handoff" not in tools
    assert agent.pending_approval is None
    _assert_clean(result["response"])


# ======================================================================
# SCENARIO E - MULTI-TURN
# ======================================================================

def test_scenario_e_multiturn(monkeypatch):
    script = [
        [("find_product", {"query": "Industrial Cable"})],
        "How many units?",
        [("update_enquiry_signals", {"quantity": 30})],
        "Is this for a business?",
        [("update_enquiry_signals", {"business_customer": True,
                                     "company_name": "ABC Construction"})],
        "Noted.",
        [("update_enquiry_signals", {"quotation_requested": True, "urgent": True})],
        "I'll proceed with those details.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    agent.send("I need Industrial Cable.")
    agent.send("30 units.")
    agent.send("For ABC Construction.")
    agent.send("I need a quotation urgently.")

    e = agent.enquiry
    assert e.product_sku == "CBL-210"
    assert e.quantity == 30
    assert e.business_customer is True
    assert e.company_name == "ABC Construction"
    assert e.quotation_requested is True
    assert e.urgent is True
    assert agent.last_triage.opportunity_value_score == 6


# ======================================================================
# SCENARIO F - CORRECTION
# ======================================================================

def test_scenario_f_correction(monkeypatch):
    script = [
        [("find_product", {"query": "Industrial Cable"})],
        "How many?",
        [("update_enquiry_signals", {"quantity": 30, "business_customer": True,
                                     "company_name": "ABC", "urgent": True,
                                     "quotation_requested": True})],
        "Noted.",
        [("update_enquiry_signals", {"quantity": 50})],
        "Updated to 50.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    agent.send("I need Industrial Cable.")
    agent.send("30 units, business, ABC, urgent, quotation.")
    agent.send("Actually make that 50.")

    e = agent.enquiry
    assert e.quantity == 50
    # Unchanged context (product_sku stays because product_query didn't change).
    assert e.product_sku == "CBL-210"
    assert e.business_customer is True
    assert e.company_name == "ABC"
    assert e.quotation_requested is True
    assert e.urgent is True


# ======================================================================
# SCENARIO G - QUOTATION CANCELLATION
# ======================================================================

def test_scenario_g_quotation_cancellation(monkeypatch):
    script = [
        [("update_enquiry_signals", {"quotation_requested": True})],
        "I'll prepare a quotation.",
        [("update_enquiry_signals", {"quotation_requested": False})],
        "No problem.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    agent.send("I need a quotation.")
    assert agent.last_triage.opportunity_value_score == 2
    agent.send("I don't need a quotation anymore.")
    assert agent.enquiry.quotation_requested is False
    assert agent.last_triage.opportunity_value_score == 0


# ======================================================================
# SCENARIO H - EXPLICIT HUMAN (score-independent)
# ======================================================================

def test_scenario_h_explicit_human(monkeypatch):
    script = [
        [("request_human_handoff", {"reason": "customer asked for salesperson"})],
        "I've flagged this for our sales team.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    # Re-patch AFTER build_agent so we can count events (overrides harness no-op).
    logged = []
    monkeypatch.setattr(
        "app.handoff.log_sales_event",
        lambda **kw: logged.append(kw) or {"success": True},
    )
    result = agent.send("I want to speak to a salesperson.")
    assert agent.enquiry.human_requested is True
    assert len(logged) == 1
    assert logged[0]["event_type"] == EVENT_HUMAN_HANDOFF_REQUESTED
    assert "create_order" not in tools
    assert agent.pending_approval is None       # not a discount approval
    _assert_clean(result["response"])


# ======================================================================
# SCENARIO I - DISCOUNT (existing HITL, independent of triage)
# ======================================================================

def test_scenario_i_discount(monkeypatch):
    script = [
        [("check_discount_authority", {"requested_discount_percent": 10})],
        "I've sent that request for review.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    agent.send("Can I get 10% off?")
    assert "check_discount_authority" in tools
    assert agent.pending_approval is not None                 # HITL intact
    assert agent.pending_approval["requested_discount_percent"] == 10


# ======================================================================
# SCENARIO J - GOLD FAQ (intent != triage)
# ======================================================================

def test_scenario_j_gold_faq(monkeypatch):
    script = [
        [("find_customer", {"phone": "+6581658457"})],   # GOLD
        [("lookup_faq", {"query": "opening hours"})],
        "I can't confirm our hours right now.",
    ]
    agent, tools = build_agent(monkeypatch, script, phone="+6581658457")
    result = agent.send("What time do you close?")
    assert agent.last_triage.customer_value_score == 3       # existing+gold
    assert "request_human_handoff" not in tools
    assert "create_order" not in tools
    assert agent.pending_approval is None
    _assert_clean(result["response"])


# ======================================================================
# ORDER SAFETY
# ======================================================================

def test_high_priority_alone_does_not_create_order(monkeypatch):
    script = [
        [("update_enquiry_signals", {"business_customer": True, "quantity": 100,
                                      "quotation_requested": True, "urgent": True})],
        "Noted.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    agent.send("Business, 100 units, quotation, urgent.")
    assert agent.last_triage.priority_band == BAND_HIGH_PRIORITY
    assert "create_order" not in tools


def test_quotation_and_urgent_do_not_confirm_order(monkeypatch):
    script = [
        [("update_enquiry_signals", {"quotation_requested": True, "urgent": True})],
        "I'll prepare that.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    agent.send("I need a quotation, it's urgent.")
    assert "create_order" not in tools


# ======================================================================
# HANDOFF BEHAVIOUR (REVISED)
# ======================================================================

def test_high_priority_does_not_refer_to_sales(monkeypatch):
    # DECOUPLED requirement: HIGH_PRIORITY (sales priority) does NOT, by
    # itself, refer the enquiry to a human. No handoff tool, no order.
    script = [
        [("update_enquiry_signals", {"business_customer": True, "quantity": 100,
                                      "quotation_requested": True, "urgent": True})],
        "Noted, I'll continue helping you.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    agent.send("Business, 100 units, quotation, urgent.")
    assert agent.last_triage.priority_band == BAND_HIGH_PRIORITY
    assert "request_human_handoff" not in tools   # no handoff from band alone
    assert "create_order" not in tools


# ======================================================================
# RESPONSE HYGIENE across a representative sales reply
# ======================================================================

def test_response_hygiene_sales_reply(monkeypatch):
    script = [
        [("update_enquiry_signals", {"business_customer": True, "quantity": 100,
                                      "quotation_requested": True, "urgent": True})],
        "Thanks - I've got the quantity and quotation request noted, and I'll "
        "continue with the available details.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("Business, 100 units, quotation, urgent.")
    _assert_clean(result["response"])
