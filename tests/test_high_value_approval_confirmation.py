"""
Regression: missing customer confirmation after a HIGH_VALUE (and other)
Commercial Authority APPROVAL.

LIVE BUG (staging 7a10157):
After a high-value transaction is approved through Commercial Authority, the
agent produced NO customer-facing confirmation. Root cause:

  1. `evaluate_commercial_authority` stores the approval with the eval-time
     `order_value` (e.g. the product subtotal).
  2. The customer confirms -> `create_order` is attempted with `final_total`
     (subtotal + delivery fee), is blocked by HIGH_VALUE, and the exact
     transaction is preserved in `pending_commercial_order`.
  3. A human APPROVES. `apply_commercial_authority_approval` resumes by
     retrying `create_order`, which RE-RUNS the commercial-authority gate.
     That gate calls `get_matching_commercial_approval(... order_value=
     final_total ...)`, matched against the stored `order_value` with a
     `< 0.01` tolerance. Because `final_total != eval order_value`, NO
     approval matches, so the retry returns `HUMAN_APPROVAL_REQUIRED` again.
  4. `apply_commercial_authority_approval` then returns
     `{"success": False, ...}` WITHOUT any `"response"` key, and the
     `/process-approvals` endpoint's `if not result.get("success"): continue`
     skips `send_whatsapp_message` entirely -> the customer receives NOTHING,
     the order is never created, and the approval is never marked PROCESSED.

A human approval of an ALREADY-CONFIRMED commercial transaction must not be
gated again on a re-derived authority match: it must resume the exact
preserved order and confirm it to the customer.

These tests are OFFLINE: the committed data/lioncity.db is never written
(DB_PATH is monkeypatched to a temp file, and create_order - the real DB
writer - is stubbed), and no live LLM / WhatsApp API is called.
"""

import pytest

# Import the harness FIRST so anthropic/dotenv/requests are stubbed before
# app.agent imports them.
from tests._agent_harness import build_agent, patch_commercial_policies
import app.agent as agent_module
import app.database as db


PHONE = "+6580000000"
SKU = "CBL-210"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_lioncity.db")
    db.create_tables()
    return db.DB_PATH


def _stub_create_order(monkeypatch, counter, order_id="SO-HV-001"):
    """Stub ONLY the trusted create_order DB writer (leaves the real
    execute_tool authority gate intact so the bug path is exercised)."""

    def fake_create_order(**kw):
        counter["n"] += 1
        return {
            "success": True, "order_id": order_id, "status": "CONFIRMED",
            "customer_id": kw["customer_id"], "items": kw["items"],
            "product_subtotal": kw["product_subtotal"],
            "discount_percent": kw["discount_percent"],
            "delivery_fee": kw["delivery_fee"],
            "final_total": kw["final_total"],
            "delivery_area": kw["delivery_area"],
            "delivery_date": kw["delivery_date"],
        }

    monkeypatch.setattr(agent_module, "create_order", fake_create_order)


def _order_input(final_total, discount_percent=0.0, quantity=10,
                 delivery_fee=35.0):
    return {
        "phone": PHONE, "customer_id": "CUST-001",
        "items": [{"sku": SKU, "quantity": quantity, "unit_price": 12.0}],
        "product_subtotal": 120.0, "discount_percent": discount_percent,
        "delivery_fee": delivery_fee, "final_total": final_total,
        "delivery_area": "Jurong", "delivery_date": "2026-09-15",
    }


def _eval_input(order_value, discount_percent=0.0, quantity=10):
    return {"sku": SKU, "quantity": quantity, "order_value": order_value,
            "discount_percent": discount_percent, "phone": PHONE}


def _drive_confirmed_commercial_transaction(
    monkeypatch, counter, eval_order_value, order_final_total,
    discount_percent=0.0, quantity=10, delivery_fee=35.0,
):
    """Realistic production sequence up to (but excluding) human approval.

    turn 1: LLM evaluates authority (creates a PENDING COMMERCIAL_AUTHORITY
    approval) AND, in the same confirmed turn, calls create_order -> blocked
    by authority -> pending_commercial_order preserved.
    Returns (agent, approval_row_dict).
    """
    _stub_create_order(monkeypatch, counter)
    script = [
        [("evaluate_commercial_authority",
          _eval_input(eval_order_value, discount_percent, quantity)),
         ("create_order",
          _order_input(order_final_total, discount_percent, quantity,
                       delivery_fee))],
        "I've submitted this high-value order for approval.",
    ]
    agent, _tools = build_agent(monkeypatch, script)
    agent.enquiry.product_sku = SKU
    agent.enquiry.quantity = quantity

    agent.send("Yes, please place the order")

    assert agent.pending_commercial_order is not None, (
        "precondition: create_order should have been blocked and preserved"
    )
    assert counter["n"] == 0, "no order should exist before approval"

    pend = db.get_pending_approvals()
    assert len(pend) == 1, "a COMMERCIAL_AUTHORITY approval must be pending"
    row = pend[0]
    # Human approves exactly as the Sales Console does.
    db.approve_request(approval_id=row["approval_id"],
                       approved_percent=(row["requested_percent"] or 0))
    approved = db.get_approval_by_id(row["approval_id"])
    return agent, dict(approved)


def _assert_confirms_order(result, counter):
    """The approval must yield a customer-facing confirmation of a created
    order, using the trusted order result - never a 'still needs approval'
    message and never a silent drop."""
    assert isinstance(result, dict)
    assert result.get("success") is True, (
        "approval must succeed so /process-approvals sends a response"
    )
    response = result.get("response")
    assert isinstance(response, str) and response.strip(), (
        "a non-empty customer-facing response is required"
    )
    assert counter["n"] == 1, "exactly one order must be created"
    low = response.lower()
    # Trusted order confirmation, not a pending/approval-needed message.
    assert "order" in low
    assert "SO-HV-001" in response or "reference" in low
    for forbidden in ("still need", "cannot proceed", "needs approval",
                      "pending approval", "awaiting approval"):
        assert forbidden not in low, f"must not imply pending: {forbidden!r}"


