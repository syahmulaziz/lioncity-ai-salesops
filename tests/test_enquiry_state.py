"""
Unit tests for EnquiryState (Task 13, Batch 1).

Covers the Category A validation/update mechanism, the None-vs-False
semantics, correction behaviour, and the trust boundary that rejects
attempts to set Category B / C fields through the untrusted signal path.

All tests are pure, offline, and assertion-based (no LLM / DB / network).
"""

from app.enquiry_state import EnquiryState


# ----------------------------------------------------------------------
# 1. Default / empty EnquiryState
# ----------------------------------------------------------------------

def test_default_state_is_all_unknown():
    state = EnquiryState()

    # Category A tri-state / value fields start as None (unknown).
    assert state.product_query is None
    assert state.quantity is None
    assert state.business_customer is None
    assert state.company_name is None
    assert state.quotation_requested is None
    assert state.urgent is None
    assert state.discount_requested is None
    assert state.current_intent is None
    assert state.human_requested is None

    # Category B verified fields.
    assert state.existing_customer is False
    assert state.customer_id is None
    assert state.customer_tier is None
    assert state.product_sku is None
    assert state.product_name is None
    assert state.verified_subtotal is None

    # Category C result.
    assert state.last_triage is None


# ----------------------------------------------------------------------
# 2. None versus False semantics
# ----------------------------------------------------------------------

def test_none_versus_false_semantics():
    state = EnquiryState()

    # Unknown by default.
    assert state.quotation_requested is None

    # Explicit False is distinct from unknown None.
    state.apply_candidate({"quotation_requested": False})
    assert state.quotation_requested is False
    assert state.quotation_requested is not None


# ----------------------------------------------------------------------
# 3. Valid Category A update
# ----------------------------------------------------------------------

def test_valid_category_a_update():
    state = EnquiryState()

    report = state.apply_candidate({
        "product_query": "Industrial Cable",
        "quantity": 30,
        "business_customer": True,
        "company_name": "ABC Construction",
        "quotation_requested": True,
        "urgent": True,
        "discount_requested": False,
        "current_intent": "SALES_ENQUIRY",
        "human_requested": False,
    })

    assert report["rejected"] == {}
    assert state.product_query == "Industrial Cable"
    assert state.quantity == 30
    assert state.business_customer is True
    assert state.company_name == "ABC Construction"
    assert state.quotation_requested is True
    assert state.urgent is True
    assert state.discount_requested is False
    assert state.current_intent == "SALES_ENQUIRY"
    assert state.human_requested is False


# ----------------------------------------------------------------------
# 4. Quantity correction 30 -> 50 (last-valid-update-wins)
# ----------------------------------------------------------------------

def test_quantity_correction_last_write_wins():
    state = EnquiryState()

    state.apply_candidate({"quantity": 30})
    assert state.quantity == 30

    state.apply_candidate({"quantity": 50})
    assert state.quantity == 50


# ----------------------------------------------------------------------
# 5. quotation_requested: None -> True -> False
# ----------------------------------------------------------------------

def test_quotation_requested_transitions():
    state = EnquiryState()

    assert state.quotation_requested is None

    state.apply_candidate({"quotation_requested": True})
    assert state.quotation_requested is True

    # "I don't need a quotation anymore."
    state.apply_candidate({"quotation_requested": False})
    assert state.quotation_requested is False


# ----------------------------------------------------------------------
# 6. business_customer: None -> True -> False
# ----------------------------------------------------------------------

def test_business_customer_transitions():
    state = EnquiryState()

    assert state.business_customer is None

    state.apply_candidate({"business_customer": True})
    assert state.business_customer is True

    # "Actually it's for personal use."
    state.apply_candidate({"business_customer": False})
    assert state.business_customer is False


# ----------------------------------------------------------------------
# 7. Unrelated fields survive a correction
# ----------------------------------------------------------------------

def test_unrelated_fields_survive_correction():
    state = EnquiryState()

    state.apply_candidate({
        "quantity": 30,
        "quotation_requested": True,
        "company_name": "ABC Construction",
    })

    # Correct only the quantity.
    state.apply_candidate({"quantity": 50})

    assert state.quantity == 50
    # Untouched fields remain.
    assert state.quotation_requested is True
    assert state.company_name == "ABC Construction"


# ----------------------------------------------------------------------
# 8-13. Untrusted signal path must REJECT Category B / C fields
# ----------------------------------------------------------------------

