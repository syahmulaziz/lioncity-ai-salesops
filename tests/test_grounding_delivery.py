"""
ISSUE 1 regression - delivery-fee / final-total grounding (DETERMINISTIC).

Enforcement is Python-level, not prompt-only:
  * check_delivery results are normalised in the agent so an unavailable /
    no-slot / non-numeric-fee result is flagged delivery_fee_verified=False,
    delivered_total_available=False, and carries NO usable fee (never 0).
  * A per-turn signal (reset each send) prevents a previous turn's verified
    fee from leaking into a later unavailable turn.
  * A narrow final-response guard replaces delivery-linked total /
    free-delivery claims when the current turn's delivery is unverified,
    while preserving a stated product subtotal.

The hostile-LLM tests script Claude to EMIT unsafe wording and assert the
APPLICATION neutralises it (not merely that the mock behaved).

Offline, scripted mock Claude; runtime DB read-only.
"""

import json

import pytest

from tests._agent_harness import build_agent
from app.tools.delivery import check_delivery
from app.quotation import build_quotation_preview, TBC
from app.enquiry_state import EnquiryState

# A seeded AVAILABLE slot (Jurong / 2026-09-15 / fee 35.0).
AVAIL_AREA, AVAIL_DATE, AVAIL_FEE = "Jurong", "2026-09-15", 35.0


def _delivery_payloads(agent):
    out = []
    for m in agent.messages:
        if m["role"] == "user" and isinstance(m["content"], list):
            for b in m["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    try:
                        p = json.loads(b["content"])
                    except Exception:
                        continue
                    if isinstance(p, dict) and (
                        "available" in p or p.get("reason") == "NO_DELIVERY_SLOT"
                    ):
                        out.append(p)
    return out


# ======================================================================
# 1. Unavailable delivery -> normalised trusted result: no fee, flagged
# ======================================================================

def test_unavailable_delivery_normalised_result(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": "Nowhere-Zone",
                             "delivery_date": "2099-01-01"})],
        "That slot isn't available; I can't confirm a delivery fee or total.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    agent.send("Can you deliver to Nowhere-Zone on 2099-01-01?")
    payload = _delivery_payloads(agent)[-1]
    assert payload["available"] is False
    assert payload["delivery_fee_verified"] is False
    assert payload["delivered_total_available"] is False
    assert "delivery_fee" not in payload          # no usable fee at all
    assert agent._delivery_fee_verified_this_turn is False


# ======================================================================
# 2. Missing delivery_fee is NOT converted to 0
# ======================================================================

def test_missing_delivery_fee_not_zero(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": "Nowhere-Zone",
                             "delivery_date": "2099-01-01"})],
        "That slot isn't available.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    agent.send("Deliver Nowhere-Zone 2099-01-01?")
    payload = _delivery_payloads(agent)[-1]
    assert payload.get("delivery_fee", "ABSENT") == "ABSENT"   # absent, not 0
    assert payload["delivery_fee_verified"] is False


# ======================================================================
# 3. HOSTILE LLM: delivered-total claim is BLOCKED by the application
# ======================================================================

def test_hostile_delivered_total_blocked(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": "Nowhere-Zone",
                             "delivery_date": "2099-01-01"})],
        # Claude tries to state an unverified delivered total:
        "There is no delivery slot, but your final delivered total is S$1,200.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("Deliver 100 cables to Nowhere-Zone on 2099-01-01?")
    reply = result["response"]
    # Application must NOT expose the unverified delivered-total AMOUNT.
    assert "1,200" not in reply and "1200" not in reply
    # It should say the slot/fee/total cannot be confirmed (the safe fallback
    # legitimately uses the words "delivered total" in "can't confirm a ...
    # delivered total", so we assert on the removed AMOUNT, not the phrase).
    assert "can't confirm" in reply.lower() or "cannot confirm" in reply.lower()
    # And it must have logged the guard action.
    assert any(e["type"] == "delivery_grounding_guard" for e in agent.activity_log)


