"""
Regression: COMMERCIAL_AUTHORITY rejection.

LIVE GAP (staging 2e964f9): the Human Decisions panel showed a
"Commercial Authority Request" with only "✓ Approve Commercial Transaction"
and NO rejection action. A DISCOUNT rejection path already existed, but a
COMMERCIAL_AUTHORITY escalation (EXCESSIVE_DISCOUNT / HIGH_QUANTITY /
HIGH_VALUE, or combinations) had no rejection path.

These tests exercise the commercial-authority rejection at the agent layer
and the finalizer/grounding layer. They must:
  - transition an approval PENDING -> REJECTED (DB layer, temp DB);
  - resume the SAME agent with a TRUSTED, reason-aware rejection message;
  - NEVER create an order and NEVER call create_order;
  - clear pending_commercial_order so no later approval can resurrect the
    order (order-safety / no-resurrection);
  - not describe a HIGH_QUANTITY / HIGH_VALUE rejection as merely a discount
    rejection;
  - be idempotent (a processed rejection is not re-processed).

DB SAFETY: DB-layer assertions use a TEMPORARY sqlite file (DB_PATH
monkeypatched). Agent-layer tests build the agent via object.__new__ and stub
all tool/DB seams, so the committed data/lioncity.db is never written and no
external LLM / WhatsApp API is called.
"""

import pytest

# Import the offline harness FIRST so anthropic/dotenv/requests stubs are
# registered before app.agent (via app.claude_client) imports them.
from tests._agent_harness import build_agent  # noqa: F401
import app.agent as agent_module
from app.enquiry_state import EnquiryState
import app.database as db


PHONE = "+6581658457"


# ---------------------------------------------------------------------------
# Agent-layer helper: a commercial escalation that already blocked create_order
# (so pending_commercial_order is set), mirroring test_transaction_lifecycle.
# ---------------------------------------------------------------------------
def _bare_commercial_agent(reason="EXCESSIVE_DISCOUNT", requested_percent=10.0):
    agent = object.__new__(agent_module.SalesAgent)
    agent.messages = []
    agent.pending_approval = None
    agent.pending_commercial_order = {
        "phone": PHONE, "customer_id": "CUST-001",
        "items": [{"sku": "CBL-210", "quantity": 10, "unit_price": 12.0}],
        "product_subtotal": 120.0, "discount_percent": 10.0,
        "delivery_fee": 0.0, "final_total": 108.0,
        "delivery_area": "Jurong", "delivery_date": "2026-09-15",
    }
    agent.log_activity = lambda *a, **k: None
    # Use the REAL grounding reset/renderer so we can assert the customer text.
    agent.enquiry = EnquiryState()
    agent.enquiry.product_sku = "CBL-210"
    agent.enquiry.product_name = "Industrial Cable"
    agent.enquiry.quantity = 10
    agent.enquiry.set_verified_inventory({
        "success": True, "sku": "CBL-210", "requested_quantity": 10,
        "available_quantity": 486, "can_fulfil": True,
    })
    # Initialise the per-cycle grounding fields the real reset would set.
    agent._reset_response_grounding()
    return agent


def _approval(reason="EXCESSIVE_DISCOUNT", requested_percent=10.0,
              approval_id=999):
    return {
        "approval_id": approval_id, "phone": PHONE,
        "approval_type": "COMMERCIAL_AUTHORITY", "status": "REJECTED",
        "sku": "CBL-210", "requested_quantity": 10, "order_value": 108.0,
        "requested_percent": requested_percent, "approved_percent": None,
        "reason": reason,
    }


def _run_rejection(agent, approval):
    """Drive the commercial rejection but stop before the LLM continuation.

    _continue_after_human_action() would call the (stubbed) client; here we
    only need to verify the trusted state/message the method establishes, so
    we monkeypatch the continuation to a deterministic finalize-only call.
    """
    captured = {}

    def _fake_continue():
        # Emulate the finalizer running on a benign model draft, so the
        # deterministic rejection grounding is what reaches the customer.
        text = agent._finalize_customer_response([
            type("B", (), {"type": "text", "text":
                "Good news, your discount was approved and your order is placed!"})()
        ])
        captured["response"] = text
        return {"success": True, "response": text}

    agent._continue_after_human_action = _fake_continue
    result = agent.apply_commercial_authority_rejection(approval)
    result.setdefault("response", captured.get("response"))
    return result


