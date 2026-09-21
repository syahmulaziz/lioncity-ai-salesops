from datetime import datetime
from app.database import get_connection, log_sales_event


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
    Create and persist a confirmed LionCity sales order.

    The order and its line items are written to the local
    LionCity database before success is returned.
    """

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")

    order_id = f"SO-DEMO-{timestamp}"

    connection = get_connection()
    cursor = connection.cursor()

    try:
        # Persist the confirmed order first.
        cursor.execute("""
            INSERT INTO orders (
                order_id,
                customer_id,
                order_date,
                delivery_area,
                status
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            order_id,
            customer_id,
            datetime.now().strftime("%Y-%m-%d"),
            delivery_area,
            "CONFIRMED",
        ))

        # Persist every line item belonging to the order.
        for item in items:
            cursor.execute("""
                INSERT INTO order_items (
                    order_id,
                    sku,
                    quantity,
                    unit_price
                )
                VALUES (?, ?, ?, ?)
            """, (
                order_id,
                item["sku"],
                item["quantity"],
                item["unit_price"],
            ))

        # The order and all line items must succeed together.
        connection.commit()

    except Exception as error:
        connection.rollback()

        return {
            "success": False,
            "error": "ORDER_CREATION_FAILED",
            "message": str(error),
        }

    finally:
        connection.close()

    # Only log ORDER_CONFIRMED after the real order
    # has been successfully persisted.
    log_sales_event(
        event_type="ORDER_CONFIRMED",
        customer_id=customer_id,
        amount=final_total,
        details=order_id,
    )

    print(
        "SALES EVENT LOGGED: ORDER_CONFIRMED",
        order_id,
        final_total
    )

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