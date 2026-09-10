from app.database import get_connection


def get_customer_price(
    customer_id: str,
    sku: str,
    quantity: int
):
    """
    Return the currently approved price for a customer and product.
    """

    connection = get_connection()
    cursor = connection.cursor()

    # First check whether the product exists.
    cursor.execute("""
        SELECT
            sku,
            product_name,
            list_price
        FROM products
        WHERE sku = ?
    """, (sku,))

    product = cursor.fetchone()

    if product is None:
        connection.close()

        return {
            "success": False,
            "error": "PRODUCT_NOT_FOUND",
            "sku": sku
        }

    # Look for customer-specific contracted pricing.
    cursor.execute("""
        SELECT unit_price
        FROM customer_prices
        WHERE customer_id = ?
          AND sku = ?
    """, (customer_id, sku))

    customer_price = cursor.fetchone()

    if customer_price is not None:
        unit_price = customer_price["unit_price"]
        price_source = "CUSTOMER_CONTRACT"
    else:
        unit_price = product["list_price"]
        price_source = "LIST_PRICE"

    subtotal = unit_price * quantity

    connection.close()

    return {
        "success": True,
        "customer_id": customer_id,
        "sku": product["sku"],
        "product_name": product["product_name"],
        "quantity": quantity,
        "unit_price": unit_price,
        "price_source": price_source,
        "subtotal": subtotal
    }