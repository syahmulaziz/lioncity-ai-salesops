"""
Batch 3 tests: SalesAgent <-> EnquiryState integration + guest handling
(Task 17 guest tests plus narrowly-scoped Task 7 integration tests).

These test APPLICATION BOUNDARIES, not the LLM's intelligence. We never make
live Anthropic/WhatsApp calls. Claude is replaced with a fake client so
SalesAgent can be constructed offline, and we simulate tool requests/results
directly by calling the agent's tool handler.

All tests are deterministic, offline, assertion-based.
"""

import sys
import types

import pytest

# ---------------------------------------------------------------------------
# Offline shim: app.claude_client imports `anthropic` at module load. The
# package is not installed in this offline sandbox, and these tests never make
# a live LLM call, so we register a minimal stub module BEFORE importing
# app.agent. This is a TEST-ONLY shim; no application code is modified.
# ---------------------------------------------------------------------------
if "anthropic" not in sys.modules:
    _anthropic_stub = types.ModuleType("anthropic")
    _anthropic_stub.Anthropic = object  # never instantiated in these tests
    sys.modules["anthropic"] = _anthropic_stub

if "dotenv" not in sys.modules:
    _dotenv_stub = types.ModuleType("dotenv")
    _dotenv_stub.load_dotenv = lambda *args, **kwargs: False
    sys.modules["dotenv"] = _dotenv_stub

if "requests" not in sys.modules:
    # Staging's LLM gateway client imports `requests` at module load; stub it
    # for offline collection. These tests never make a real HTTP call.
    _requests_stub = types.ModuleType("requests")
    _requests_stub.get = _requests_stub.post = _requests_stub.request = (
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("Live HTTP call attempted in an offline test")
        )
    )

    class _ReqExc(Exception):
        pass

    _requests_stub.RequestException = _ReqExc
    _requests_stub.exceptions = types.SimpleNamespace(RequestException=_ReqExc)
    sys.modules["requests"] = _requests_stub

from app import agent as agent_module  # noqa: E402
from app.agent import SalesAgent  # noqa: E402
from app.enquiry_state import EnquiryState  # noqa: E402
from app.triage_config import (  # noqa: E402
    BAND_ROUTINE,
    BAND_HIGH_PRIORITY,
)


class _FakeClaudeClient:
    """Stand-in for the Anthropic client. Never called in these tests."""
    class messages:  # noqa: N801 (mimic anthropic client shape)
        @staticmethod
        def create(*args, **kwargs):
            raise AssertionError("Live Claude call attempted in an offline test")


@pytest.fixture
def make_agent(monkeypatch):
    """Build a SalesAgent without any network/API key by faking the client."""
    def _factory(phone="+6580000000"):
        monkeypatch.setattr(
            agent_module, "get_claude_client", lambda: _FakeClaudeClient()
        )
        # DB SAFETY: an explicit human handoff calls log_sales_event, which
        # would write to the runtime SQLite DB. No-op the logger by default so
        # these offline tests never mutate data/lioncity.db. (HIGH_PRIORITY by
        # itself no longer triggers any handoff.)
        monkeypatch.setattr(
            "app.handoff.log_sales_event", lambda **kw: {"success": True}
        )
        return SalesAgent(phone=phone)
    return _factory


# ----------------------------------------------------------------------
# 1. SalesAgent initializes with an empty EnquiryState
# ----------------------------------------------------------------------

def test_agent_initializes_empty_enquiry_state(make_agent):
    agent = make_agent()
    assert isinstance(agent.enquiry, EnquiryState)
    assert agent.enquiry.quantity is None
    assert agent.enquiry.business_customer is None
    assert agent.enquiry.existing_customer is False
    assert agent.last_triage is None


# ----------------------------------------------------------------------
# 2. Two SalesAgent instances have independent EnquiryState objects
# ----------------------------------------------------------------------

def test_two_agents_have_independent_state(make_agent):
    agent_a = make_agent(phone="+6511111111")
    agent_b = make_agent(phone="+6522222222")

    agent_a._handle_tool("update_enquiry_signals", {"quantity": 100})

    assert agent_a.enquiry.quantity == 100
    assert agent_b.enquiry.quantity is None
    assert agent_a.enquiry is not agent_b.enquiry


# ----------------------------------------------------------------------
# 3. Existing self.messages behaviour still exists
# ----------------------------------------------------------------------

def test_messages_list_still_present(make_agent):
    agent = make_agent()
    assert agent.messages == []
    # It is still an ordinary list we can append to (history role preserved).
    agent.messages.append({"role": "user", "content": "hi"})
    assert len(agent.messages) == 1


