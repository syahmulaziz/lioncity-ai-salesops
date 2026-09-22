"""
Feature A - DISCOUNT REJECTION, database layer.

Covers the reject_request() state transition, the unprocessed-rejection
query, and the completed-decision (get_latest_sales_state) distinction
between an APPROVED and a REJECTED decision.

DB SAFETY: every test here runs against a TEMPORARY sqlite file created by
monkeypatching app.database.DB_PATH. The committed data/lioncity.db is never
opened or mutated by this module.
"""

import importlib

import pytest

import app.database as db


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Point the database module at a fresh temp DB with the real schema."""
    db_file = tmp_path / "test_lioncity.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    db.create_tables()
    return db_file


def _make_pending(phone="+6580000001", requested=10.0):
    created = db.create_approval_request(
        phone=phone,
        requested_percent=requested,
    )
    assert created["success"] is True
    return created["approval_id"]


# A2 - PENDING -> REJECTED allowed.
def test_reject_pending_transitions_to_rejected(temp_db):
    approval_id = _make_pending()
    result = db.reject_request(approval_id)
    assert result["success"] is True
    assert result["status"] == "REJECTED"

    connection = db.get_connection()
    row = connection.execute(
        "SELECT status, approved_percent FROM approval_requests "
        "WHERE approval_id = ?",
        (approval_id,),
    ).fetchone()
    connection.close()
    assert row["status"] == "REJECTED"
    # A rejection NEVER writes an approved value (never an approved 0%).
    assert row["approved_percent"] is None


# A3 - rejected request no longer returned by the pending query.
def test_rejected_request_not_in_pending(temp_db):
    approval_id = _make_pending(phone="+6580000002")
    db.reject_request(approval_id)
    pending = db.get_pending_approvals()
    assert all(r["approval_id"] != approval_id for r in pending)


# A14 - repeated Reject does not create another decision.
def test_reject_twice_second_is_noop(temp_db):
    approval_id = _make_pending(phone="+6580000003")
    first = db.reject_request(approval_id)
    second = db.reject_request(approval_id)
    assert first["success"] is True
    assert second["success"] is False
    assert second["status"] is None


# APPROVED -> REJECTED refused (completed decision preserved).
def test_cannot_reject_an_approved_request(temp_db):
    approval_id = _make_pending(phone="+6580000004")
    db.approve_request(approval_id, approved_percent=5.0)
    result = db.reject_request(approval_id)
    assert result["success"] is False

    connection = db.get_connection()
    row = connection.execute(
        "SELECT status, approved_percent FROM approval_requests "
        "WHERE approval_id = ?",
        (approval_id,),
    ).fetchone()
    connection.close()
    assert row["status"] == "APPROVED"
    assert row["approved_percent"] == 5.0


# PROCESSED -> REJECTED refused.
def test_cannot_reject_a_processed_request(temp_db):
    approval_id = _make_pending(phone="+6580000005")
    db.approve_request(approval_id, approved_percent=5.0)
    db.mark_approval_processed(approval_id)
    result = db.reject_request(approval_id)
    assert result["success"] is False


# A15 - approve-after-reject cannot silently convert REJECTED to APPROVED.
def test_cannot_approve_after_reject(temp_db):
    approval_id = _make_pending(phone="+6580000006")
    db.reject_request(approval_id)
    result = db.approve_request(approval_id, approved_percent=5.0)
    assert result["success"] is False

    connection = db.get_connection()
    row = connection.execute(
        "SELECT status, approved_percent FROM approval_requests "
        "WHERE approval_id = ?",
        (approval_id,),
    ).fetchone()
    connection.close()
    assert row["status"] == "REJECTED"
    assert row["approved_percent"] is None


# Unknown approval id fails safely.
def test_reject_unknown_id_fails_safely(temp_db):
    result = db.reject_request(999999)
    assert result["success"] is False
    assert result["status"] is None


# get_rejected_unprocessed_requests returns rejected, not approved rows.
def test_rejected_unprocessed_query(temp_db):
    rejected_id = _make_pending(phone="+6580000007")
    approved_id = _make_pending(phone="+6580000008")
    db.reject_request(rejected_id)
    db.approve_request(approved_id, approved_percent=5.0)

    rejected = db.get_rejected_unprocessed_requests()
    ids = {r["approval_id"] for r in rejected}
    assert rejected_id in ids
    assert approved_id not in ids

    # Once processed, the rejected row leaves the unprocessed set.
    db.mark_approval_processed(rejected_id)
    rejected_after = db.get_rejected_unprocessed_requests()
    assert all(r["approval_id"] != rejected_id for r in rejected_after)


# A11 - completed state distinguishes REJECTED from APPROVED (never "0%").
def test_latest_sales_state_rejected_vs_approved(temp_db):
    # A processed rejection -> AWAITING_CUSTOMER_REJECTED, decision REJECTED,
    # discount_percent None (never 0), requested percent surfaced.
    rid = _make_pending(phone="+6580000009", requested=10.0)
    db.reject_request(rid)
    # Provide a sales event so get_latest_sales_state uses the approval path
    # (it returns READY when no event exists at all).
    db.log_sales_event(event_type="HUMAN_APPROVAL_REJECTED", phone="+6580000009",
                       details="Rejected discount: 10.0%")
    db.mark_approval_processed(rid)

    state = db.get_latest_sales_state()
    assert state["status"] == "AWAITING_CUSTOMER_REJECTED"
    assert state["decision"] == "REJECTED"
    assert state["discount_percent"] is None
    assert state["requested_percent"] == 10.0


def test_latest_sales_state_approved_is_unchanged(temp_db):
    aid = _make_pending(phone="+6580000010", requested=10.0)
    db.approve_request(aid, approved_percent=5.0)
    db.log_sales_event(event_type="HUMAN_APPROVAL_APPROVED", phone="+6580000010",
                       details="Approved discount: 5.0%")
    db.mark_approval_processed(aid)

    state = db.get_latest_sales_state()
    assert state["status"] == "AWAITING_CUSTOMER"
    assert state["decision"] == "APPROVED"
    assert state["discount_percent"] == 5.0
