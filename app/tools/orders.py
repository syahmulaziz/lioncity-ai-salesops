from app.database import get_connection


def get_previous_orders(customer_id: str, limit: int = 5):
    """
    Retrieve a customer's most recent completed orders,
    including their line items.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            order_id,
            order_date,
            delivery_area,
            status
        FROM orders
        WHERE customer_id = ?
          AND status = 'COMPLETED'
        ORDER BY order_date DESC
        LIMIT ?
    """, (customer_id, limit))

    order_rows = cursor.fetchall()

    if not order_rows:
        connection.close()

        return {
            "success": True,
            "customer_id": customer_id,
            "orders": []
        }

    orders = []

    for order in order_rows:

        cursor.execute("""
            SELECT
                order_items.sku,
                products.product_name,
                order_items.quantity,
                order_items.unit_price
            FROM order_items
            JOIN products
                ON order_items.sku = products.sku
            WHERE order_items.order_id = ?
            ORDER BY order_items.order_item_id
        """, (order["order_id"],))

        item_rows = cursor.fetchall()

        items = []

        for item in item_rows:
            items.append({
                "sku": item["sku"],
                "product_name": item["product_name"],
                "quantity": item["quantity"],
                "unit_price": item["unit_price"]
            })

        orders.append({
            "order_id": order["order_id"],
            "order_date": order["order_date"],
            "delivery_area": order["delivery_area"],
            "status": order["status"],
            "items": items
        })

    connection.close()

    return {
        "success": True,
        "customer_id": customer_id,
        "orders": orders
    }