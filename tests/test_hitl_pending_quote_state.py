"""
Regression: CURRENT QUOTE (and customer/tier) must NOT disappear from the
Sales Console while a discount HITL approval is PENDING.

LIVE BUG (staging 1c01d7c): customer orders 10 x CBL-210 @ S$12 (trusted
subtotal S$120), requests a 10% discount which exceeds the AI's 5% authority,
so a DISCOUNT human-approval is created and left PENDING. At that point the
Sales Console top section shows:
    Active Customer: -
    Account Tier: -
    Current Quote: -
    Human Decisions: 1
The pending Human Decision card is correct, but the top-level current-deal
context vanished.

Root cause: the trusted subtotal lived only in in-memory
EnquiryState.verified_subtotal and was never persisted when the DISCOUNT
approval was created (approval_requests.order_value left NULL, the
HUMAN_APPROVAL_REQUIRED sales_event logged amount=None). get_latest_sales_state()
therefore returned quote_amount=None (and no customer identity) in its
PENDING/HUMAN_APPROVAL branch.

Expected: while PENDING, get_latest_sales_state() surfaces the TRUSTED
persisted quote (S$120) and the customer identity (resolved from the pending
approval's phone), WITHOUT representing the requested 10% as approved. When no
trusted subtotal was persisted, it must NOT fabricate a quote.

DB SAFETY: this module runs entirely against a TEMPORARY sqlite file
(app.database.DB_PATH monkeypatched). The committed data/lioncity.db is never
opened or mutated.
"""

import pytest

import app.database as db


CUST_PHONE = "+6591112222"
CUST_ID = "CUST-HITL-1"
COMPANY = "Apex Engineering Pte Ltd"
TIER = "GOLD"
SUBTOTAL = 120.0


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Point the database module at a fresh temp DB with the real schema."""
    db_file = tmp_path / "test_lioncity.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    db.create_tables()
    return db_file


def _seed_customer(phone=CUST_PHONE):
    db.add_customer(
        customer_id=CUST_ID,
        company_name=COMPANY,
        contact_name="Jane Tan",
        phone=phone,
        account_tier=TIER,
        delivery_area="Jurong",
        assigned_sales_rep="Marcus",
    )


# ----------------------------------------------------------------------
# PRIMARY: pending discount HITL must still expose the trusted current
# quote and the customer/tier - without treating the requested % as approved.
# ----------------------------------------------------------------------
def test_pending_discount_hitl_preserves_current_quote_and_customer(temp_db):
    _seed_customer()

    # Create the DISCOUNT approval exactly as the webhook does when the AI
    # escalates an over-authority discount - now persisting the TRUSTED
    # subtotal (S$120) as the current quote/order value.
    created = db.create_approval_request(
        phone=CUST_PHONE,
        requested_percent=10.0,
        approval_type="DISCOUNT",
        order_value=SUBTOTAL,          # trusted current quote at HITL time
        sku="CBL-210",
        requested_quantity=10,
    )
    assert created["success"] is True
    assert created["status"] == "PENDING"

    # Log the escalation event as the webhook does.
    db.log_sales_event(
        event_type="HUMAN_APPROVAL_REQUIRED",
        phone=CUST_PHONE,
        details="Discount requested: 10.0%",
    )

    # Pending count still correct.
    pending = db.get_pending_approvals()
    assert len(pending) == 1
    assert pending[0]["requested_percent"] == 10.0

    state = db.get_latest_sales_state()

    # The console top section must still show the current deal:
    assert state["status"] == "HUMAN_APPROVAL"
    # Current Quote must be the TRUSTED S$120 (not None -> not "-").
    assert state["quote_amount"] == SUBTOTAL
    # Requested discount must NOT be represented as approved.
    assert state.get("discount_percent") is None
    assert state.get("decision") != "APPROVED"
    # The requested percent is available (for display as "requested", pending).
    assert state.get("requested_percent") == 10.0
    # Customer identity is resolvable while pending.
    assert state.get("phone") == CUST_PHONE
    assert state.get("company_name") == COMPANY
    assert state.get("account_tier") == TIER


# ----------------------------------------------------------------------
# Customer/tier resolvable directly from the pending approval's phone.
# ----------------------------------------------------------------------
def test_get_customer_by_phone_resolves_pending_customer(temp_db):
    _seed_customer()
    db.create_approval_request(
        phone=CUST_PHONE, requested_percent=10.0, approval_type="DISCOUNT",
        order_value=SUBTOTAL, sku="CBL-210", requested_quantity=10,
    )
    customer = db.get_customer_by_phone(CUST_PHONE)
    assert customer is not None
    assert customer["company_name"] == COMPANY
    assert customer["account_tier"] == TIER


# ----------------------------------------------------------------------
# NO FABRICATION: if no trusted subtotal was persisted (order_value NULL),
# the pending state must NOT invent a quote.
# ----------------------------------------------------------------------
def test_pending_discount_without_trusted_subtotal_does_not_fabricate(temp_db):
    _seed_customer()
    db.create_approval_request(
        phone=CUST_PHONE,
        requested_percent=10.0,
        approval_type="DISCOUNT",
        # order_value intentionally omitted -> NULL (no trusted subtotal)
    )
    # Log the escalation event as the webhook does, so state reaches the
    # PENDING (HUMAN_APPROVAL) branch (get_latest_sales_state returns READY
    # only when there is no sales_event at all).
    db.log_sales_event(
        event_type="HUMAN_APPROVAL_REQUIRED",
        phone=CUST_PHONE,
        details="Discount requested: 10.0%",
    )
    state = db.get_latest_sales_state()
    assert state["status"] == "HUMAN_APPROVAL"
    assert state["quote_amount"] is None          # not fabricated
    assert state.get("discount_percent") is None    # not approved


# ----------------------------------------------------------------------
# No order is auto-created merely because a discount HITL is pending.
# ----------------------------------------------------------------------
def test_pending_discount_hitl_creates_no_order(temp_db):
    _seed_customer()
    db.create_approval_request(
        phone=CUST_PHONE, requested_percent=10.0, approval_type="DISCOUNT",
        order_value=SUBTOTAL, sku="CBL-210", requested_quantity=10,
    )
    connection = db.get_connection()
    orders = connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    connection.close()
    assert orders == 0