def test_reject_customer_id_via_signal_path():
    state = EnquiryState()
    report = state.apply_candidate({"customer_id": "CUST-001"})

    assert "customer_id" in report["rejected"]
    assert state.customer_id is None


def test_reject_customer_tier_via_signal_path():
    state = EnquiryState()
    report = state.apply_candidate({"customer_tier": "GOLD"})

    assert "customer_tier" in report["rejected"]
    assert state.customer_tier is None


def test_reject_verified_subtotal_via_signal_path():
    state = EnquiryState()
    report = state.apply_candidate({"verified_subtotal": 10000})

    assert "verified_subtotal" in report["rejected"]
    assert state.verified_subtotal is None


def test_reject_verified_unit_price_via_signal_path():
    state = EnquiryState()
    report = state.apply_candidate({"verified_unit_price": 999})

    assert "verified_unit_price" in report["rejected"]
    assert state.verified_unit_price is None


def test_reject_customer_value_score_via_signal_path():
    state = EnquiryState()
    report = state.apply_candidate({"customer_value_score": 99})

    assert "customer_value_score" in report["rejected"]
    # No such attribute should have been created/set.
    assert getattr(state, "customer_value_score", None) is None


def test_reject_total_priority_score_via_signal_path():
    state = EnquiryState()
    report = state.apply_candidate({"total_priority_score": 99})

    assert "total_priority_score" in report["rejected"]
    assert getattr(state, "total_priority_score", None) is None


def test_reject_priority_band_via_signal_path():
    state = EnquiryState()
    report = state.apply_candidate({"priority_band": "HIGH_PRIORITY"})

    assert "priority_band" in report["rejected"]
    assert getattr(state, "priority_band", None) is None


# ----------------------------------------------------------------------
# 23 (state side). Customer-supplied monetary claim cannot reach
# verified_subtotal via the signal path; existing_customer cannot be
# faked either.
# ----------------------------------------------------------------------

def test_customer_supplied_fake_stock_and_identity_ignored():
    state = EnquiryState()

    # A customer/LLM trying to fake trusted facts through the signal path.
    report = state.apply_candidate({
        "existing_customer": True,      # Category B - must be rejected
        "verified_subtotal": 10000,     # Category B - must be rejected
        "quantity": 5,                  # Category A - allowed
    })

    assert "existing_customer" in report["rejected"]
    assert "verified_subtotal" in report["rejected"]
    assert state.existing_customer is False
    assert state.verified_subtotal is None
    # The legitimate Category A field still applied.
    assert state.quantity == 5


# ----------------------------------------------------------------------
# Extra validation guards (type checks)
# ----------------------------------------------------------------------

def test_invalid_quantity_types_rejected():
    state = EnquiryState()

    assert "quantity" in state.apply_candidate({"quantity": "30"})["rejected"]
    assert state.quantity is None

    assert "quantity" in state.apply_candidate({"quantity": -5})["rejected"]
    assert state.quantity is None

    # bool must not be accepted as an int quantity.
    assert "quantity" in state.apply_candidate({"quantity": True})["rejected"]
    assert state.quantity is None


def test_invalid_intent_rejected_but_valid_accepted():
    state = EnquiryState()

    assert "current_intent" in state.apply_candidate(
        {"current_intent": "NONSENSE"}
    )["rejected"]
    assert state.current_intent is None

    state.apply_candidate({"current_intent": "faq_general"})
    assert state.current_intent == "FAQ_GENERAL"


def test_trusted_setters_populate_category_b():
    """The application-owned trusted path (not the LLM path) populates B."""
    state = EnquiryState()

    state.set_customer_from_tool({
        "success": True,
        "customer_id": "CUST-001",
        "account_tier": "GOLD",
        "company_name": "Apex Engineering Pte Ltd",
    })
    assert state.existing_customer is True
    assert state.customer_id == "CUST-001"
    assert state.customer_tier == "GOLD"

    # A failed find_customer => guest, not an error dead-end.
    guest = EnquiryState()
    guest.set_customer_from_tool({"success": False, "error": "CUSTOMER_NOT_FOUND"})
    assert guest.existing_customer is False
    assert guest.customer_id is None
    assert guest.customer_tier is None

    # Pricing sets verified_subtotal only on success.
    state.set_verified_value({"success": True, "subtotal": 5000})
    assert state.verified_subtotal == 5000.0

    state2 = EnquiryState()
    state2.set_verified_value({"success": False})
    assert state2.verified_subtotal is None
