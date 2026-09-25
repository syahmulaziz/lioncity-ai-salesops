import app.agent as agent_module
from app.enquiry_state import EnquiryState


TEST_PHONE = "+6599994047"


def _build_agent():
    """
    Minimal SalesAgent for deterministic commercial-rendering tests.

    We bypass __init__ so no Claude/API client is required.
    """
    agent = object.__new__(agent_module.SalesAgent)

    agent.phone = TEST_PHONE
    agent.messages = []
    agent.activity_log = []
    agent.enquiry = EnquiryState()

    agent.pending_approval = None
    agent.pending_commercial_order = None

    agent.approved_discount_percent = None
    agent.approved_commercial_discount_percent = None
    agent.approved_commercial_approval_id = None

    agent._suppress_order_completion_reset = False
    agent._resuming_approved_commercial_order = False

    agent._reset_response_grounding()

    return agent


def test_scrum43_multi_item_delivery_uses_whole_basket_subtotal():
    """
    SCRUM-43 regression.

    13 x TIE-100 @ S$2.00  = S$26.00
    59 x ADP-408 @ S$25.00 = S$1,475.00

    Whole basket subtotal = S$1,501.00.

    Delivery rendering must never display only the subtotal belonging
    to the last-priced item.
    """
    agent = _build_agent()

    # Reproduce the bug:
    # EnquiryState currently holds the latest individual pricing result.
    agent.enquiry.verified_subtotal = 1475.0

    agent._delivery_result_this_cycle = {
        "success": True,
        "available": True,
        "delivery_area": "Tengah",
        "delivery_date": "2026-09-26",
        "delivery_fee": 35.0,
        "delivery_fee_verified": True,
    }

    # Target trusted basket-level commercial snapshot.
    agent._commercial_summary_this_cycle = {
        "items": [
            {
                "sku": "TIE-100",
                "quantity": 13,
                "unit_price": 2.0,
                "line_total": 26.0,
            },
            {
                "sku": "ADP-408",
                "quantity": 59,
                "unit_price": 25.0,
                "line_total": 1475.0,
            },
        ],
        "product_subtotal": 1501.0,
        "discount_percent": 0.0,
        "discount_amount": 0.0,
        "discounted_subtotal": 1501.0,
        "delivery_fee": 35.0,
        "final_total": 1536.0,
    }

    rendered = agent._render_delivery_section()

    assert "S$1,501.00" in rendered

    # The last item's line subtotal must not be presented as the
    # basket-level product subtotal.
    assert "product subtotal is S$1,475.00" not in rendered.lower()


def test_scrum47_delivery_shows_approved_discount_and_final_total():
    """
    SCRUM-47 regression.

    Delivery confirmation after a human-approved discount must show
    the commercial amount the customer is actually being asked to
    accept, not merely the pre-discount product subtotal.
    """
    agent = _build_agent()

    agent.enquiry.verified_subtotal = 1800.0
    agent.approved_commercial_discount_percent = 8.0

    agent._delivery_result_this_cycle = {
        "success": True,
        "available": True,
        "delivery_area": "Tengah",
        "delivery_date": "2026-09-26",
        "delivery_fee": 30.0,
        "delivery_fee_verified": True,
    }

    agent._commercial_summary_this_cycle = {
        "items": [
            {
                "sku": "ADP-120",
                "quantity": 100,
                "unit_price": 18.0,
                "line_total": 1800.0,
            },
        ],
        "product_subtotal": 1800.0,
        "discount_percent": 8.0,
        "discount_amount": 144.0,
        "discounted_subtotal": 1656.0,
        "delivery_fee": 30.0,
        "final_total": 1686.0,
    }

    rendered = agent._render_delivery_section()

    assert "S$1,800.00" in rendered
    assert "8%" in rendered
    assert "S$144.00" in rendered
    assert "S$1,656.00" in rendered
    assert "S$30.00" in rendered
    assert "S$1,686.00" in rendered

    # Most important: the final amount being accepted must be explicit.
    assert "final total" in rendered.lower()


