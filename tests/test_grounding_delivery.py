"""
ISSUE 1 regression - delivery-fee / final-total / subtotal grounding
(DETERMINISTIC), plus G01-G05 Person 1 grounding-fix regressions.

Enforcement is Python-level, not prompt-only:
  * check_delivery results are normalised in the agent so an unavailable /
    no-slot / non-numeric-fee result is flagged delivery_fee_verified=False,
    delivered_total_available=False, and carries NO usable fee (never 0).
  * A per-turn signal (reset each send) prevents a previous turn's verified
    fee from leaking into a later unavailable turn.
  * A per-response-cycle trusted delivery snapshot
    (`_delivery_result_this_cycle`) is retained, and the customer-facing
    delivery section of the final reply is rendered DETERMINISTICALLY from
    that trusted snapshot (area/date/availability/fee) - never from
    Claude's draft text. This means:
      - a standalone unverified fee claim ("The delivery fee is S$35.")
        cannot survive an unavailable/unverified check (G02), not just the
        narrow "delivered total"/"free delivery" phrases;
      - the customer-facing area/date always matches the TRUSTED checked
        tuple, even if Claude's draft states a different date/area (G03);
      - the ONLY subtotal that may appear is `EnquiryState.verified_subtotal`
        - never an amount parsed out of Claude's own draft (G01).
  * The SAME finalizer (`_finalize_customer_response`) is used by the
    normal send() path AND by the approval-continuation terminal response
    (`_continue_after_human_action`, used by both legacy discount
    `apply_human_approval` and `apply_commercial_authority_approval`), so
    returned_response == stored_assistant_response holds on every path
    (G04).

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
# G02. TRUSTED DELIVERY FEE ONLY: a STANDALONE positive fee claim (not just
#      "delivered total"/"free delivery" phrasing) must never survive an
#      unavailable/unverified delivery check.
# ======================================================================

def test_hostile_standalone_fee_sgd_dollar_sign_blocked(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": "Nowhere-Zone",
                             "delivery_date": "2099-01-01"})],
        # No "delivered total"/"free delivery" phrase at all - just a bare,
        # standalone, unverified fee claim.
        "The delivery fee is S$35.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("Deliver to Nowhere-Zone on 2099-01-01?")
    reply = result["response"]
    assert "35" not in reply
    assert "can't confirm" in reply.lower() or "cannot confirm" in reply.lower()


def test_hostile_standalone_fee_sgd_word_blocked(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": "Nowhere-Zone",
                             "delivery_date": "2099-01-01"})],
        "The delivery fee is SGD 35.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("Deliver to Nowhere-Zone on 2099-01-01?")
    reply = result["response"]
    assert "35" not in reply
    assert "can't confirm" in reply.lower() or "cannot confirm" in reply.lower()


def test_verified_fee_still_shown_when_actually_available(monkeypatch):
    # Positive control: a genuinely verified fee for the CURRENT trusted
    # checked result must still be shown (G02 must not become a blanket ban
    # on all fees, only unverified ones).
    script = [
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE})],
        "Delivery is possible!",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send(f"Deliver to {AVAIL_AREA} on {AVAIL_DATE}?")
    reply = result["response"]
    assert f"S${AVAIL_FEE:,.2f}" in reply
    assert AVAIL_AREA in reply
    assert AVAIL_DATE in reply


# ======================================================================
# G01. TRUSTED SUBTOTAL ONLY: a model-authored subtotal must NEVER be
#      preserved/presented as verified. Only EnquiryState.verified_subtotal
#      may ever appear.
# ======================================================================

def test_model_authored_subtotal_not_preserved_when_no_trusted_subtotal(
    monkeypatch,
):
    # No get_customer_price call ever happened this conversation, so
    # EnquiryState.verified_subtotal is None. Claude nonetheless states an
    # invented subtotal AND an unverified delivered total after an
    # unavailable delivery check. NEITHER model-authored amount may survive.
    script = [
        [("check_delivery", {"delivery_area": "Nowhere-Zone",
                             "delivery_date": "2099-01-01"})],
        "The product subtotal is S$1,200. Your final delivered total is S$1,235.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    assert agent.enquiry.verified_subtotal is None
    result = agent.send("100 cables delivered to Nowhere-Zone on 2099-01-01?")
    reply = result["response"]
    # The model-authored subtotal must NOT be preserved (this used to be
    # treated as a "legitimate negative control" - it is not: nothing
    # verified that amount).
    assert "1,200" not in reply and "1200" not in reply
    # The model-authored delivered total must also be absent.
    assert "1,235" not in reply and "1235" not in reply
    assert "can't confirm" in reply.lower() or "cannot confirm" in reply.lower()


def test_bare_model_subtotal_not_preserved_without_trusted_value(monkeypatch):
    # A reply that ONLY states a model-authored subtotal (no delivery total
    # claim) must STILL not preserve that unverified amount once a delivery
    # check ran this cycle - the response is grounded in the trusted
    # delivery result, not in whatever Claude wrote about money.
    script = [
        [("check_delivery", {"delivery_area": "Nowhere-Zone",
                             "delivery_date": "2099-01-01"})],
        "The product subtotal is S$1,200. That delivery date isn't available.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    assert agent.enquiry.verified_subtotal is None
    result = agent.send("100 cables, deliver Nowhere-Zone 2099-01-01?")
    reply = result["response"]
    assert "1,200" not in reply and "1200" not in reply


def test_trusted_subtotal_rendered_canonically_when_verified(monkeypatch):
    # A REAL trusted subtotal (ingested via the pricing tool's trusted
    # setter, exactly as get_customer_price would populate it) MAY be shown,
    # rendered canonically by the application - never by parsing Claude's
    # text. The model's own (different, invented) amount must not leak.
    script = [
        [("check_delivery", {"delivery_area": "Nowhere-Zone",
                             "delivery_date": "2099-01-01"})],
        "Your product subtotal is S$999,999 and delivery is free!",
    ]
    agent, tools = build_agent(monkeypatch, script)
    # Simulate a trusted pricing result exactly as get_customer_price would
    # return it, ingested through the real trusted setter (not the LLM path).
    agent.enquiry.set_verified_value({
        "success": True, "subtotal": 1200.0, "unit_price": 12.0,
    })
    result = agent.send("100 cables delivered to Nowhere-Zone on 2099-01-01?")
    reply = result["response"]
    # Canonical trusted amount shown...
    assert "S$1,200.00" in reply
    # ...but the model-authored (fabricated) amount and free-delivery claim
    # never appear.
    assert "999,999" not in reply and "999999" not in reply
    assert "free" not in reply.lower()


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
    # The reply is rendered from the TRUSTED checked tuple: exact area/date
    # and the exact trusted fee are shown...
    assert AVAIL_AREA in result["response"]
    assert AVAIL_DATE in result["response"]
    assert f"S${AVAIL_FEE:,.2f}" in result["response"]
    # ...but the model's own invented "delivered total" (S$1,235, an
    # unverified figure never produced by any trusted tool) must NOT appear:
    # this patch never calculates/exposes a delivered/final total.
    assert "1,235" not in result["response"]


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
    # Turn 1's trusted fee is shown (legitimate); the model's invented
    # delivered total is not (this patch never renders a delivered total).
    assert f"S${AVAIL_FEE:,.2f}" in r1["response"]
    assert "1,235" not in r1["response"]

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
    # Positive control: on a verified-delivery turn the reply is grounded
    # (not the raw model draft), and the stored history still equals the
    # returned reply.
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
    # Trusted fee preserved in both the reply and stored history; the
    # model's invented delivered total is absent from both.
    assert f"S${AVAIL_FEE:,.2f}" in reply
    assert f"S${AVAIL_FEE:,.2f}" in stored
    assert "1,235" not in reply
    assert "1,235" not in stored


# ======================================================================
# G03. BIND RESPONSE TO THE TRUSTED CHECKED DELIVERY TUPLE: the final reply
#      must use the EXACT area/date that check_delivery actually checked,
#      never a different area/date Claude states in its draft.
# ======================================================================

def test_wrong_checked_date_in_draft_is_corrected(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": "Tengah",
                             "delivery_date": "2026-09-22"})],
        # Hostile/mistaken draft names a DIFFERENT date than what was
        # actually checked.
        "Delivery is unavailable on 23 September.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("Can you deliver tomorrow to Tengah?")
    reply = result["response"]
    # Final response must reference the TRUSTED checked date...
    assert "2026-09-22" in reply
    # ...and must NOT present the model's different date as the checked one.
    assert "23 September" not in reply
    assert "23 Sep" not in reply


def test_wrong_checked_area_in_draft_is_corrected(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": "Tengah",
                             "delivery_date": "2026-09-22"})],
        # Hostile/mistaken draft names a DIFFERENT area than was checked.
        "Delivery to Woodlands on 2026-09-22 is unavailable.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("Can you deliver to Tengah on 2026-09-22?")
    reply = result["response"]
    assert "Tengah" in reply
    assert "Woodlands" not in reply


def test_correct_checked_date_matches_and_is_shown(monkeypatch):
    # Negative control: when the model's draft happens to state the SAME
    # date/area that was actually checked, the final reply still uses that
    # (trusted) tuple - proving this is deterministic binding, not merely
    # suppression of any date.
    script = [
        [("check_delivery", {"delivery_area": "Tengah",
                             "delivery_date": "2026-09-22"})],
        "Delivery to Tengah on 2026-09-22 is unavailable.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("Can you deliver to Tengah on 2026-09-22?")
    reply = result["response"]
    assert "Tengah" in reply
    assert "2026-09-22" in reply
    assert "unavailable" in reply.lower()


# ======================================================================
# G04. ONE SHARED FINALIZER: approval continuation (both the legacy
#      discount path and the newer commercial-authority path) must apply
#      the SAME delivery grounding as normal send(), and the returned
#      response must exactly equal the stored assistant history entry.
# ======================================================================

def test_legacy_discount_continuation_grounds_unsafe_delivery_fee(
    monkeypatch,
):
    # Continuation script: after resuming, Claude performs an unavailable
    # delivery check then states a standalone unverified fee.
    continuation_script = [
        [("check_delivery", {"delivery_area": "Nowhere-Zone",
                             "delivery_date": "2099-01-01"})],
        "The delivery fee is S$35.",
    ]
    agent, tools = build_agent(monkeypatch, continuation_script)
    agent.pending_approval = {
        "type": "DISCOUNT",
        "requested_discount_percent": 10,
        "ai_authority_limit_percent": 5,
        "status": "PENDING",
    }
    result = agent.apply_human_approval(approved_discount_percent=5)
    assert result["success"] is True
    reply = result["response"]
    # Unsafe standalone fee removed, exactly like the normal send() path.
    assert "35" not in reply
    assert "can't confirm" in reply.lower() or "cannot confirm" in reply.lower()
    # returned_response == stored_assistant_response.
    stored = _last_assistant_text(agent)
    assert stored == reply


def test_commercial_authority_continuation_grounds_unsafe_delivery_fee(
    monkeypatch,
):
    continuation_script = [
        [("check_delivery", {"delivery_area": "Nowhere-Zone",
                             "delivery_date": "2099-01-01"})],
        "The delivery fee is SGD 35.",
    ]
    agent, tools = build_agent(monkeypatch, continuation_script)
    result = agent.apply_commercial_authority_approval({
        "approval_id": 999,
        "sku": "CBL-210",
        "requested_quantity": 701,
        "order_value": 15001.0,
        "requested_percent": 9.0,
        "reason": "HIGH_QUANTITY",
    })
    assert result["success"] is True
    reply = result["response"]
    assert "35" not in reply
    assert "can't confirm" in reply.lower() or "cannot confirm" in reply.lower()
    stored = _last_assistant_text(agent)
    assert stored == reply


def test_continuation_reply_equals_stored_history_when_verified(monkeypatch):
    # Positive control on the continuation path: a genuinely verified fee
    # is shown, and returned/stored text remain identical.
    continuation_script = [
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE})],
        "Great news about delivery!",
    ]
    agent, tools = build_agent(monkeypatch, continuation_script)
    agent.pending_approval = {
        "type": "DISCOUNT",
        "requested_discount_percent": 10,
        "ai_authority_limit_percent": 5,
        "status": "PENDING",
    }
    result = agent.apply_human_approval(approved_discount_percent=5)
    reply = result["response"]
    assert f"S${AVAIL_FEE:,.2f}" in reply
    stored = _last_assistant_text(agent)
    assert stored == reply



# ======================================================================
# MULTI-INTENT SAFETY (pre-commit review follow-up).
#
# The shared finalizer discards Claude's ENTIRE draft whenever a
# catalogue/delivery section is rendered (G01-G05), which previously also
# silently dropped any OTHER legitimate intent covered in that same draft
# (quotation preview, human-handoff acknowledgement). These regressions
# restore that legitimate secondary information from ITS OWN trusted
# per-cycle snapshot - never by re-including Claude's discarded draft text
# (which could carry exactly the unsafe G01-G05 content: invented
# subtotal/fee/date/area).
# ======================================================================

# Scenario A: DELIVERY + QUOTATION - the quotation preview must survive
# even though the delivery section is being rendered from trusted state.
def test_multi_intent_delivery_and_quotation_both_present(monkeypatch):
    script = [
        [
            ("check_delivery", {"delivery_area": "Nowhere-Zone",
                                "delivery_date": "2099-01-01"}),
            ("generate_quotation_preview", {}),
        ],
        # Hostile/careless draft invents a subtotal inside its own quotation
        # summary - this amount must never reach the customer either.
        "Delivery is unavailable, but here is your quote: subtotal S$999.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send(
        "Deliver 5 cables to Nowhere-Zone on 2099-01-01, and send me a quote"
    )
    reply = result["response"]
    # Trusted delivery grounding still applies (G01-G05 unaffected).
    assert "Nowhere-Zone" in reply
    assert "2099-01-01" in reply
    assert "can't confirm" in reply.lower() or "cannot confirm" in reply.lower()
    # The LEGITIMATE quotation preview (trusted, TBC-filled) is restored...
    assert "*Quotation Preview*" in reply
    assert "PREVIEW" in reply
    # ...but the model-authored invented subtotal never appears anywhere.
    assert "999" not in reply
    stored = _last_assistant_text(agent)
    assert stored == reply


# Scenario A (tool-order independence): quotation_preview called BEFORE
# check_delivery must produce the identical composed result.
def test_multi_intent_delivery_and_quotation_reverse_tool_order(monkeypatch):
    script = [
        [
            ("generate_quotation_preview", {}),
            ("check_delivery", {"delivery_area": "Nowhere-Zone",
                                "delivery_date": "2099-01-01"}),
        ],
        "Here is your quote, and delivery is unavailable.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send(
        "Send me a quote, and can you deliver to Nowhere-Zone on 2099-01-01?"
    )
    reply = result["response"]
    assert "Nowhere-Zone" in reply
    assert "*Quotation Preview*" in reply


# Scenario with a REAL trusted subtotal: the quotation section shows the
# canonical trusted amount (never a model-authored one), alongside the
# grounded delivery section.
def test_multi_intent_delivery_and_quotation_with_trusted_subtotal(
    monkeypatch,
):
    script = [
        [
            ("check_delivery", {"delivery_area": "Nowhere-Zone",
                                "delivery_date": "2099-01-01"}),
            ("generate_quotation_preview", {}),
        ],
        "Delivery is unavailable, but your subtotal is S$1 (fabricated).",
    ]
    agent, tools = build_agent(monkeypatch, script)
    # Simulate a real trusted pricing result, exactly as get_customer_price
    # would populate it, ingested through the real trusted setter.
    agent.enquiry.product_name = "Industrial Cable"
    agent.enquiry.product_sku = "CBL-210"
    agent.enquiry.quantity = 10
    agent.enquiry.set_verified_value({
        "success": True, "subtotal": 600.0, "unit_price": 60.0,
    })
    result = agent.send(
        "Deliver 10 cables to Nowhere-Zone on 2099-01-01, and quote me"
    )
    reply = result["response"]
    # Trusted canonical subtotal from the quotation preview appears...
    assert "SGD 600.00" in reply
    # ...but the model-authored fabricated amount never does.
    assert "S$1 " not in reply and "S$1(" not in reply


# Scenario B: DELIVERY + explicit human HANDOFF (SUCCESS) - the handoff
# acknowledgement must survive alongside the grounded delivery section.
def test_multi_intent_delivery_and_handoff_success(monkeypatch):
    script = [
        [
            ("check_delivery", {"delivery_area": "Nowhere-Zone",
                                "delivery_date": "2099-01-01"}),
            ("request_human_handoff", {"reason": "customer wants a person"}),
        ],
        "Delivery is unavailable. I've told our sales manager Bob and he "
        "personally guarantees a callback within the hour.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send(
        "Deliver to Nowhere-Zone on 2099-01-01, and I want to talk to a person"
    )
    reply = result["response"]
    assert "Nowhere-Zone" in reply
    # Legitimate deterministic acknowledgement is present...
    assert "flagged this for our sales team" in reply
    # ...but the model's unverifiable embellishment (a specific name/
    # guarantee never confirmed by the trusted handoff result) is absent.
    assert "Bob" not in reply
    assert "guarantee" not in reply.lower()
    stored = _last_assistant_text(agent)
    assert stored == reply


# Scenario B (tool-order independence): handoff requested BEFORE the
# delivery check must produce the identical composed result.
def test_multi_intent_delivery_and_handoff_reverse_tool_order(monkeypatch):
    script = [
        [
            ("request_human_handoff", {"reason": "customer wants a person"}),
            ("check_delivery", {"delivery_area": "Nowhere-Zone",
                                "delivery_date": "2099-01-01"}),
        ],
        "I've flagged this, and delivery is unavailable.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send(
        "I want to talk to a person, and can you deliver to Nowhere-Zone "
        "on 2099-01-01?"
    )
    reply = result["response"]
    assert "Nowhere-Zone" in reply
    assert "flagged this for our sales team" in reply


# Scenario B2: DELIVERY + human HANDOFF (FAILURE) - on a failed/ERROR
# handoff result, the acknowledgement must NOT claim a salesperson was
# notified.
def test_multi_intent_delivery_and_handoff_failure_no_false_ack(monkeypatch):
    script = [
        [
            ("check_delivery", {"delivery_area": "Nowhere-Zone",
                                "delivery_date": "2099-01-01"}),
            ("request_human_handoff", {"reason": "customer wants a person"}),
        ],
        "Delivery is unavailable. Our sales team has been notified and will "
        "reach out shortly.",
    ]
    agent, tools = build_agent(monkeypatch, script)

    # Force the trusted handoff persistence call to fail (ERROR contract),
    # exactly as app/handoff.py's record_handoff() defensive except-branch
    # would produce on a real failure.
    def _boom(**kwargs):
        raise RuntimeError("simulated persistence failure")

    monkeypatch.setattr("app.handoff.log_sales_event", _boom)

    result = agent.send(
        "Deliver to Nowhere-Zone on 2099-01-01, and I want to talk to a person"
    )
    reply = result["response"]
    assert "Nowhere-Zone" in reply
    # Must NOT POSITIVELY claim a salesperson was notified when the trusted
    # result says the handoff failed. The safe deterministic fallback
    # phrasing is a NEGATION ("I wasn't able to confirm that a salesperson
    # has been notified"), so assert on that exact safe phrase being present
    # (proving the failure path fired) rather than banning the word
    # "notified" outright, which would also match inside the negation.
    assert (
        "wasn't able to confirm that a salesperson has been notified"
        in reply
    )
    # The model's own affirmative claim ("Our sales team has been notified
    # and will reach out shortly") must not appear verbatim.
    assert "will reach out shortly" not in reply
    stored = _last_assistant_text(agent)
    assert stored == reply


# Negative control: when NEITHER catalogue nor delivery ran this cycle, a
# quotation-only or handoff-only response is Claude's own draft, unmodified
# by this patch (multi-intent restoration only activates alongside a
# catalogue/delivery section).
def test_quotation_only_response_not_altered_by_multi_intent_fix(monkeypatch):
    script = [
        [("generate_quotation_preview", {})],
        "Sure, here's a quick note before your quote.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("Send me a quote")
    assert result["response"] == "Sure, here's a quick note before your quote."


def test_handoff_only_response_not_altered_by_multi_intent_fix(monkeypatch):
    script = [
        [("request_human_handoff", {"reason": "customer wants a person"})],
        "No problem, connecting you now.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("I want to talk to a person")
    assert result["response"] == "No problem, connecting you now."


# G01-G05 regression guard: re-running a prior hostile delivery test with an
# ADDITIONAL quotation-preview call in the SAME cycle must still block the
# unsafe standalone fee claim exactly as before.
def test_hostile_standalone_fee_still_blocked_with_quotation_present(
    monkeypatch,
):
    script = [
        [
            ("check_delivery", {"delivery_area": "Nowhere-Zone",
                                "delivery_date": "2099-01-01"}),
            ("generate_quotation_preview", {}),
        ],
        "The delivery fee is S$35. Here's your quote too.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    result = agent.send("Deliver to Nowhere-Zone on 2099-01-01, and quote me")
    reply = result["response"]
    assert "35" not in reply
    assert "can't confirm" in reply.lower() or "cannot confirm" in reply.lower()
    assert "*Quotation Preview*" in reply



# ======================================================================
# PERSON 3 CONTINUATION COMPATIBILITY: the multi-intent restoration must
# work identically on the approval-continuation path (apply_human_approval /
# apply_commercial_authority_approval), which shares the SAME finalizer,
# without touching any Person 3 decision/DB logic.
# ======================================================================

def test_continuation_multi_intent_delivery_and_quotation(monkeypatch):
    continuation_script = [
        [
            ("check_delivery", {"delivery_area": "Nowhere-Zone",
                                "delivery_date": "2099-01-01"}),
            ("generate_quotation_preview", {}),
        ],
        "Delivery is unavailable, but here's your quote.",
    ]
    agent, tools = build_agent(monkeypatch, continuation_script)
    agent.pending_approval = {
        "type": "DISCOUNT",
        "requested_discount_percent": 10,
        "ai_authority_limit_percent": 5,
        "status": "PENDING",
    }
    result = agent.apply_human_approval(approved_discount_percent=5)
    assert result["success"] is True
    reply = result["response"]
    assert "Nowhere-Zone" in reply
    assert "*Quotation Preview*" in reply
    stored = _last_assistant_text(agent)
    assert stored == reply


def test_continuation_multi_intent_delivery_and_handoff(monkeypatch):
    continuation_script = [
        [
            ("check_delivery", {"delivery_area": "Nowhere-Zone",
                                "delivery_date": "2099-01-01"}),
            ("request_human_handoff", {"reason": "customer wants a person"}),
        ],
        "Delivery is unavailable, and I've told our team.",
    ]
    agent, tools = build_agent(monkeypatch, continuation_script)
    result = agent.apply_commercial_authority_approval({
        "approval_id": 999,
        "sku": "CBL-210",
        "requested_quantity": 701,
        "order_value": 15001.0,
        "requested_percent": 9.0,
        "reason": "HIGH_QUANTITY",
    })
    assert result["success"] is True
    reply = result["response"]
    assert "Nowhere-Zone" in reply
    assert "flagged this for our sales team" in reply
    stored = _last_assistant_text(agent)
    assert stored == reply
