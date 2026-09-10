from datetime import datetime


def create_order(
    customer_id: str,
    items: list,
    product_subtotal: float,
    discount_percent: float,
    delivery_fee: float,
    final_total: float,
    delivery_area: str,
    delivery_date: str
):
    """
    Create a prototype LionCity sales order.

    For the internal prototype this does not write to an ERP.
    It returns a controlled mock order confirmation.
    """

    timestamp = datetime.now().strftime("%H%M%S")

    order_id = f"SO-DEMO-{timestamp}"

    return {
        "success": True,
        "order_id": order_id,
        "customer_id": customer_id,
        "items": items,
        "product_subtotal": product_subtotal,
        "discount_percent": discount_percent,
        "delivery_fee": delivery_fee,
        "final_total": final_total,
        "delivery_area": delivery_area,
        "delivery_date": delivery_date,
        "status": "CONFIRMED"
    }