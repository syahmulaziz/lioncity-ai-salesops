"""
Feature B - DELIVERY PROCEED PROMPT (reconciled onto e213572).

After a trusted AVAILABLE delivery check, the customer-facing reply ends
with a clear proceed question ONLY when trusted state proves the next
legitimate action is customer confirmation:

    no pending discount approval
    AND no pending commercial-authority order
    AND delivery available this cycle (trusted snapshot)
    AND verified product + validated quantity (EnquiryState)
    AND verified stock this cycle can fulfil the requested quantity
        (trusted check_inventory snapshot; out-of-stock / insufficient /
         no-check => suppressed)

Asking the question is rendering-only and NEVER calls create_order.

Offline scripted mock Claude. The runtime DB is only READ (delivery slots +
inventory SELECTs); nothing is written. Handoff logger stubbed by harness.
"""

import pytest

from tests._agent_harness import build_agent

# A seeded AVAILABLE slot (Jurong / 2026-09-15 / fee 35.0).
AVAIL_AREA = "Jurong"
AVAIL_DATE = "2026-09-15"
AVAIL_DISPLAY_DATE = "15-09-2026"
AVAIL_FEE = 35.0
# CBL-210 is seeded with 486 units in stock.
SKU, PNAME, IN_STOCK_QTY = "CBL-210", "Industrial Cable", 100
OVER_STOCK_QTY = 999999
PROCEED = "Would you like to proceed with the order?"


def _set_order_prereqs(agent, sku=SKU, name=PNAME, qty=IN_STOCK_QTY):
    agent.enquiry.product_sku = sku
    agent.enquiry.product_name = name
    agent.enquiry.quantity = qty


# B1 - available delivery + prereqs + sufficient verified stock -> PROMPT.
def test_available_delivery_ready_prompts(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE}),
         ("check_inventory", {"sku": SKU, "requested_quantity": IN_STOCK_QTY})],
        "Delivery is possible!",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _set_order_prereqs(agent)
    result = agent.send(f"Deliver {IN_STOCK_QTY} to {AVAIL_AREA} on {AVAIL_DATE}?")
    reply = result["response"]
    assert PROCEED in reply
    assert AVAIL_AREA in reply
    assert AVAIL_DISPLAY_DATE in reply
    assert f"S${AVAIL_FEE:,.2f}" in reply
    assert "create_order" not in tools


# B2 - unavailable delivery -> NO prompt.
def test_unavailable_delivery_no_prompt(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": "Nowhere-Zone",
                             "delivery_date": "2099-01-01"}),
         ("check_inventory", {"sku": SKU, "requested_quantity": IN_STOCK_QTY})],
        "Sorry, not available.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _set_order_prereqs(agent)
    result = agent.send("Deliver to Nowhere-Zone on 2099-01-01?")
    assert PROCEED not in result["response"]


# B3 - delivery tool failure -> NO prompt.
def test_delivery_tool_failure_no_prompt(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE})],
        "Trying delivery.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _set_order_prereqs(agent)

    import app.agent as agent_module

    def _boom(name, tool_input):
        raise RuntimeError("simulated delivery tool failure")

    monkeypatch.setattr(agent_module, "execute_tool", _boom)
    result = agent.send(f"Deliver to {AVAIL_AREA} on {AVAIL_DATE}?")
    assert PROCEED not in result["response"]


# B4 - malformed/unverified delivery (available but fee unverified via a
# monkeypatched malformed tool result) still requires availability=True; here
# we assert an unavailable/invalid snapshot yields no prompt (covered by B2/B3);
# additionally: no inventory check at all -> NO prompt even when delivery ok.
def test_available_delivery_but_no_inventory_check_no_prompt(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE})],
        "Delivery is possible!",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _set_order_prereqs(agent)
    result = agent.send(f"Deliver to {AVAIL_AREA} on {AVAIL_DATE}?")
    # Stock was never verified this cycle -> suppress.
    assert PROCEED not in result["response"]


# B5 - missing product -> NO prompt.
def test_missing_product_no_prompt(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE}),
         ("check_inventory", {"sku": SKU, "requested_quantity": IN_STOCK_QTY})],
        "Delivery is possible!",
    ]
    agent, tools = build_agent(monkeypatch, script)
    agent.enquiry.quantity = IN_STOCK_QTY  # quantity set, product missing
    result = agent.send(f"Deliver to {AVAIL_AREA} on {AVAIL_DATE}?")
    assert PROCEED not in result["response"]