def test_scrum40_order_confirmation_has_standard_commercial_summary():
    """
    SCRUM-40 regression.

    A successful order confirmation should use one consistent,
    customer-friendly structure containing the complete commercial
    summary rather than a sparse mixture of fields.
    """
    agent = _build_agent()

    agent._order_result_this_cycle = {
        "success": True,
        "order_id": "SO-SCRUM40-001",
        "customer_id": "CUST-001",
        "status": "CONFIRMED",
        "items": [
            {
                "sku": "ADP-120",
                "quantity": 100,
                "unit_price": 18.0,
            },
        ],
        "product_subtotal": 1800.0,
        "discount_percent": 8.0,
        "delivery_fee": 30.0,
        "final_total": 1686.0,
        "delivery_area": "Tengah",
        "delivery_date": "2026-09-26",
    }

    rendered = agent._render_order_confirmation_section()

    assert "Order reference: SO-SCRUM40-001" in rendered

    # Item details.
    assert "ADP-120" in rendered
    assert "100" in rendered
    assert "S$18.00" in rendered

    # Complete pricing summary.
    assert "S$1,800.00" in rendered
    assert "8%" in rendered
    assert "S$144.00" in rendered
    assert "S$1,656.00" in rendered
    assert "S$30.00" in rendered
    assert "S$1,686.00" in rendered

    # Delivery details.
    assert "Tengah" in rendered
    assert "26-09-2026" in rendered

    # Standard confirmation must not contain stale handoff language.
    lower = rendered.lower()

    assert "sales representative" not in lower
    assert "finalize" not in lower
    assert "finalise" not in lower


def test_scrum40_confirmation_does_not_duplicate_delivery_section():
    """
    SCRUM-40 regression.

    When create_order and check_delivery trusted state coexist in the
    same response cycle, finalization must not render delivery twice.
    The authoritative order confirmation already contains delivery.
    """
    agent = _build_agent()

    agent._order_result_this_cycle = {
        "success": True,
        "order_id": "SO-SCRUM40-002",
        "customer_id": "CUST-001",
        "status": "CONFIRMED",
        "items": [
            {
                "sku": "CBL-210",
                "quantity": 10,
                "unit_price": 12.0,
            },
        ],
        "product_subtotal": 120.0,
        "discount_percent": 5.0,
        "delivery_fee": 35.0,
        "final_total": 149.0,
        "delivery_area": "Tengah",
        "delivery_date": "2026-09-24",
    }

    # Reproduce the screenshot where the finalizer had both an
    # order confirmation and delivery grounding available.
    agent._delivery_result_this_cycle = {
        "success": True,
        "available": True,
        "delivery_area": "Tengah",
        "delivery_date": "2026-09-24",
        "delivery_fee": 35.0,
        "delivery_fee_verified": True,
    }

    finalized = agent._finalize_customer_response([])

    assert "SO-SCRUM40-002" in finalized

    # Delivery should appear exactly once as part of the authoritative
    # confirmation, not once in confirmation + again as a delivery block.
    assert finalized.count("Tengah on 24-09-2026") == 1

    assert (
        finalized.count(
            "Delivery to Tengah on 24-09-2026 is available"
        )
        == 0
    )

def test_scrum43_successive_pricing_results_build_trusted_basket(
    monkeypatch,
):
    """
    SCRUM-43 root-cause regression.

    Multiple successful trusted pricing results in the same transaction
    must accumulate into one basket rather than the latest pricing result
    replacing the commercial subtotal used for customer rendering.
    """
    agent = _build_agent()

    pricing_results = {
        "TIE-100": {
            "success": True,
            "customer_id": "CUST-001",
            "sku": "TIE-100",
            "product_name": "Heavy Duty Cable Tie",
            "quantity": 13,
            "unit_price": 2.0,
            "price_source": "LIST_PRICE",
            "subtotal": 26.0,
        },
        "ADP-408": {
            "success": True,
            "customer_id": "CUST-001",
            "sku": "ADP-408",
            "product_name": "Hydraulic Adapter",
            "quantity": 59,
            "unit_price": 25.0,
            "price_source": "LIST_PRICE",
            "subtotal": 1475.0,
        },
    }

    monkeypatch.setattr(
        agent_module,
        "execute_tool",
        lambda tool_name, tool_input: (
            pricing_results[tool_input["sku"]]
            if tool_name == "get_customer_price"
            else {
                "success": False,
                "error": "UNEXPECTED_TOOL",
            }
        ),
    )

    first = agent._handle_tool(
        "get_customer_price",
        {
            "customer_id": "CUST-001",
            "sku": "TIE-100",
            "quantity": 13,
        },
    )

    second = agent._handle_tool(
        "get_customer_price",
        {
            "customer_id": "CUST-001",
            "sku": "ADP-408",
            "quantity": 59,
        },
    )

    assert first["success"] is True
    assert second["success"] is True

    summary = agent._build_commercial_summary()

    assert len(summary["items"]) == 2

    items = {
        item["sku"]: item
        for item in summary["items"]
    }

    assert items["TIE-100"]["quantity"] == 13
    assert items["TIE-100"]["unit_price"] == 2.0
    assert items["TIE-100"]["line_total"] == 26.0

    assert items["ADP-408"]["quantity"] == 59
    assert items["ADP-408"]["unit_price"] == 25.0
    assert items["ADP-408"]["line_total"] == 1475.0

    assert summary["product_subtotal"] == 1501.0