# ----------------------------------------------------------------------
# 4. Valid update_enquiry_signals call updates Category A state
# ----------------------------------------------------------------------

def test_valid_signal_update(make_agent):
    agent = make_agent()
    result = agent._handle_tool("update_enquiry_signals", {
        "product_query": "industrial cables",
        "quantity": 100,
        "urgent": True,
    })
    assert result["success"] is True
    assert agent.enquiry.product_query == "industrial cables"
    assert agent.enquiry.quantity == 100
    assert agent.enquiry.urgent is True


# ----------------------------------------------------------------------
# 5-7. Untrusted signal path rejects Category B / C fields (via agent)
# ----------------------------------------------------------------------

def test_signal_path_rejects_customer_tier(make_agent):
    agent = make_agent()
    result = agent._handle_tool("update_enquiry_signals", {"customer_tier": "GOLD"})
    assert "customer_tier" in result["rejected"]
    assert agent.enquiry.customer_tier is None


def test_signal_path_rejects_verified_subtotal(make_agent):
    agent = make_agent()
    result = agent._handle_tool(
        "update_enquiry_signals", {"verified_subtotal": 10000}
    )
    assert "verified_subtotal" in result["rejected"]
    assert agent.enquiry.verified_subtotal is None


def test_signal_path_rejects_priority_band(make_agent):
    agent = make_agent()
    result = agent._handle_tool(
        "update_enquiry_signals", {"priority_band": "HIGH_PRIORITY"}
    )
    assert "priority_band" in result["rejected"]
    assert getattr(agent.enquiry, "priority_band", None) is None


# ----------------------------------------------------------------------
# 8. Successful trusted find_customer populates Category B
# ----------------------------------------------------------------------

def test_successful_find_customer_populates_category_b(make_agent):
    agent = make_agent()
    # Simulate the trusted tool returning a real customer.
    agent._ingest_tool_side_effects("find_customer", {
        "success": True,
        "customer_id": "CUST-001",
        "account_tier": "GOLD",
        "company_name": "Apex Engineering Pte Ltd",
    })
    assert agent.enquiry.existing_customer is True
    assert agent.enquiry.customer_id == "CUST-001"
    assert agent.enquiry.customer_tier == "GOLD"


# ----------------------------------------------------------------------
# 9 & 10 & 17. CUSTOMER_NOT_FOUND -> guest state, enquiry not terminated
# ----------------------------------------------------------------------

def test_customer_not_found_becomes_guest(make_agent):
    agent = make_agent()
    agent._ingest_tool_side_effects("find_customer", {
        "success": False,
        "error": "CUSTOMER_NOT_FOUND",
        "phone": "+6580000000",
    })
    assert agent.enquiry.existing_customer is False
    assert agent.enquiry.customer_id is None      # no invented id
    assert agent.enquiry.customer_tier is None
    # Enquiry state still usable (not terminated): we can keep adding signals.
    agent._handle_tool("update_enquiry_signals", {"quantity": 10})
    assert agent.enquiry.quantity == 10


# ----------------------------------------------------------------------
# 11-15 & 16 & 17. Guest accumulates Category A signals -> HIGH_PRIORITY
# ----------------------------------------------------------------------

def test_guest_can_reach_high_priority(make_agent):
    agent = make_agent()

    # Unknown phone -> guest.
    agent._ingest_tool_side_effects("find_customer", {
        "success": False, "error": "CUSTOMER_NOT_FOUND",
    })

    # "We're ABC Construction."
    agent._handle_tool("update_enquiry_signals", {
        "company_name": "ABC Construction",
        "business_customer": True,
    })
    # "We need 100 units."
    agent._handle_tool("update_enquiry_signals", {"quantity": 100})
    # "We need a quotation urgently."
    agent._handle_tool("update_enquiry_signals", {
        "quotation_requested": True,
        "urgent": True,
    })

    assert agent.enquiry.company_name == "ABC Construction"
    assert agent.enquiry.business_customer is True
    assert agent.enquiry.quantity == 100
    assert agent.enquiry.quotation_requested is True
    assert agent.enquiry.urgent is True
    # No invented customer id.
    assert agent.enquiry.customer_id is None

    t = agent.last_triage
    assert t.customer_value_score == 0            # guest: no account points
    assert t.opportunity_value_score == 6         # business1+bulk2+quote2+urgent1
    assert t.total_priority_score == 6
    assert t.priority_band == BAND_HIGH_PRIORITY


# ----------------------------------------------------------------------
# 18. Existing GOLD customer-value = existing(1) + gold(2) = 3
# ----------------------------------------------------------------------