# B6 - missing quantity -> NO prompt.
def test_missing_quantity_no_prompt(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE}),
         ("check_inventory", {"sku": SKU, "requested_quantity": IN_STOCK_QTY})],
        "Delivery is possible!",
    ]
    agent, tools = build_agent(monkeypatch, script)
    agent.enquiry.product_sku = SKU
    agent.enquiry.product_name = PNAME  # quantity missing
    result = agent.send(f"Deliver to {AVAIL_AREA} on {AVAIL_DATE}?")
    assert PROCEED not in result["response"]


# B7 - OUT_OF_STOCK / product-not-found inventory -> NO prompt.
def test_out_of_stock_no_prompt(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE}),
         ("check_inventory", {"sku": "NON-EXISTENT-SKU",
                              "requested_quantity": IN_STOCK_QTY})],
        "Delivery is possible!",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _set_order_prereqs(agent)
    result = agent.send(f"Deliver {IN_STOCK_QTY} to {AVAIL_AREA} on {AVAIL_DATE}?")
    # check_inventory returns success=False (PRODUCT_NOT_FOUND) -> suppress.
    assert PROCEED not in result["response"]


# B8 - requested quantity exceeds verified stock -> NO prompt.
def test_insufficient_stock_no_prompt(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE}),
         ("check_inventory", {"sku": SKU,
                              "requested_quantity": OVER_STOCK_QTY})],
        "Delivery is possible!",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _set_order_prereqs(agent, qty=OVER_STOCK_QTY)
    result = agent.send(f"Deliver {OVER_STOCK_QTY} to {AVAIL_AREA} on {AVAIL_DATE}?")
    # can_fulfil is False -> suppress.
    assert PROCEED not in result["response"]


# B9 - pending discount approval -> NO prompt.
def test_pending_discount_approval_no_prompt(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE}),
         ("check_inventory", {"sku": SKU, "requested_quantity": IN_STOCK_QTY})],
        "Delivery is possible!",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _set_order_prereqs(agent)
    agent.pending_approval = {
        "type": "DISCOUNT",
        "requested_discount_percent": 10,
        "ai_authority_limit_percent": 5,
        "status": "PENDING",
    }
    result = agent.send(f"Deliver to {AVAIL_AREA} on {AVAIL_DATE}?")
    assert PROCEED not in result["response"]


# B10 - pending commercial-authority order -> NO prompt.
def test_pending_commercial_order_no_prompt(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE}),
         ("check_inventory", {"sku": SKU, "requested_quantity": IN_STOCK_QTY})],
        "Delivery is possible!",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _set_order_prereqs(agent)
    agent.pending_commercial_order = {
        "phone": "+6580000000", "customer_id": "CUST-001",
        "items": [{"sku": SKU, "quantity": IN_STOCK_QTY, "unit_price": 12.0}],
        "product_subtotal": 1200.0, "discount_percent": 0.0,
        "delivery_fee": 35.0, "final_total": 1235.0,
        "delivery_area": AVAIL_AREA, "delivery_date": AVAIL_DATE,
    }
    result = agent.send(f"Deliver to {AVAIL_AREA} on {AVAIL_DATE}?")
    assert PROCEED not in result["response"]


# B11 - rendering the prompt never calls create_order.
def test_prompt_render_does_not_create_order(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE}),
         ("check_inventory", {"sku": SKU, "requested_quantity": IN_STOCK_QTY})],
        "Delivery is possible!",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _set_order_prereqs(agent)
    agent.send(f"Deliver {IN_STOCK_QTY} to {AVAIL_AREA} on {AVAIL_DATE}?")
    assert "create_order" not in tools


# B12 - customer has not confirmed after the prompt -> no order created.
def test_no_order_until_customer_confirms(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE}),
         ("check_inventory", {"sku": SKU, "requested_quantity": IN_STOCK_QTY})],
        "Delivery is possible!",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _set_order_prereqs(agent)
    r1 = agent.send(f"Deliver {IN_STOCK_QTY} to {AVAIL_AREA} on {AVAIL_DATE}?")
    assert PROCEED in r1["response"]
    assert "create_order" not in tools