def test_scrum43_multi_item_summary_does_not_append_single_product_match():
    """
    SCRUM-43 AWS regression.

    When a transaction contains multiple priced items, the final
    customer response must not append a single-product catalogue
    message referring only to the last resolved product.

    Example bad response:
        Product subtotal: S$150.00
        ...
        That matches Industrial Adapter (ADP-120) in our catalogue.

    The basket summary is authoritative for this response.
    """
    agent = _build_agent()

    agent._commercial_summary_this_cycle = {
        "items": [
            {
                "sku": "CBL-210",
                "product_name": "Industrial Cable",
                "quantity": 5,
                "unit_price": 12.0,
                "line_total": 60.0,
            },
            {
                "sku": "ADP-120",
                "product_name": "Industrial Adapter",
                "quantity": 5,
                "unit_price": 18.0,
                "line_total": 90.0,
            },
        ],
        "product_subtotal": 150.0,
        "discount_percent": 0.0,
        "discount_amount": 0.0,
        "discounted_subtotal": 150.0,
        "delivery_fee": 30.0,
        "final_total": 180.0,
    }

    agent._delivery_result_this_cycle = {
        "success": True,
        "available": True,
        "delivery_area": "Tengah",
        "delivery_date": "2026-09-26",
        "delivery_fee": 30.0,
        "delivery_fee_verified": True,
    }

    # Reproduce AWS: find_product resolved the second product during
    # this same response cycle.
    agent._specific_product_result_this_cycle = {
        "sku": "ADP-120",
        "product_name": "Industrial Adapter",
    }

    finalized = agent._finalize_customer_response([])

    assert "S$150.00" in finalized
    assert "S$180.00" in finalized

    assert (
        "That matches Industrial Adapter "
        "(ADP-120) in our catalogue."
        not in finalized
    )

def test_scrum43_ready_multi_item_order_still_prompts_to_proceed():
    """
    SCRUM-43 AWS regression.

    A multi-item transaction with:
      - trusted priced basket,
      - verified available delivery,
      - sufficient verified stock,
      - no pending HITL

    must still ask the customer whether they want to proceed.

    Commercial-summary rendering must not accidentally suppress the
    normal customer-confirmation checkpoint.
    """
    agent = _build_agent()

    agent._commercial_summary_this_cycle = {
        "items": [
            {
                "sku": "CBL-210",
                "product_name": "Industrial Cable",
                "quantity": 5,
                "unit_price": 12.0,
                "line_total": 60.0,
            },
            {
                "sku": "ADP-120",
                "product_name": "Industrial Adapter",
                "quantity": 5,
                "unit_price": 18.0,
                "line_total": 90.0,
            },
        ],
        "product_subtotal": 150.0,
        "discount_percent": 0.0,
        "discount_amount": 0.0,
        "discounted_subtotal": 150.0,
        "delivery_fee": 30.0,
        "final_total": 180.0,
    }

    agent._delivery_result_this_cycle = {
        "success": True,
        "available": True,
        "delivery_area": "Tengah",
        "delivery_date": "2026-09-26",
        "delivery_fee": 30.0,
        "delivery_fee_verified": True,
    }

    # _render_proceed_prompt currently uses EnquiryState for its
    # minimum order prerequisites.
    agent.enquiry.product_sku = "ADP-120"
    agent.enquiry.quantity = 5

    # Give it the trusted inventory state it requires.
    agent.enquiry.verified_inventory_sku = "ADP-120"
    agent.enquiry.verified_inventory_quantity = 5
    agent.enquiry.verified_inventory_can_fulfil = True

    agent.pending_approval = None
    agent.pending_commercial_order = None

    finalized = agent._finalize_customer_response([])

    assert "S$150.00" in finalized
    assert "S$180.00" in finalized

    assert (
        "Would you like to proceed with the order?"
        in finalized
    )

