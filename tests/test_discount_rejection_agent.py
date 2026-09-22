"""
Feature A - DISCOUNT REJECTION, SalesAgent continuation + deterministic
grounding. Offline scripted mock Claude (tests/_agent_harness.py); no live
LLM / WhatsApp / network. No DB writes (handoff logger is stubbed by the
harness; no create_order is invoked in these flows).
"""

import pytest

from tests._agent_harness import build_agent


def _last_assistant_text(agent):
    for m in reversed(agent.messages):
        if m["role"] != "assistant":
            continue
        content = m["content"]
        if isinstance(content, str):
            return content
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif getattr(b, "type", None) == "text":
                parts.append(getattr(b, "text", ""))
        return "\n".join(parts)
    return None


def _pending_discount(agent, requested=10.0):
    agent.pending_approval = {
        "type": "DISCOUNT",
        "requested_discount_percent": requested,
        "ai_authority_limit_percent": 5,
        "status": "PENDING",
    }


# A5/A6 - rejection continuation resumes and clearly tells the customer the
# requested discount was NOT approved.
def test_rejection_continuation_informs_customer(monkeypatch):
    script = [
        "Understood, I'll let them know.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _pending_discount(agent, requested=10.0)

    result = agent.apply_human_rejection(requested_discount_percent=10.0)
    assert result["success"] is True
    reply = result["response"]
    assert "could not be approved" in reply.lower()
    assert "10%" in reply
    # returned == stored history.
    assert _last_assistant_text(agent) == reply


# A7 - HOSTILE model: model claims approval; final response must NOT expose it.
def test_rejection_blocks_false_approval_claim(monkeypatch):
    script = [
        "Great news, your requested 10% discount was approved!",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _pending_discount(agent, requested=10.0)

    result = agent.apply_human_rejection(requested_discount_percent=10.0)
    reply = result["response"]
    assert "approved" not in reply.lower() or "not" in reply.lower()
    # Specifically, the false affirmative claim must be gone.
    assert "was approved" not in reply.lower()
    assert "could not be approved" in reply.lower()
    assert _last_assistant_text(agent) == reply


# A8 - rejection does NOT call create_order.
def test_rejection_does_not_call_create_order(monkeypatch):
    script = [
        "Okay.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _pending_discount(agent)
    agent.apply_human_rejection(requested_discount_percent=10.0)
    assert "create_order" not in tools


# Trusted requested percent comes from stored state, not the caller value.
def test_rejection_uses_trusted_stored_requested_percent(monkeypatch):
    script = ["ok"]
    agent, tools = build_agent(monkeypatch, script)
    _pending_discount(agent, requested=12.0)
    # Caller passes a WRONG value; stored 12.0 must win.
    result = agent.apply_human_rejection(requested_discount_percent=999.0)
    reply = result["response"]
    assert "12%" in reply
    assert "999" not in reply


# No pending approval -> safe error, no resume.
def test_rejection_without_pending_returns_error(monkeypatch):
    script = ["should not be used"]
    agent, tools = build_agent(monkeypatch, script)
    agent.pending_approval = None
    result = agent.apply_human_rejection(requested_discount_percent=10.0)
    assert result["success"] is False
    assert result["error"] == "NO_PENDING_APPROVAL"


# A9 - reject then customer accepts base price: normal flow available.
def test_reject_then_accept_base_price_flow_available(monkeypatch):
    script = [
        # continuation after rejection
        "Understood.",
        # next customer turn: proceed at base price -> normal (no tools here,
        # but the agent must accept a fresh send and produce a reply).
        "Sure, I'll set that up at the standard price.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _pending_discount(agent)
    r1 = agent.apply_human_rejection(requested_discount_percent=10.0)
    assert "could not be approved" in r1["response"].lower()

    r2 = agent.send("Okay, proceed at the original price.")
    assert r2["success"] is True
    # No order was auto-created by the rejection or the follow-up text turn.
    assert "create_order" not in tools


# A10 - reject then decline: no order created.
def test_reject_then_decline_no_order(monkeypatch):
    script = [
        "Understood.",
        "No problem, let us know if you change your mind.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _pending_discount(agent)
    agent.apply_human_rejection(requested_discount_percent=10.0)
    agent.send("No thanks.")
    assert "create_order" not in tools


# Rejection continuation does not leave a stale rejection flag for a later
# ordinary turn (grounding reset each send()).
def test_rejection_flag_not_leaked_into_next_turn(monkeypatch):
    script = [
        "Understood.",
        "Anything else I can help with?",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _pending_discount(agent)
    agent.apply_human_rejection(requested_discount_percent=10.0)
    r2 = agent.send("Thanks, that's all.")
    assert "could not be approved" not in r2["response"].lower()
    assert r2["response"] == "Anything else I can help with?"
