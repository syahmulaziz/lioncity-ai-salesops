from app.database import get_connection
from app.tools.order_creation import create_order


TEST_SKU = "CBL-210"


def _get_stock():
    connection = get_connection()
    cursor = connection.cursor()

    row = cursor.execute(
        """
        SELECT available_quantity
        FROM inventory
        WHERE sku = ?
        """,
        (TEST_SKU,),
    ).fetchone()

    connection.close()

    return row["available_quantity"]


def test_order_creation_deducts_inventory():
    connection = get_connection()
    cursor = connection.cursor()

    original_stock = _get_stock()

    # Make sure this test has known stock.
    cursor.execute(
        """
        UPDATE inventory
        SET available_quantity = 800
        WHERE sku = ?
        """,
        (TEST_SKU,),
    )
    connection.commit()
    connection.close()

    try:
        result = create_order(
            customer_id="CUST-001",
            items=[
                {
                    "sku": TEST_SKU,
                    "quantity": 600,
                    "unit_price": 12.0,
                }
            ],
            product_subtotal=7200.0,
            discount_percent=0.0,
            delivery_fee=35.0,
            final_total=7235.0,
            delivery_area="Tengah",
            delivery_date="2026-09-23",
        )

        assert result["success"] is True
        assert _get_stock() == 200

    finally:
        # Restore local test data.
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE inventory
            SET available_quantity = ?
            WHERE sku = ?
            """,
            (original_stock, TEST_SKU),
        )

        connection.commit()
        connection.close()


def test_insufficient_inventory_rolls_back_order():
    connection = get_connection()
    cursor = connection.cursor()

    original_stock = _get_stock()

    cursor.execute(
        """
        UPDATE inventory
        SET available_quantity = 500
        WHERE sku = ?
        """,
        (TEST_SKU,),
    )

    connection.commit()
    connection.close()

    try:
        result = create_order(
            customer_id="CUST-001",
            items=[
                {
                    "sku": TEST_SKU,
                    "quantity": 600,
                    "unit_price": 12.0,
                }
            ],
            product_subtotal=7200.0,
            discount_percent=0.0,
            delivery_fee=35.0,
            final_total=7235.0,
            delivery_area="Tengah",
            delivery_date="2026-09-23",
        )

        assert result["success"] is False
        assert result["error"] == "ORDER_CREATION_FAILED"

        # Failed order must not consume stock.
        assert _get_stock() == 500

    finally:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE inventory
            SET available_quantity = ?
            WHERE sku = ?
            """,
            (original_stock, TEST_SKU),
        )

        connection.commit()
        connection.close()