# ===========================================================================
# A. EXCESSIVE_DISCOUNT rejection
# ===========================================================================
def test_commercial_rejection_excessive_discount(monkeypatch):
    agent = _bare_commercial_agent()
    called = {"create_order": 0}
    agent._handle_tool = lambda t, i: called.__setitem__(
        "create_order", called["create_order"] + (t == "create_order")
    ) or {"success": True}

    result = _run_rejection(agent, _approval(reason="EXCESSIVE_DISCOUNT"))
    reply = result["response"]

    assert result["success"] is True
    # Order safety: no order, no create_order call, pending cleared.
    assert called["create_order"] == 0
    assert agent.pending_commercial_order is None
    # Customer message must not claim approval / order created.
    low = reply.lower()
    assert "was approved" not in low
    assert "order is placed" not in low and "order has been created" not in low
    assert "order reference" not in low
    # Reason-aware: discount context is acceptable here (customer may proceed
    # at standard pricing), so the message should say the requested discount /
    # commercial terms were not approved.
    assert "not approved" in low or "could not be approved" in low


# ===========================================================================
# B. HIGH_QUANTITY rejection - must NOT be described only as a discount reject
# ===========================================================================
def test_commercial_rejection_high_quantity(monkeypatch):
    agent = _bare_commercial_agent(reason="HIGH_QUANTITY")
    called = {"create_order": 0}
    agent._handle_tool = lambda t, i: called.__setitem__(
        "create_order", called["create_order"] + (t == "create_order")
    ) or {"success": True}

    result = _run_rejection(agent, _approval(reason="HIGH_QUANTITY"))
    reply = result["response"].lower()

    assert result["success"] is True
    assert called["create_order"] == 0
    assert agent.pending_commercial_order is None
    # Must reflect the proposed transaction/quantity was not approved, and must
    # NOT falsely say only a discount was rejected nor imply approval/order.
    assert "was approved" not in reply
    assert "order has been created" not in reply and "order reference" not in reply
    assert "not approved" in reply or "could not be approved" in reply
    # Must not reduce a quantity rejection to a pure discount rejection.
    assert "your requested 10% discount could not be approved" not in reply


# ===========================================================================
# C. HIGH_VALUE rejection
# ===========================================================================
def test_commercial_rejection_high_value(monkeypatch):
    agent = _bare_commercial_agent(reason="HIGH_VALUE")
    called = {"create_order": 0}
    agent._handle_tool = lambda t, i: called.__setitem__(
        "create_order", called["create_order"] + (t == "create_order")
    ) or {"success": True}

    result = _run_rejection(agent, _approval(reason="HIGH_VALUE"))
    reply = result["response"].lower()

    assert result["success"] is True
    assert called["create_order"] == 0
    assert agent.pending_commercial_order is None
    assert "was approved" not in reply
    assert "order has been created" not in reply and "order reference" not in reply
    assert "not approved" in reply or "could not be approved" in reply
    assert "your requested 10% discount could not be approved" not in reply


# ===========================================================================
# D. Multiple reasons
# ===========================================================================
def test_commercial_rejection_multiple_reasons(monkeypatch):
    agent = _bare_commercial_agent(reason="HIGH_VALUE,EXCESSIVE_DISCOUNT")
    called = {"create_order": 0}
    agent._handle_tool = lambda t, i: called.__setitem__(
        "create_order", called["create_order"] + (t == "create_order")
    ) or {"success": True}

    result = _run_rejection(
        agent, _approval(reason="HIGH_VALUE,EXCESSIVE_DISCOUNT"))
    reply = result["response"].lower()

    assert result["success"] is True
    assert called["create_order"] == 0
    assert agent.pending_commercial_order is None
    assert "was approved" not in reply
    assert "order has been created" not in reply and "order reference" not in reply
    assert "not approved" in reply or "could not be approved" in reply


