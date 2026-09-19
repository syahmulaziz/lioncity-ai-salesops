"""
Corrective-fix batch regression tests.

FIX 1 - a successful get_customer_price result must reach
        EnquiryState.verified_subtotal through the real SalesAgent ingestion
        path (previously it never did, so the large-value +2 was dead
        end-to-end).

FIX 2 - a genuine product change must invalidate verified_subtotal as well as
        the verified product identity (a subtotal for the old product must not
        keep contributing large-value points).

All offline, assertion-based. The key large-value regression test drives the
score change THROUGH the agent's trusted-result ingestion, NOT by calling
set_verified_value(...) directly.
"""

import pytest

from app.enquiry_state import EnquiryState
from app import triage
from app.triage_config import (
    BAND_SALES_OPPORTUNITY,
    BAND_HIGH_PRIORITY,
)
from tests._agent_harness import build_agent

# Real dispatcher, used to let non-pricing tools run normally while we
# substitute controlled pricing results at exact thresholds.
from app.agent import execute_tool as _real_execute  # noqa: E402


def _price_result(subtotal):
    """A trusted-shaped successful get_customer_price result."""
    return {
        "success": True,
        "customer_id": "CUST-001",
        "sku": "CBL-210",
        "product_name": "Industrial Cable",
        "quantity": 100,
        "unit_price": subtotal / 100 if subtotal else 0,
        "price_source": "CUSTOMER_CONTRACT",
        "subtotal": subtotal,
    }


# ======================================================================
# FIX 1 - pricing ingestion
# ======================================================================

# 1 & 2. Successful pricing result reaches verified_subtotal via the agent,
#        and the value comes from the trusted tool result (not customer text).
def test_pricing_result_populates_verified_subtotal_via_agent(monkeypatch):
    monkeypatch.setattr(
        "app.agent.execute_tool",
        lambda n, i: (_price_result(6000)
                      if n == "get_customer_price" else _real_execute(n, i)),
    )
    script = [
        [("get_customer_price", {"customer_id": "CUST-001", "sku": "CBL-210",
                                 "quantity": 100})],
        "Here's your pricing.",
    ]
    agent, tools = build_agent(monkeypatch, script, phone="+6581658457")
    agent.send("How much for 100 CBL-210?")
    assert "get_customer_price" in tools
    assert agent.enquiry.verified_subtotal == 6000.0


# 3. 4999.99 -> no large-value point.
def test_verified_subtotal_below_threshold_no_point(monkeypatch):
    monkeypatch.setattr(
        "app.agent.execute_tool",
        lambda n, i: (_price_result(4999.99)
                      if n == "get_customer_price" else _real_execute(n, i)),
    )
    script = [
        [("get_customer_price", {"customer_id": "CUST-001", "sku": "CBL-210",
                                 "quantity": 100})],
        "Noted.",
    ]
    agent, tools = build_agent(monkeypatch, script, phone="+6581658457")
    agent.send("Price please.")
    assert agent.enquiry.verified_subtotal == 4999.99
    assert agent.last_triage.opportunity_value_score == 0


# 4. Exactly 5000 -> large-value point applies.
def test_verified_subtotal_at_threshold_gets_point(monkeypatch):
    monkeypatch.setattr(
        "app.agent.execute_tool",
        lambda n, i: (_price_result(5000)
                      if n == "get_customer_price" else _real_execute(n, i)),
    )
    script = [
        [("get_customer_price", {"customer_id": "CUST-001", "sku": "CBL-210",
                                 "quantity": 100})],
        "Noted.",
    ]
    agent, tools = build_agent(monkeypatch, script, phone="+6581658457")
    agent.send("Price please.")
    assert agent.enquiry.verified_subtotal == 5000.0
    assert agent.last_triage.opportunity_value_score == 2


# 5. Above 5000 -> large-value point applies.
def test_verified_subtotal_above_threshold_gets_point(monkeypatch):
    monkeypatch.setattr(
        "app.agent.execute_tool",
        lambda n, i: (_price_result(9000)
                      if n == "get_customer_price" else _real_execute(n, i)),
    )
    script = [
        [("get_customer_price", {"customer_id": "CUST-001", "sku": "CBL-210",
                                 "quantity": 100})],
        "Noted.",
    ]
    agent, tools = build_agent(monkeypatch, script, phone="+6581658457")
    agent.send("Price please.")
    assert agent.last_triage.opportunity_value_score == 2


