"""
REVISION Gate 1 - HIGH_PRIORITY automatic human sales handoff (idempotent).

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


# ----------------------------------------------------------------------
# 1. ROUTINE does not automatically hand off
# ----------------------------------------------------------------------

def test_routine_no_auto_handoff(monkeypatch):
    script = [
        [("update_enquiry_signals", {"urgent": True})],  # total 1 -> ROUTINE
        "Noted.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    handoff_log = _capture_handoffs(monkeypatch)
    agent.send("It's a bit urgent.")
    assert agent.last_triage.priority_band == BAND_ROUTINE
    assert handoff_log == []
    assert agent._auto_handoff_done is False


# ----------------------------------------------------------------------
# 2. SALES_OPPORTUNITY does not automatically hand off
# ----------------------------------------------------------------------

def test_sales_opportunity_no_auto_handoff(monkeypatch):
    script = [
        # quotation(2) + urgent(1) = 3 -> SALES_OPPORTUNITY
        [("update_enquiry_signals", {"quotation_requested": True, "urgent": True})],
        "Noted.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    handoff_log = _capture_handoffs(monkeypatch)
    agent.send("Quotation, urgent.")
    assert agent.last_triage.priority_band == BAND_SALES_OPPORTUNITY
    assert handoff_log == []


# ----------------------------------------------------------------------
# 3. HIGH_PRIORITY automatically creates a human sales handoff
# ----------------------------------------------------------------------

def test_high_priority_auto_handoff(monkeypatch):
    script = [
        [("update_enquiry_signals", {"business_customer": True, "quantity": 100,
                                      "quotation_requested": True, "urgent": True})],
        "Thanks - I've referred this to our sales team.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    handoff_log = _capture_handoffs(monkeypatch)
    agent.send("Business, 100 units, quotation, urgent.")
    assert agent.last_triage.priority_band == BAND_HIGH_PRIORITY
    assert len(handoff_log) == 1
    assert handoff_log[0]["event_type"] == EVENT_HUMAN_HANDOFF_REQUESTED
    assert "[high_priority]" in handoff_log[0]["details"]
    assert agent._auto_handoff_done is True


# ----------------------------------------------------------------------
# 4. Re-evaluating the same HIGH_PRIORITY enquiry does NOT duplicate
# ----------------------------------------------------------------------

def test_high_priority_handoff_idempotent(monkeypatch):
    script = [
        [("update_enquiry_signals", {"business_customer": True, "quantity": 100,
                                      "quotation_requested": True, "urgent": True})],
        "Referred to sales.",
        # Another message that keeps it HIGH_PRIORITY (re-evaluates triage).
        [("update_enquiry_signals", {"urgent": True})],
        "Still noted.",
        # And another.
        [("update_enquiry_signals", {"quotation_requested": True})],
        "Noted again.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    handoff_log = _capture_handoffs(monkeypatch)
    agent.send("Business, 100 units, quotation, urgent.")
    agent.send("Still urgent please.")
    agent.send("Yes I still want a quotation.")
    assert agent.last_triage.priority_band == BAND_HIGH_PRIORITY
    # Exactly ONE auto handoff across all re-evaluations.
    assert len(handoff_log) == 1


# ----------------------------------------------------------------------
# 5. Explicit human request creates handoff regardless of score
# ----------------------------------------------------------------------

def test_explicit_request_handoff_at_routine(monkeypatch):
    script = [
        [("request_human_handoff", {"reason": "customer asked for a salesperson"})],
        "I've flagged this for our sales team.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    handoff_log = _capture_handoffs(monkeypatch)
    agent.send("Can a salesperson call me?")  # no sales signals -> ROUTINE band
    assert agent.enquiry.human_requested is True
    assert len(handoff_log) == 1
    assert "[explicit_request]" in handoff_log[0]["details"]


def test_explicit_and_auto_are_distinct_triggers(monkeypatch):
    # Explicit request AND high priority in one enquiry: distinct triggers,
    # and the automatic one still fires at most once.
    script = [
        [("update_enquiry_signals", {"business_customer": True, "quantity": 100,
                                      "quotation_requested": True, "urgent": True})],
        "Referred to sales.",
        [("request_human_handoff", {"reason": "customer asked for a salesperson"})],
        "Also flagged explicitly.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    handoff_log = _capture_handoffs(monkeypatch)
    agent.send("Business, 100 units, quotation, urgent.")   # auto handoff (1)
    agent.send("Actually, please connect me to sales.")     # explicit handoff (1)
    triggers = [e["details"].split("]")[0] + "]" for e in handoff_log]
    assert "[high_priority]" in " ".join(triggers)
    assert "[explicit_request]" in " ".join(triggers)
    # Auto handoff still only once even though it stayed HIGH_PRIORITY.
    high = [e for e in handoff_log if "[high_priority]" in e["details"]]
    assert len(high) == 1


# ----------------------------------------------------------------------
# 6. Handoff failure does not falsely tell the customer it succeeded
# ----------------------------------------------------------------------

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
    # The tool result the agent saw reports failure (not a fake success).
    # Find the recorded activity for the handoff.
    handoff_entries = [e for e in agent.activity_log
                       if e["type"] == "human_handoff_requested"]
    assert handoff_entries
    result = handoff_entries[-1]["data"]["result"]
    assert result["success"] is False
    assert result["status"] == "ERROR"


# ----------------------------------------------------------------------
# 7 & 8. HIGH_PRIORITY does NOT auto-create order / auto-approve discount
# ----------------------------------------------------------------------

def test_high_priority_no_order_no_discount_approval(monkeypatch):
    script = [
        [("update_enquiry_signals", {"business_customer": True, "quantity": 100,
                                      "quotation_requested": True, "urgent": True})],
        "Referred to sales.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _capture_handoffs(monkeypatch)
    agent.send("Business, 100 units, quotation, urgent.")
    assert agent.last_triage.priority_band == BAND_HIGH_PRIORITY
    assert "create_order" not in tools
    assert "check_discount_authority" not in tools
    assert agent.pending_approval is None