# ===========================================================================
# Scenario A / E — HIGH_VALUE approval where eval order_value != final_total
# (the reported live bug). Must confirm the created order to the customer.
# ===========================================================================
def test_high_value_approval_confirms_order(temp_db, monkeypatch):
    patch_commercial_policies(monkeypatch)
    counter = {"n": 0}
    # eval on subtotal (15000); order final_total includes delivery (15035).
    agent, approval = _drive_confirmed_commercial_transaction(
        monkeypatch, counter,
        eval_order_value=15000.0, order_final_total=15035.0,
    )
    result = agent.apply_commercial_authority_approval(approval)
    _assert_confirms_order(result, counter)
    assert agent.pending_commercial_order is None


# ===========================================================================
# Scenario A (exact match still works) — regression guard: when eval and
# final_total are identical, behaviour is unchanged (order confirmed).
# ===========================================================================
def test_high_value_approval_confirms_when_values_match(temp_db, monkeypatch):
    patch_commercial_policies(monkeypatch)
    counter = {"n": 0}
    agent, approval = _drive_confirmed_commercial_transaction(
        monkeypatch, counter,
        eval_order_value=15000.0, order_final_total=15000.0, delivery_fee=0.0,
    )
    result = agent.apply_commercial_authority_approval(approval)
    _assert_confirms_order(result, counter)
    assert agent.pending_commercial_order is None


# ===========================================================================
# HIGH_QUANTITY approval (not just HIGH_VALUE) with divergent totals.
# ===========================================================================
def test_high_quantity_approval_confirms_order(temp_db, monkeypatch):
    patch_commercial_policies(monkeypatch)
    counter = {"n": 0}
    # quantity 700 > MAX_QUANTITY_PER_SKU (500) -> HIGH_QUANTITY.
    agent, approval = _drive_confirmed_commercial_transaction(
        monkeypatch, counter,
        eval_order_value=8000.0, order_final_total=8040.0, quantity=700,
    )
    assert "HIGH_QUANTITY" in (approval.get("reason") or "")
    result = agent.apply_commercial_authority_approval(approval)
    _assert_confirms_order(result, counter)
    assert agent.pending_commercial_order is None


# ===========================================================================
# Scenario B — Exactly once. Re-processing the same APPROVED transaction must
# not create a second order or re-run the transaction.
# ===========================================================================
def test_approval_is_processed_exactly_once(temp_db, monkeypatch):
    patch_commercial_policies(monkeypatch)
    counter = {"n": 0}
    agent, approval = _drive_confirmed_commercial_transaction(
        monkeypatch, counter,
        eval_order_value=15000.0, order_final_total=15035.0,
    )
    first = agent.apply_commercial_authority_approval(approval)
    _assert_confirms_order(first, counter)
    assert counter["n"] == 1

    # Reload the (now order-linked) approval row and re-process it.
    reloaded = db.get_approval_by_id(approval["approval_id"])
    second = agent.apply_commercial_authority_approval(dict(reloaded))
    assert second.get("success") is True
    assert isinstance(second.get("response"), str) and second["response"].strip()
    assert counter["n"] == 1, "no duplicate order may be created on re-process"


# ===========================================================================
# Scenario C — Rejection regression. Commercial rejection must still work,
# create no order, return a rejection response, and clear pending state.
# ===========================================================================
def test_commercial_rejection_still_works(temp_db, monkeypatch):
    patch_commercial_policies(monkeypatch)
    counter = {"n": 0}
    agent, approval = _drive_confirmed_commercial_transaction(
        monkeypatch, counter,
        eval_order_value=15000.0, order_final_total=15035.0,
    )
    # Build a REJECTED row from the same approval and drive the rejection.
    approval["reason"] = "HIGH_VALUE"

    captured = {}

    def _fake_continue():
        text = agent._finalize_customer_response([
            type("B", (), {"type": "text",
                           "text": "Good news, your order is placed!"})()
        ])
        captured["r"] = text
        return {"success": True, "response": text}

    agent._continue_after_human_action = _fake_continue
    result = agent.apply_commercial_authority_rejection(approval)
    assert result.get("success") is True
    assert counter["n"] == 0, "rejection must not create an order"
    assert agent.pending_commercial_order is None
    low = (result.get("response") or captured.get("r") or "").lower()
    assert "not be approved" in low or "not approved" in low
    assert "order is placed" not in low


# ===========================================================================
# Scenario D — Ordinary (below-authority) transaction is unaffected: it never
# needs commercial approval and creates the order directly.
# ===========================================================================
def test_normal_transaction_below_authority_unaffected(temp_db, monkeypatch):
    patch_commercial_policies(monkeypatch)
    counter = {"n": 0}
    _stub_create_order(monkeypatch, counter, order_id="SO-NORMAL-1")

    # final_total 155, quantity 10, discount 0 -> all within authority.
    script = [
        [("create_order", _order_input(155.0, quantity=10, delivery_fee=35.0))],
        "Order created!",
    ]
    agent, _tools = build_agent(monkeypatch, script)
    agent.enquiry.product_sku = SKU
    agent.enquiry.quantity = 10

    result = agent.send("Yes, place my order")
    assert counter["n"] == 1, "ordinary order should be created directly"
    assert agent.pending_commercial_order is None
    # No approval row should have been created.
    assert db.get_pending_approvals() == []
    assert "order" in result["response"].lower()