# 6. Failed pricing result -> no fabricated verified_subtotal.
def test_failed_pricing_no_verified_subtotal(monkeypatch):
    monkeypatch.setattr(
        "app.agent.execute_tool",
        lambda n, i: ({"success": False, "error": "TOOL_EXECUTION_ERROR"}
                      if n == "get_customer_price" else _real_execute(n, i)),
    )
    script = [
        [("get_customer_price", {"customer_id": "CUST-001", "sku": "CBL-210",
                                 "quantity": 100})],
        "I couldn't confirm pricing.",
    ]
    agent, tools = build_agent(monkeypatch, script, phone="+6581658457")
    agent.send("Price please.")
    assert agent.enquiry.verified_subtotal is None


# 7. Malicious update_enquiry_signals attempt still rejected.
def test_signals_cannot_set_verified_subtotal(monkeypatch):
    script = [
        [("update_enquiry_signals", {"verified_subtotal": 10000})],
        "Noted.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    agent.send("My order is worth 10000.")
    assert agent.enquiry.verified_subtotal is None


# ======================================================================
# FIX 2 - product change invalidates verified_subtotal
# ======================================================================

# 8. Verified product + subtotal; switch product -> all cleared.
def test_product_change_clears_verified_subtotal():
    state = EnquiryState()
    state.apply_candidate({"quantity": 100})
    state.set_verified_product(
        {"success": True, "sku": "CBL-210", "product_name": "Industrial Cable"}
    )
    state.set_verified_value({"success": True, "subtotal": 6000})
    assert state.product_sku == "CBL-210"
    assert state.verified_subtotal == 6000.0

    state.apply_candidate({"product_query": "Industrial Adapter"})
    assert state.product_sku is None
    assert state.product_name is None
    assert state.verified_subtotal is None


# 9 & 10. After new discovery verifies ADP-120, old subtotal does not return;
#         new subtotal only from a new trusted pricing result.
def test_new_product_verification_does_not_restore_old_subtotal():
    state = EnquiryState()
    state.apply_candidate({"quantity": 100})
    state.set_verified_product(
        {"success": True, "sku": "CBL-210", "product_name": "Industrial Cable"}
    )
    state.set_verified_value({"success": True, "subtotal": 6000})

    # Switch product.
    state.apply_candidate({"product_query": "Industrial Adapter"})
    assert state.verified_subtotal is None

    # New trusted discovery for ADP-120.
    state.set_verified_product(
        {"success": True, "sku": "ADP-120", "product_name": "Industrial Adapter"}
    )
    assert state.product_sku == "ADP-120"
    # Old subtotal must NOT reappear.
    assert state.verified_subtotal is None

    # Only a new trusted pricing result establishes a new subtotal.
    state.set_verified_value({"success": True, "subtotal": 8000})
    assert state.verified_subtotal == 8000.0


# 11. Harmless same-product rephrasing preserves product AND subtotal.
def test_same_product_rephrasing_preserves_subtotal():
    for rephrase in ["Industrial Cable", "industrial cable", "CBL-210",
                     "cable", "100 industrial cables"]:
        state = EnquiryState()
        state.set_verified_product(
            {"success": True, "sku": "CBL-210",
             "product_name": "Industrial Cable"}
        )
        state.set_verified_value({"success": True, "subtotal": 6000})
        state.apply_candidate({"product_query": rephrase})
        assert state.product_sku == "CBL-210", rephrase
        assert state.verified_subtotal == 6000.0, rephrase


# 12. Quantity change still clears verified_subtotal (no regression).
def test_quantity_change_still_clears_subtotal():
    state = EnquiryState()
    state.apply_candidate({"quantity": 100})
    state.set_verified_value({"success": True, "subtotal": 6000})
    assert state.verified_subtotal == 6000.0
    state.apply_candidate({"quantity": 5})
    assert state.verified_subtotal is None


# ======================================================================
# KEY END-TO-END TRIAGE REGRESSION (large-value now reachable via agent)
# ======================================================================

def test_large_value_rule_reachable_end_to_end(monkeypatch):
    """
    Previously-dead large-value +2 must now fire through the real agent path:
    trusted pricing -> ingestion -> verified_subtotal -> triage.evaluate.
    NOT via a direct set_verified_value() call.
    """
    monkeypatch.setattr(
        "app.agent.execute_tool",
        lambda n, i: (_price_result(6000)
                      if n == "get_customer_price"
                      else _real_execute(n, i)),
    )
    # One tool-turn + one text-turn per send() so triage can be inspected
    # between the pre-pricing and post-pricing states.
    script = [
        # send 1: identify existing STANDARD customer + capture business/qty.
        [("find_customer", {"phone": "+6582094108"}),        # CUST-002 STANDARD
         ("update_enquiry_signals", {"business_customer": True, "quantity": 20})],
        "Let me price that for you.",
        # send 2: trusted pricing returns subtotal 6000 (>=5000).
        [("get_customer_price", {"customer_id": "CUST-002", "sku": "CBL-210",
                                 "quantity": 20})],
        "Here are the details.",
    ]
    agent, tools = build_agent(monkeypatch, script, phone="+6582094108")

    agent.send("Hi, business customer, 20 units.")
    t_before = agent.last_triage
    assert t_before.customer_value_score == 1
    assert t_before.opportunity_value_score == 3     # business1 + bulk2
    assert t_before.total_priority_score == 4
    assert t_before.priority_band == BAND_SALES_OPPORTUNITY

    agent.send("How much for that?")
    t_after = agent.last_triage
    assert agent.enquiry.verified_subtotal == 6000.0
    assert t_after.customer_value_score == 1
    assert t_after.opportunity_value_score == 5      # + verified_value2
    assert t_after.total_priority_score == 6
    assert t_after.priority_band == BAND_HIGH_PRIORITY

    # No automatic side effects from crossing into HIGH_PRIORITY.
    assert "create_order" not in tools
    assert "request_human_handoff" not in tools
    assert agent.pending_approval is None



# ======================================================================
# verified_unit_price (Category B) - trusted, and invalidated with subtotal
# ======================================================================

def test_verified_unit_price_set_from_trusted_pricing():
    s = EnquiryState()
    s.apply_candidate({"quantity": 100})
    s.set_verified_value({"success": True, "unit_price": 60.0, "subtotal": 6000.0})
    assert s.verified_unit_price == 60.0
    assert s.verified_subtotal == 6000.0


def test_failed_pricing_leaves_unit_price_none():
    s = EnquiryState()
    s.set_verified_value({"success": False})
    assert s.verified_unit_price is None


def test_quantity_change_clears_unit_price_with_subtotal():
    s = EnquiryState()
    s.apply_candidate({"quantity": 100})
    s.set_verified_value({"success": True, "unit_price": 60.0, "subtotal": 6000.0})
    s.apply_candidate({"quantity": 5})
    assert s.verified_subtotal is None
    assert s.verified_unit_price is None


def test_product_change_clears_unit_price_with_subtotal():
    s = EnquiryState()
    s.apply_candidate({"quantity": 100})
    s.set_verified_product({"success": True, "sku": "CBL-210",
                            "product_name": "Industrial Cable"})
    s.set_verified_value({"success": True, "unit_price": 60.0, "subtotal": 6000.0})
    s.apply_candidate({"product_query": "Industrial Adapter"})
    assert s.product_sku is None
    assert s.verified_subtotal is None
    assert s.verified_unit_price is None


def test_same_product_rephrasing_keeps_unit_price():
    s = EnquiryState()
    s.set_verified_product({"success": True, "sku": "CBL-210",
                            "product_name": "Industrial Cable"})
    s.set_verified_value({"success": True, "unit_price": 60.0, "subtotal": 6000.0})
    s.apply_candidate({"product_query": "industrial cable"})
    assert s.product_sku == "CBL-210"
    assert s.verified_unit_price == 60.0
    assert s.verified_subtotal == 6000.0