# B13 - rejection + available delivery + ready -> rejection + delivery +
# proceed prompt coexist.
def test_rejection_plus_ready_delivery_prompt(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE}),
         ("check_inventory", {"sku": SKU, "requested_quantity": IN_STOCK_QTY})],
        "Your discount was approved and delivery is set!",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _set_order_prereqs(agent)
    agent.pending_approval = {
        "type": "DISCOUNT", "requested_discount_percent": 10,
        "ai_authority_limit_percent": 5, "status": "PENDING",
    }
    result = agent.apply_human_rejection(requested_discount_percent=10.0)
    reply = result["response"]
    assert "could not be approved" in reply.lower()
    assert "was approved" not in reply.lower()   # false approval blocked
    assert AVAIL_AREA in reply
    assert PROCEED in reply


# B14 - rejection + unavailable delivery -> rejection + unavailable, NO prompt.
def test_rejection_plus_unavailable_delivery_no_prompt(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": "Nowhere-Zone",
                             "delivery_date": "2099-01-01"})],
        "Your discount was approved!",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _set_order_prereqs(agent)
    agent.pending_approval = {
        "type": "DISCOUNT", "requested_discount_percent": 10,
        "ai_authority_limit_percent": 5, "status": "PENDING",
    }
    result = agent.apply_human_rejection(requested_discount_percent=10.0)
    reply = result["response"]
    assert "could not be approved" in reply.lower()
    assert "unavailable" in reply.lower()
    assert PROCEED not in reply


# B15 - delivery + quotation preserves trusted quotation content.
def test_delivery_plus_quotation_preserves_quotation(monkeypatch):
    script = [
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE}),
         ("check_inventory", {"sku": SKU, "requested_quantity": IN_STOCK_QTY}),
         ("generate_quotation_preview", {})],
        "Delivery available and here's your quote.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _set_order_prereqs(agent)
    result = agent.send(
        f"Deliver {IN_STOCK_QTY} to {AVAIL_AREA} on {AVAIL_DATE} and quote me"
    )
    reply = result["response"]
    assert f"S${AVAIL_FEE:,.2f}" in reply          # delivery
    assert "*Quotation Preview*" in reply          # quotation preserved
    assert PROCEED in reply                         # prompt last
    assert reply.rstrip().endswith(PROCEED)



# ======================================================================
# DELIVERY READINESS RECONCILIATION (persisted inventory verification).
#
# These reproduce the REAL multi-turn conversational sequences the prior
# same-cycle tests did not cover. Inventory verification now lives on
# EnquiryState, bound to SKU + requested quantity, so it survives a later
# delivery-only turn but is invalidated when the product or quantity
# changes, and never authorises an order that already exists.
# ======================================================================


# REAL JIRA MULTI-TURN: inventory verified turn 1; delivery-only turn 2.
# check_inventory is NOT called again on turn 2. Prompt must still appear.
def test_real_multiturn_delivery_only_second_turn_prompts(monkeypatch):
    script = [
        # TURN 1: establish product + verified sufficient stock.
        [("find_product", {"query": "Industrial Cable"}),
         ("check_inventory", {"sku": SKU, "requested_quantity": IN_STOCK_QTY})],
        "We have Industrial Cable in stock.",
        # TURN 2: delivery ONLY (no check_inventory).
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE})],
        "Delivery details below.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    # Validated quantity as the enquiry-signal path would set it.
    agent.enquiry.quantity = IN_STOCK_QTY

    agent.send("I want 100 units of Industrial Cable")
    # Trusted inventory verification is persisted and bound to SKU + qty.
    assert agent.enquiry.verified_inventory_sku == SKU
    assert agent.enquiry.verified_inventory_quantity == IN_STOCK_QTY
    assert agent.enquiry.verified_inventory_can_fulfil is True

    r2 = agent.send("Delivery to Jurong on 2026-09-15 can?")
    # Prompt appears WITHOUT re-running check_inventory on turn 2.
    assert tools.count("check_inventory") == 1
    assert PROCEED in r2["response"]
    assert AVAIL_AREA in r2["response"]