def test_existing_gold_customer_value(make_agent):
    agent = make_agent()
    agent._ingest_tool_side_effects("find_customer", {
        "success": True, "customer_id": "CUST-001", "account_tier": "GOLD",
    })
    assert agent.last_triage.customer_value_score == 3


# ----------------------------------------------------------------------
# 19. STANDARD existing customer-value = existing(1) + standard(0) = 1
# ----------------------------------------------------------------------

def test_existing_standard_customer_value(make_agent):
    agent = make_agent()
    agent._ingest_tool_side_effects("find_customer", {
        "success": True, "customer_id": "CUST-002", "account_tier": "STANDARD",
    })
    assert agent.last_triage.customer_value_score == 1


# ----------------------------------------------------------------------
# 20. Correction quantity 100 -> 5 removes bulk points on re-evaluation
# ----------------------------------------------------------------------

def test_quantity_correction_removes_bulk_points(make_agent):
    agent = make_agent()
    agent._handle_tool("update_enquiry_signals", {"quantity": 100})
    assert agent.last_triage.opportunity_value_score == 2  # bulk

    agent._handle_tool("update_enquiry_signals", {"quantity": 5})
    assert agent.enquiry.quantity == 5
    assert agent.last_triage.opportunity_value_score == 0  # bulk gone


# ----------------------------------------------------------------------
# 21. Correction quotation True -> False removes quotation points
# ----------------------------------------------------------------------

def test_quotation_cancellation_removes_points(make_agent):
    agent = make_agent()
    agent._handle_tool("update_enquiry_signals", {"quotation_requested": True})
    assert agent.last_triage.opportunity_value_score == 2  # quotation

    agent._handle_tool("update_enquiry_signals", {"quotation_requested": False})
    assert agent.enquiry.quotation_requested is False
    assert agent.last_triage.opportunity_value_score == 0  # quotation gone


# ----------------------------------------------------------------------
# 22 & 23. HIGH_PRIORITY: no ORDER / no DISCOUNT-APPROVAL side effect.
# (REVISED: HIGH_PRIORITY now DOES auto-refer to sales - a human handoff -
#  but must still never auto-create an order or approve a discount. The
#  handoff logger is patched so no row is written to the committed DB.)
# ----------------------------------------------------------------------

def test_high_priority_no_order_or_discount_side_effect(make_agent, monkeypatch):
    monkeypatch.setattr(
        "app.handoff.log_sales_event",
        lambda **kw: {"success": True},
    )
    agent = make_agent()
    agent._handle_tool("update_enquiry_signals", {
        "business_customer": True, "quantity": 100,
        "quotation_requested": True, "urgent": True,
    })
    assert agent.last_triage.priority_band == BAND_HIGH_PRIORITY

    # No discount approval was created.
    assert agent.pending_approval is None
    # No order-confirmed / discount-approval events were logged.
    logged_types = {entry["type"] for entry in agent.activity_log}
    assert "order_created" not in logged_types
    assert "human_approval_required" not in logged_types
    # Triage classification still logged.
    assert "triage_evaluated" in logged_types
    # DECOUPLED behaviour: HIGH_PRIORITY does NOT create a handoff by itself.
    assert "human_handoff_requested" not in logged_types


# ----------------------------------------------------------------------
# 24. Existing discount HITL path/config remains unchanged
# ----------------------------------------------------------------------

def test_discount_hitl_untouched():
    # AI discount authority still owned by tools/discount.py, unchanged.
    from app.tools.discount import AI_DISCOUNT_LIMIT, check_discount_authority
    assert AI_DISCOUNT_LIMIT == 5.0

    within = check_discount_authority(5)
    assert within["requires_human_approval"] is False

    over = check_discount_authority(10)
    assert over["requires_human_approval"] is True


# ----------------------------------------------------------------------
# FAQ intent exception: a valuable account asking an FAQ is NOT escalated
# by the mere presence of customer-value points (no automatic side effects).
# ----------------------------------------------------------------------

def test_faq_intent_customer_value_has_no_side_effects(make_agent):
    agent = make_agent()
    # Gold customer (customer-value 3 internally)...
    agent._ingest_tool_side_effects("find_customer", {
        "success": True, "customer_id": "CUST-001", "account_tier": "GOLD",
    })
    # ...asking an FAQ-style question (no opportunity signals).
    agent._handle_tool("update_enquiry_signals", {"current_intent": "FAQ_GENERAL"})

    # Internal customer-value may be 3, but there is no handoff/order/approval.
    assert agent.last_triage.customer_value_score == 3
    assert agent.last_triage.opportunity_value_score == 0
    assert agent.pending_approval is None
    logged_types = {entry["type"] for entry in agent.activity_log}
    assert "human_approval_required" not in logged_types
    assert "order_created" not in logged_types