# ===========================================================================
# H. Order safety: rejection then a stray commercial APPROVAL must not
#    resurrect an order (pending_commercial_order was cleared).
# ===========================================================================
def test_rejection_clears_pending_so_later_approval_cannot_resurrect(monkeypatch):
    agent = _bare_commercial_agent()
    created = {"n": 0}

    def _handle(t, i):
        if t == "create_order":
            created["n"] += 1
            return {"success": True, "order_id": "SO-SHOULD-NOT-HAPPEN"}
        return {"success": True}

    agent._handle_tool = _handle
    agent._continue_after_human_action = lambda: {"success": True, "response": "ok"}

    # Reject first.
    agent.apply_commercial_authority_rejection(_approval())
    assert agent.pending_commercial_order is None
    assert created["n"] == 0

    # A stray later approval on the same (now-rejected) transaction: because
    # pending_commercial_order is cleared, the pre-confirmation branch runs
    # and does NOT create an order.
    monkeypatch.setattr(agent_module, "get_approval_by_id",
                        lambda approval_id: {"approval_id": approval_id,
                                             "status": "REJECTED",
                                             "order_id": None})
    agent._continue_after_human_action = lambda: {"success": True, "response": "ok2"}
    agent.apply_commercial_authority_approval(_approval())
    assert created["n"] == 0  # still no order created


# ===========================================================================
# Guard: with no pending commercial order, method fails safely (no crash).
# ===========================================================================
def test_commercial_rejection_without_pending_is_safe(monkeypatch):
    agent = _bare_commercial_agent()
    agent.pending_commercial_order = None
    agent._continue_after_human_action = lambda: {"success": True, "response": "ok"}
    result = agent.apply_commercial_authority_rejection(_approval())
    # Should still succeed (informing the customer) OR return a safe result;
    # it must never raise and never create an order.
    assert isinstance(result, dict)


# ===========================================================================
# DB LAYER: reject_request works for a COMMERCIAL_AUTHORITY row (temp DB) and
# get_rejected_unprocessed_requests returns it with reason preserved.
# ===========================================================================
@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_lioncity.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    db.create_tables()
    return db_file


def test_reject_request_handles_commercial_authority_row(temp_db):
    created = db.create_approval_request(
        phone=PHONE, requested_percent=10.0,
        approval_type="COMMERCIAL_AUTHORITY", sku="CBL-210",
        requested_quantity=10, order_value=108.0, reason="HIGH_VALUE",
    )
    approval_id = created["approval_id"]
    res = db.reject_request(approval_id)
    assert res["success"] is True
    assert res["status"] == "REJECTED"

    rejected = db.get_rejected_unprocessed_requests()
    ids = {r["approval_id"] for r in rejected}
    assert approval_id in ids
    row = [r for r in rejected if r["approval_id"] == approval_id][0]
    assert row["approval_type"] == "COMMERCIAL_AUTHORITY"
    assert row["reason"] == "HIGH_VALUE"
    assert row["approved_percent"] is None      # never "approved 0%"
    assert row["order_id"] is None              # no order

    # Idempotency at the DB layer: a second reject on a non-PENDING row fails.
    res2 = db.reject_request(approval_id)
    assert res2["success"] is False



# ===========================================================================
# ENDPOINT LAYER: /process-approvals must route a rejected COMMERCIAL_AUTHORITY
# row to apply_commercial_authority_rejection (NOT the legacy discount path),
# send the customer the resulting message, and mark it processed exactly once.
#
# fastapi/requests are not installed in this offline sandbox, so we register
# minimal stubs BEFORE importing app.whatsapp_api (mirroring tests/_agent_harness).
# ===========================================================================
import sys
import types


