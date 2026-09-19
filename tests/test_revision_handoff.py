"""
HITL DECOUPLING (revised architecture): sales-priority band NEVER, by itself,
triggers a human handoff. Human handoff comes only from an EXPLICIT customer
request (or, separately, the teammate discount-approval workflow for discounts
beyond AI authority).

Offline, scripted mock Claude. app.handoff.log_sales_event is monkeypatched so
handoff events are counted in-memory and the committed DB is never touched.
"""

import pytest

from tests._agent_harness import build_agent
from app.triage_config import (
    BAND_ROUTINE,
    BAND_SALES_OPPORTUNITY,
    BAND_HIGH_PRIORITY,
)
from app.handoff import EVENT_HUMAN_HANDOFF_REQUESTED
from app.agent import execute_tool as _real_execute


def _capture_handoffs(monkeypatch):
    """
    Install a handoff-event sink and return the list. MUST be called AFTER
    build_agent(), because build_agent installs a default no-op logger patch;
    this re-patch overrides it so we can count events (still no DB write).
    """
    events = []
    monkeypatch.setattr(
        "app.handoff.log_sales_event",
        lambda **kw: events.append(kw) or {"success": True, "event_id": len(events)},
    )
    return events


def _handoff_count(events):
    return [e for e in events if e["event_type"] == EVENT_HUMAN_HANDOFF_REQUESTED]


# ======================================================================
# PRIORITY BAND ALONE NEVER TRIGGERS HITL
# ======================================================================