# QUANTITY CHANGE INVALIDATION: verified for qty 10; quantity changes to a
# different value; no re-check; available delivery -> NO prompt.
def test_quantity_change_invalidates_inventory_no_prompt(monkeypatch):
    script = [
        [("find_product", {"query": "Industrial Cable"}),
         ("check_inventory", {"sku": SKU, "requested_quantity": 10})],
        "In stock.",
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE})],
        "Delivery details.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    # Turn 1 verified for quantity 10.
    agent.enquiry.apply_candidate({"quantity": 10})
    agent.send("10 units of Industrial Cable please")
    assert agent.enquiry.verified_inventory_quantity == 10
    assert agent.enquiry.verified_inventory_can_fulfil is True

    # Quantity changes to a DIFFERENT value via the trusted signal path;
    # this must invalidate the persisted inventory verification.
    agent.enquiry.apply_candidate({"quantity": 500})
    assert agent.enquiry.verified_inventory_sku is None  # invalidated

    r2 = agent.send("Delivery to Jurong on 2026-09-15 can?")
    assert PROCEED not in r2["response"]


# SKU CHANGE INVALIDATION: verified SKU A; product changes to SKU B (no
# re-check for B); available delivery -> NO prompt.
def test_sku_change_invalidates_inventory_no_prompt(monkeypatch):
    script = [
        [("find_product", {"query": "Industrial Cable"}),
         ("check_inventory", {"sku": SKU, "requested_quantity": IN_STOCK_QTY})],
        "In stock.",
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE})],
        "Delivery details.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    agent.enquiry.apply_candidate({"quantity": IN_STOCK_QTY,
                                   "product_query": "Industrial Cable"})
    agent.send("100 units of Industrial Cable")
    assert agent.enquiry.verified_inventory_sku == SKU

    # Customer changes product to a different one via the trusted signal
    # path -> the SKU A verification must not authorise SKU B.
    agent.enquiry.apply_candidate({"product_query": "Industrial Adapter"})
    assert agent.enquiry.verified_inventory_sku is None  # invalidated

    r2 = agent.send("Delivery to Jurong on 2026-09-15 can?")
    assert PROCEED not in r2["response"]


# ALREADY-CREATED ORDER: current transaction order already created; a later
# otherwise-ready delivery lookup must NOT re-ask to proceed.
def test_already_created_order_suppresses_prompt(monkeypatch):
    # A completed order ends the transaction via
    # EnquiryState.reset_after_order_completion(), which clears product /
    # quantity / verified inventory. A subsequent delivery lookup for that
    # just-completed order therefore has no order-readiness prerequisites and
    # must NOT offer to proceed again. (The full order->reset lifecycle is
    # covered in tests/test_transaction_lifecycle.py.)
    script = [
        [("check_delivery", {"delivery_area": AVAIL_AREA,
                             "delivery_date": AVAIL_DATE}),
         ("check_inventory", {"sku": SKU, "requested_quantity": IN_STOCK_QTY})],
        "Delivery details.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    _set_order_prereqs(agent)
    # Simulate the current transaction's order having just completed.
    agent.enquiry.reset_after_order_completion()

    result = agent.send(f"Deliver {IN_STOCK_QTY} to {AVAIL_AREA} on {AVAIL_DATE}?")
    assert PROCEED not in result["response"]
    # And rendering never created another order.
    assert "create_order" not in tools


# Positive control: persisted verification matches current SKU+qty across a
# delivery-only turn AND stock is sufficient -> prompt (already covered by
# the multi-turn test, but assert the readiness helper directly too).
def test_inventory_ready_helper_binds_to_current_sku_and_qty(monkeypatch):
    script = [
        [("check_inventory", {"sku": SKU, "requested_quantity": IN_STOCK_QTY})],
        "In stock.",
    ]
    agent, tools = build_agent(monkeypatch, script)
    agent.enquiry.product_sku = SKU
    agent.enquiry.quantity = IN_STOCK_QTY
    agent.send("Stock check")
    assert agent.enquiry.inventory_ready_for(SKU, IN_STOCK_QTY) is True
    # Mismatched quantity / SKU -> not ready.
    assert agent.enquiry.inventory_ready_for(SKU, IN_STOCK_QTY + 1) is False
    assert agent.enquiry.inventory_ready_for("ADP-120", IN_STOCK_QTY) is False