def _install_web_stubs():
    if "dotenv" not in sys.modules:
        _d = types.ModuleType("dotenv")
        _d.load_dotenv = lambda *a, **k: False
        sys.modules["dotenv"] = _d
    if "requests" not in sys.modules:
        _r = types.ModuleType("requests")
        _r.exceptions = types.SimpleNamespace(
            ConnectionError=type("ConnectionError", (Exception,), {}),
            Timeout=type("Timeout", (Exception,), {}),
            RequestException=type("RequestException", (Exception,), {}),
        )
        sys.modules["requests"] = _r
    if "fastapi" not in sys.modules:
        _f = types.ModuleType("fastapi")

        class _FastAPI:
            def __init__(self, *a, **k):
                pass

            def _decorator(self, *a, **k):
                def wrap(fn):
                    return fn
                return wrap

            get = post = _decorator

        _f.FastAPI = _FastAPI
        _f.Query = lambda *a, **k: None
        _f.Request = object
        sys.modules["fastapi"] = _f
        _fr = types.ModuleType("fastapi.responses")
        _fr.PlainTextResponse = object
        sys.modules["fastapi.responses"] = _fr


class _FakeRejectionAgent:
    def __init__(self):
        self.commercial_called_with = None
        self.discount_called = False

    def apply_commercial_authority_rejection(self, approval):
        self.commercial_called_with = approval
        return {
            "success": True,
            "response": "Your requested order could not be approved.",
        }

    def apply_human_rejection(self, requested_discount_percent=None):
        self.discount_called = True
        raise AssertionError(
            "Legacy discount rejection path must NOT be used for "
            "COMMERCIAL_AUTHORITY."
        )


def test_process_approvals_routes_commercial_rejection(monkeypatch):
    _install_web_stubs()
    from app import whatsapp_api

    phone = PHONE
    approval_id = 4242
    rejected_row = {
        "approval_id": approval_id, "phone": phone,
        "approval_type": "COMMERCIAL_AUTHORITY", "status": "REJECTED",
        "sku": "CBL-210", "requested_quantity": 10, "order_value": 108.0,
        "requested_percent": 10.0, "approved_percent": None,
        "reason": "HIGH_VALUE",
    }

    fake_agent = _FakeRejectionAgent()
    whatsapp_api.customer_agents.clear()
    whatsapp_api.customer_agents[phone] = fake_agent

    # No approvals this cycle; one commercial rejection.
    monkeypatch.setattr(whatsapp_api, "get_approved_unprocessed_requests",
                        lambda: [])
    monkeypatch.setattr(whatsapp_api, "get_rejected_unprocessed_requests",
                        lambda: [rejected_row])

    sent = []
    monkeypatch.setattr(whatsapp_api, "send_whatsapp_message",
                        lambda recipient, message: sent.append(
                            {"recipient": recipient, "message": message}))

    processed_ids = []
    monkeypatch.setattr(whatsapp_api, "mark_approval_processed",
                        lambda approval_id: processed_ids.append(approval_id))

    logged = []
    monkeypatch.setattr(whatsapp_api, "log_sales_event",
                        lambda **kw: logged.append(kw))

    result = whatsapp_api.process_approvals()

    assert result["success"] is True
    assert result["processed"] == [approval_id]
    assert result["skipped"] == []
    # Correct commercial rejection method received the FULL trusted row.
    assert fake_agent.commercial_called_with == rejected_row
    assert fake_agent.discount_called is False
    # Customer notified with the agent's rejection message.
    assert sent == [{"recipient": phone,
                     "message": "Your requested order could not be approved."}]
    # Consumed exactly once (idempotency: repeat cycles see no unprocessed row).
    assert processed_ids == [approval_id]
    # Event logged with non-discount, reason-aware wording.
    assert len(logged) == 1
    assert logged[0]["event_type"] == "HUMAN_APPROVAL_REJECTED"
    assert "discount" not in logged[0]["details"].lower()
    assert "HIGH_VALUE" in logged[0]["details"]

    whatsapp_api.customer_agents.clear()
