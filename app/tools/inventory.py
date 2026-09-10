from app.database import get_connection


def check_inventory(sku: str, requested_quantity: int):
    """
    Check whether LionCity has enough stock to fulfil
    the requested quantity of a product.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            products.sku,
            products.product_name,
            inventory.available_quantity
        FROM products
        JOIN inventory
            ON products.sku = inventory.sku
        WHERE products.sku = ?
    """, (sku,))

    product = cursor.fetchone()

    connection.close()

    if product is None:
        return {
            "success": False,
            "error": "PRODUCT_NOT_FOUND",
            "sku": sku
        }

    available_quantity = product["available_quantity"]

    return {
        "success": True,
        "sku": product["sku"],
        "product_name": product["product_name"],
        "requested_quantity": requested_quantity,
        "available_quantity": available_quantity,
        "can_fulfil": available_quantity >= requested_quantity
    }