# ======================================================================
# 4. HOSTILE LLM: free-delivery claim is BLOCKED
# ======================================================================

def test_hostile_free_delivery_blocked(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": "Nowhere-Zone",
                             "delivery_date": "2099-01-01"})],
        "There is no slot available, but delivery is free.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("Deliver to Nowhere-Zone on 2099-01-01?")
    reply = result["response"].lower()
    assert "free" not in reply                     # free-delivery claim removed
    assert "can't confirm" in reply or "cannot confirm" in reply


# ======================================================================
# 5. Product-subtotal negative control: allowed + preserved
# ======================================================================

def test_product_subtotal_preserved_when_delivery_unverified(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": "Nowhere-Zone",
                             "delivery_date": "2099-01-01"})],
        # Reply states subtotal (legitimate) AND an unverified delivered total.
        "The product subtotal is S$1,200. Your final delivered total is S$1,235.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("100 cables delivered to Nowhere-Zone on 2099-01-01?")
    reply = result["response"]
    # Subtotal preserved:
    assert "1,200" in reply
    assert "product subtotal" in reply.lower()
    # Unverified delivered-total AMOUNT removed (the safe fallback may still
    # contain the words "delivered total" in a "can't confirm" clause):
    assert "1,235" not in reply and "1235" not in reply
    assert "can't confirm" in reply.lower() or "cannot confirm" in reply.lower()


def test_bare_subtotal_reply_not_blocked(monkeypatch):
    # A reply with ONLY a product subtotal (no delivery claim) must pass
    # through untouched even after an unavailable delivery check.
    script = [
        [("check_delivery", {"delivery_area": "Nowhere-Zone",
                             "delivery_date": "2099-01-01"})],
        "The product subtotal is S$1,200. That delivery date isn't available.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("100 cables, deliver Nowhere-Zone 2099-01-01?")
    reply = result["response"]
    assert reply == "The product subtotal is S$1,200. That delivery date isn't available."


# ======================================================================
# 6. Available-delivery positive control: verified fee, guard does NOT block
# ======================================================================

def test_available_delivery_verified_and_not_blocked(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE})],
        f"Delivery to {AVAIL_AREA} on {AVAIL_DATE} is S${AVAIL_FEE:.0f}. "
        "Your delivered total is S$1,235.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send(f"Deliver to {AVAIL_AREA} on {AVAIL_DATE}?")
    payload = _delivery_payloads(agent)[-1]
    assert payload["available"] is True
    assert payload["delivery_fee_verified"] is True
    assert payload["delivery_fee"] == AVAIL_FEE    # trusted fee preserved
    assert agent._delivery_fee_verified_this_turn is True
    # Guard must NOT touch a verified-delivery reply.
    assert "1,235" in result["response"]
    assert "delivered total" in result["response"].lower()


# ======================================================================
# 7. Stale-turn regression: Turn 1 verified fee cannot leak into Turn 2
# ======================================================================

def test_stale_turn_fee_cannot_leak(monkeypatch):
    script = [
        # Turn 1: available slot -> verified fee.
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE})],
        f"Delivery is S${AVAIL_FEE:.0f}; delivered total S$1,235.",
        # Turn 2: customer changes date -> unavailable; Claude (hostile) tries
        # to reuse the earlier fee/total.
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": "2099-01-01"})],
        "Using the same delivery, your final delivered total is S$1,235.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    r1 = agent.send(f"Deliver to {AVAIL_AREA} on {AVAIL_DATE}?")
    assert agent._delivery_fee_verified_this_turn is True
    assert "1,235" in r1["response"]               # turn 1 legitimate

    r2 = agent.send("Actually change it to 2099-01-01.")
    # Turn 2 reset the signal, delivery now unverified -> stale AMOUNT blocked.
    assert agent._delivery_fee_verified_this_turn is False
    assert "1,235" not in r2["response"]
    assert "35" not in r2["response"]              # stale fee cannot leak either
    assert "can't confirm" in r2["response"].lower() or \
        "cannot confirm" in r2["response"].lower()