def test_scrum47_pending_combined_commercial_hitl_suppresses_proceed_prompt():
    """
    SCRUM-47 AWS regression.

    If a combined COMMERCIAL_AUTHORITY approval is pending, the
    customer must NOT simultaneously be asked to proceed.

    Bad AWS behaviour:
        "I've sent the transaction for review..."
        ...
        "Would you like to proceed with the order?"

    Those instructions contradict each other.
    """
    agent = _build_agent()

    agent._commercial_summary_this_cycle = {
        "items": [
            {
                "sku": "TIE-100",
                "product_name": "Heavy Duty Cable Tie",
                "quantity": 100,
                "unit_price": 2.0,
                "line_total": 200.0,
            },
        ],
        "product_subtotal": 200.0,
        "discount_percent": 0.0,
        "discount_amount": 0.0,
        "discounted_subtotal": 200.0,
        "delivery_fee": 30.0,
        "final_total": 230.0,
    }

    agent._delivery_result_this_cycle = {
        "success": True,
        "available": True,
        "delivery_area": "Tengah",
        "delivery_date": "2026-09-26",
        "delivery_fee": 30.0,
        "delivery_fee_verified": True,
    }

    agent.enquiry.product_sku = "TIE-100"
    agent.enquiry.quantity = 100

    agent.enquiry.verified_inventory_sku = "TIE-100"
    agent.enquiry.verified_inventory_quantity = 100
    agent.enquiry.verified_inventory_can_fulfil = True

    # This is the important state from the AWS case:
    # a PRE-CONFIRMATION combined commercial HITL exists.
    agent._commercial_approval_this_cycle = {
        "requested_percent": 10.0,
        "reasons": [
            "EXCESSIVE_DISCOUNT",
        ],
    }

    # No legacy discount pending state and no post-confirmation
    # pending order exist in this scenario.
    agent.pending_approval = None
    agent.pending_commercial_order = None

    finalized = agent._finalize_customer_response([])

    assert "requires review" in finalized.lower()
    assert "10%" in finalized

    assert (
        "Would you like to proceed with the order?"
        not in finalized
    )

def test_scrum43_delivery_summary_shows_all_basket_line_items():
    """
    SCRUM-43 AWS regression.

    A multi-item delivery summary must show every priced basket
    line, not merely the aggregate subtotal and not merely the
    last product resolved by find_product.
    """
    agent = _build_agent()

    agent._commercial_summary_this_cycle = {
        "items": [
            {
                "sku": "CBL-210",
                "product_name": "Industrial Cable",
                "quantity": 5,
                "unit_price": 12.0,
                "line_total": 60.0,
            },
            {
                "sku": "ADP-120",
                "product_name": "Industrial Adapter",
                "quantity": 5,
                "unit_price": 18.0,
                "line_total": 90.0,
            },
        ],
        "product_subtotal": 150.0,
        "discount_percent": 0.0,
        "discount_amount": 0.0,
        "discounted_subtotal": 150.0,
        "delivery_fee": 30.0,
        "final_total": 180.0,
    }

    agent._delivery_result_this_cycle = {
        "success": True,
        "available": True,
        "delivery_area": "Tengah",
        "delivery_date": "2026-09-26",
        "delivery_fee": 30.0,
        "delivery_fee_verified": True,
    }

    rendered = agent._render_delivery_section()

    assert "CBL-210" in rendered
    assert "Industrial Cable" in rendered
    assert "5 x S$12.00 = S$60.00" in rendered

    assert "ADP-120" in rendered
    assert "Industrial Adapter" in rendered
    assert "5 x S$18.00 = S$90.00" in rendered

    assert "Product subtotal: S$150.00" in rendered
    assert "Delivery fee: S$30.00" in rendered
    assert "Final total: S$180.00" in rendered