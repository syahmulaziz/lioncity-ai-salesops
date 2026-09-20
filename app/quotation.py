"""
Customer-facing QUOTATION PREVIEW builder for LionCity.

WHY THIS MODULE EXISTS
----------------------
A quotation request should be answerable with a helpful, clearly-marked
PREVIEW - NOT a final, legally binding quotation. This module assembles that
preview from CURRENT, trusted enquiry state only.

TRUST RULES (enforced here)
---------------------------
- Reads only the validated/verified fields on EnquiryState. It never accepts
  numbers from customer/LLM text and never calculates a SKU, verified product
  name, unit price, subtotal, discount, or customer tier itself.
- Because it reads CURRENT state, it automatically respects the existing
  stale-data invalidation: if quantity or product changed, the old
  verified_subtotal was already cleared, so the preview cannot show a stale
  amount. This module keeps no cached copy of its own.
- Unit price is taken DIRECTLY from the trusted pricing result
  (EnquiryState.verified_unit_price). It is never reconstructed from
  subtotal / quantity. If it is not available it is shown as
  "To be confirmed" rather than invented.
- Discount / delivery are shown as "To be confirmed" here: this preview does
  not verify or apply them (discount authority remains owned by the existing
  discount HITL; delivery remains owned by check_delivery). Nothing is
  fabricated.
- The preview is always clearly marked as a non-final PREVIEW.

This is intentionally small: no official quotation/order-management subsystem.
"""

# WhatsApp-friendly "value unknown" marker.
TBC = "To be confirmed"


def build_quotation_preview(state):
    """
    Build a structured quotation-preview dict from CURRENT trusted state.

    Returns a dict with:
        {
          "success": True,
          "status": "PREVIEW",
          "is_final": False,
          "fields": { product, sku, quantity, unit_price, subtotal,
                      delivery, discount, estimated_total },
          "missing": [ ...field names that are unavailable... ],
          "disclaimer": <str>,
          "message": <WhatsApp-formatted preview text>,
        }

    Fields that are not backed by trusted data are set to the TBC marker and
    listed in "missing"; they are never invented.
    """
    product_name = state.product_name        # verified (B) or None
    sku = state.product_sku                   # verified (B) or None
    quantity = state.quantity                 # validated (A) or None
    subtotal = state.verified_subtotal        # verified (B) or None
    unit_price = state.verified_unit_price    # verified (B) or None

    missing = []

    product_display = product_name if product_name else TBC
    if not product_name:
        missing.append("product")
    sku_display = sku if sku else TBC
    if not sku:
        missing.append("sku")

    if isinstance(quantity, int) and not isinstance(quantity, bool):
        quantity_display = quantity
    else:
        quantity_display = TBC
        missing.append("quantity")

    # Subtotal comes only from a trusted verified_subtotal.
    if isinstance(subtotal, (int, float)) and not isinstance(subtotal, bool):
        subtotal_display = f"SGD {subtotal:.2f}"
        subtotal_value = float(subtotal)
    else:
        subtotal_display = TBC
        subtotal_value = None
        missing.append("subtotal")

    # Unit price is taken DIRECTLY from the trusted pricing result
    # (verified_unit_price). It is never reconstructed from subtotal/quantity.
    if isinstance(unit_price, (int, float)) and not isinstance(unit_price, bool):
        unit_price_display = f"SGD {unit_price:.2f}"
    else:
        unit_price_display = TBC
        missing.append("unit_price")

    # Delivery and discount are not verified/applied at preview time.
    delivery_display = TBC
    discount_display = TBC

    # Estimated total: for the preview we only safely surface the verified
    # subtotal as the basis. Delivery/discount are unconfirmed, so we present
    # the estimated total as the verified subtotal when available, otherwise
    # TBC. We never fabricate a total from unverified delivery/discount.
    if subtotal_value is not None:
        estimated_total_display = f"SGD {subtotal_value:.2f} (before any confirmed delivery/discount)"
    else:
        estimated_total_display = TBC
        missing.append("estimated_total")

    disclaimer = (
        "This is a preview only. Final pricing, delivery charges and any "
        "applicable discounts are subject to confirmation."
    )

    fields = {
        "product": product_display,
        "sku": sku_display,
        "quantity": quantity_display,
        "unit_price": unit_price_display,
        "subtotal": subtotal_display,
        "delivery": delivery_display,
        "discount": discount_display,
        "estimated_total": estimated_total_display,
    }

    message = _format_whatsapp(fields, disclaimer)

    return {
        "success": True,
        "status": "PREVIEW",
        "is_final": False,
        "fields": fields,
        "missing": missing,
        "disclaimer": disclaimer,
        "message": message,
    }


def _format_whatsapp(fields, disclaimer):
    """
    Format the preview for WhatsApp: short lines, no Markdown tables, sparing
    *bold* on the heading and status. Mobile-friendly.
    """
    lines = [
        "*Quotation Preview*",
        f"Product: {fields['product']}",
        f"SKU: {fields['sku']}",
        f"Quantity: {fields['quantity']}",
        f"Unit Price: {fields['unit_price']}",
        f"Subtotal: {fields['subtotal']}",
        f"Delivery: {fields['delivery']}",
        f"Discount: {fields['discount']}",
        f"Estimated Total: {fields['estimated_total']}",
        "Status: *PREVIEW* (not final)",
        "",
        disclaimer,
    ]
    return "\n".join(lines)


# Tool-facing entry point used by SalesAgent. Kept thin so the agent stays an
# orchestrator; all logic lives above.
def generate_quotation_preview(state):
    """Agent tool dispatch target. Builds the preview from current state."""
    return build_quotation_preview(state)