# ======================================================================
# 8. Existing quotation-preview safety remains intact
# ======================================================================

def test_quotation_preview_delivery_safety_intact():
    s = EnquiryState()
    s.product_name = "Industrial Cable"
    s.product_sku = "CBL-210"
    s.quantity = 100
    s.verified_unit_price = 60.0
    s.verified_subtotal = 6000.0
    preview = build_quotation_preview(s)
    assert preview["status"] == "PREVIEW"
    assert preview["is_final"] is False
    assert preview["fields"]["delivery"] == TBC
    assert preview["fields"]["discount"] == TBC
    assert "before any confirmed delivery" in preview["fields"]["estimated_total"].lower()
    assert "subject to confirmation" in preview["disclaimer"].lower()


# ======================================================================
# Direct check_delivery shape (unchanged teammate tool behaviour)
# ======================================================================

def test_check_delivery_unavailable_shape_direct():
    result = check_delivery(delivery_area="Nowhere-Zone", delivery_date="2099-01-01")
    assert result["available"] is False
    assert result.get("reason") == "NO_DELIVERY_SLOT"
    assert "delivery_fee" not in result



# ======================================================================
# 9. CONVERSATION-HISTORY grounding: the STORED final assistant message
#    must equal the GUARDED customer-facing reply (not the raw model text).
#
#    Regression for the defect where the guarded text was returned to the
#    customer but the UNGUARDED response.content was appended to
#    self.messages, letting an unsupported delivery amount re-enter context
#    on later turns.
# ======================================================================

def _last_assistant_text(agent):
    """Flatten the final stored assistant message to plain text."""
    for m in reversed(agent.messages):
        if m["role"] != "assistant":
            continue
        content = m["content"]
        if isinstance(content, str):
            return content
        # tool_use turns store a list of blocks; join any text blocks.
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif getattr(b, "type", None) == "text":
                parts.append(getattr(b, "text", ""))
        return "\n".join(parts)
    return None


def test_stored_history_equals_guarded_reply_when_blocked(monkeypatch):
    # Hostile LLM emits an unverified delivered total after an unavailable
    # delivery check. The guard neutralises the customer reply; the STORED
    # history entry must match that guarded reply, NOT the raw unsafe text.
    script = [
        [("check_delivery", {"delivery_area": "Nowhere-Zone",
                             "delivery_date": "2099-01-01"})],
        "There is no delivery slot, but your final delivered total is S$1,200.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("Deliver 100 cables to Nowhere-Zone on 2099-01-01?")
    reply = result["response"]

    # (1) Customer-facing response lacks the unsafe amount.
    assert "1,200" not in reply and "1200" not in reply

    # (2) The STORED final assistant history entry also lacks the amount.
    stored = _last_assistant_text(agent)
    assert stored is not None
    assert "1,200" not in stored and "1200" not in stored

    # (3) Stored history == the guarded response the customer saw.
    assert stored == reply

    # Guard fired.
    assert any(e["type"] == "delivery_grounding_guard" for e in agent.activity_log)


def test_stored_history_matches_reply_when_verified(monkeypatch):
    # Positive control: on a verified-delivery turn the guard does NOT alter
    # the reply, and the stored history still equals the returned reply.
    script = [
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE})],
        f"Delivery to {AVAIL_AREA} on {AVAIL_DATE} is S${AVAIL_FEE:.0f}. "
        "Your delivered total is S$1,235.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send(f"Deliver to {AVAIL_AREA} on {AVAIL_DATE}?")
    reply = result["response"]

    stored = _last_assistant_text(agent)
    assert stored is not None
    assert stored == reply
    # Verified amount preserved in both the reply and stored history.
    assert "1,235" in reply
    assert "1,235" in stored