def test_routine_no_handoff(monkeypatch):
    script = [
        [("update_enquiry_signals", {"urgent": True})],  # total 1 -> ROUTINE
        "Noted.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    handoff_log = _capture_handoffs(monkeypatch)
    agent.send("It's a bit urgent.")
    assert agent.last_triage.priority_band == BAND_ROUTINE
    assert _handoff_count(handoff_log) == []
    assert "request_human_handoff" not in tools


def test_sales_opportunity_no_handoff(monkeypatch):
    script = [
        # quotation(2) + urgent(1) = 3 -> SALES_OPPORTUNITY
        [("update_enquiry_signals", {"quotation_requested": True, "urgent": True})],
        "Noted.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    handoff_log = _capture_handoffs(monkeypatch)
    agent.send("Quotation, urgent.")
    assert agent.last_triage.priority_band == BAND_SALES_OPPORTUNITY
    assert _handoff_count(handoff_log) == []
    assert "request_human_handoff" not in tools


def test_high_priority_no_handoff(monkeypatch):
    # The central decoupling assertion: HIGH_PRIORITY on its own does NOT
    # create any handoff, and the AI keeps handling the enquiry.
    script = [
        [("update_enquiry_signals", {"business_customer": True, "quantity": 100,
                                      "quotation_requested": True, "urgent": True})],
        "Thanks, I've noted those details.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    handoff_log = _capture_handoffs(monkeypatch)
    agent.send("Business, 100 units, quotation, urgent.")
    assert agent.last_triage.priority_band == BAND_HIGH_PRIORITY
    assert _handoff_count(handoff_log) == []          # NO handoff
    assert "request_human_handoff" not in tools
    assert "create_order" not in tools                # no order
    assert "check_discount_authority" not in tools    # no discount
    assert agent.pending_approval is None             # no approval


def test_high_priority_still_calculated_correctly(monkeypatch):
    # HIGH_PRIORITY must still be computed/stored/logged even though it no
    # longer triggers a side effect.
    script = [
        [("update_enquiry_signals", {"business_customer": True, "quantity": 100,
                                      "quotation_requested": True, "urgent": True})],
        "Noted.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _capture_handoffs(monkeypatch)
    agent.send("Business, 100 units, quotation, urgent.")
    t = agent.last_triage
    assert t.priority_band == BAND_HIGH_PRIORITY
    assert t.opportunity_value_score == 6             # business1+bulk2+quote2+urgent1
    # It was logged internally (never shown to the customer).
    assert any(e["type"] == "triage_evaluated" for e in agent.activity_log)


# ======================================================================
# EXPLICIT HUMAN REQUEST TRIGGERS HANDOFF AT EVERY BAND
# ======================================================================

def test_explicit_request_handoff_at_routine(monkeypatch):
    script = [
        [("request_human_handoff", {"reason": "customer asked for a salesperson"})],
        "I've flagged this for our sales team.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    handoff_log = _capture_handoffs(monkeypatch)
    agent.send("Can a salesperson call me?")          # no sales signals
    # Explicit request hands off regardless of sales priority (here the turn
    # carries no sales signals, so triage isn't even evaluated).
    assert agent.enquiry.human_requested is True
    assert len(_handoff_count(handoff_log)) == 1
    assert "[explicit_request]" in handoff_log[0]["details"]


def test_explicit_request_handoff_at_sales_opportunity(monkeypatch):
    script = [
        # Reach SALES_OPPORTUNITY, then explicitly ask for a person.
        [("update_enquiry_signals", {"quotation_requested": True, "urgent": True}),
         ("request_human_handoff", {"reason": "customer asked for a salesperson"})],
        "Flagged for sales.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    handoff_log = _capture_handoffs(monkeypatch)
    agent.send("Quotation, urgent, and please connect me to sales.")
    assert agent.last_triage.priority_band == BAND_SALES_OPPORTUNITY
    assert len(_handoff_count(handoff_log)) == 1
    assert "[explicit_request]" in handoff_log[0]["details"]


def test_explicit_request_handoff_at_high_priority(monkeypatch):
    script = [
        [("update_enquiry_signals", {"business_customer": True, "quantity": 100,
                                      "quotation_requested": True, "urgent": True}),
         ("request_human_handoff", {"reason": "customer asked for a salesperson"})],
        "Flagged for sales.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    handoff_log = _capture_handoffs(monkeypatch)
    agent.send("Business, 100 units, quotation, urgent - and connect me to sales.")
    assert agent.last_triage.priority_band == BAND_HIGH_PRIORITY
    # Exactly one handoff, and it is the EXPLICIT one (not a band-triggered one).
    assert len(_handoff_count(handoff_log)) == 1
    assert "[explicit_request]" in handoff_log[0]["details"]
    assert "[high_priority]" not in handoff_log[0]["details"]


def test_explicit_handoff_distinct_from_discount_approval(monkeypatch):
    # Explicit handoff uses the sales_events handoff path, NOT the discount
    # approval workflow (pending_approval stays untouched).
    script = [
        [("request_human_handoff", {"reason": "customer asked for a salesperson"})],
        "Flagged.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    handoff_log = _capture_handoffs(monkeypatch)
    agent.send("Please get me a salesperson.")
    assert len(_handoff_count(handoff_log)) == 1
    assert agent.pending_approval is None             # not a discount approval


# ======================================================================
# HANDOFF FAILURE IS NOT REPORTED AS SUCCESS
# ======================================================================

def test_handoff_failure_not_false_success(monkeypatch):
    script = [
        [("request_human_handoff", {"reason": "customer asked for a salesperson"})],
        "Let me try to flag this.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    # Re-patch AFTER build_agent so the failing logger wins over the harness
    # default no-op. Force the handoff persistence to raise.
    monkeypatch.setattr(
        "app.handoff.log_sales_event",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    agent.send("Connect me to sales.")
    handoff_entries = [e for e in agent.activity_log
                       if e["type"] == "human_handoff_requested"]
    assert handoff_entries
    result = handoff_entries[-1]["data"]["result"]
    assert result["success"] is False
    assert result["status"] == "ERROR"


# ======================================================================
# GOLD HERO-FLOW REGRESSION: HIGH_PRIORITY continues autonomously
# ======================================================================

def test_gold_hero_high_priority_continues_autonomously(monkeypatch):
    """
    Regression for the review's AWS hero principle: a normal authorised GOLD
    business customer with a large quantity may classify HIGH_PRIORITY, but
    the AI must keep serving them - NO handoff, NO approval, NO order created
    merely because of the priority band.

    NOTE: this isolates the PRIORITY->HANDOFF decoupling. It does NOT assert
    anything about a high-quantity HITL threshold, which remains UNDEFINED.
    We use verified seed identifiers (CUST-001 / GOLD / +6581658457), not the
    review's older 'Apex Engineering' name, because staging renamed CUST-001.
    """
    script = [
        [("find_customer", {"phone": "+6581658457"})],   # CUST-001 GOLD (staging seed)
        [("find_product", {"query": "Industrial Cable"})],
        [("update_enquiry_signals", {"business_customer": True, "quantity": 300})],
        "Sure - let me sort that out for you.",
    ]
    agent, tools = build_agent(monkeypatch, script, phone="+6581658457")
    handoff_log = _capture_handoffs(monkeypatch)
    agent.send("Same order as last month but CBL-210 make it 300. Jurong Tuesday, same price can?")

    # GOLD + business + bulk -> HIGH_PRIORITY.
    assert agent.enquiry.existing_customer is True
    assert agent.enquiry.customer_tier == "GOLD"
    assert agent.last_triage.priority_band == BAND_HIGH_PRIORITY
    # ...yet the AI continues autonomously:
    assert _handoff_count(handoff_log) == []          # NO human handoff
    assert "request_human_handoff" not in tools
    assert "create_order" not in tools                # no auto order
    assert "check_discount_authority" not in tools    # no discount involved
    assert agent.pending_approval is None
