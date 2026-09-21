from app.database import get_connection
from app.tools.order_creation import create_order


def _delete_test_orders():
    """
    Remove only orders created by these regression tests.
    """
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM order_items
        WHERE order_id IN (
            SELECT order_id
            FROM orders
            WHERE order_id LIKE 'SO-DEMO-%'
              AND customer_id = 'CUST-001'
        )
    """)

    cursor.execute("""
        DELETE FROM orders
        WHERE order_id LIKE 'SO-DEMO-%'
          AND customer_id = 'CUST-001'
    """)

    connection.commit()
    connection.close()


def test_create_order_persists_order_and_items():
    _delete_test_orders()

    result = create_order(
        customer_id="CUST-001",
        items=[
            {
                "sku": "CBL-210",
                "quantity": 1,
                "unit_price": 12.0,
            }
        ],
        product_subtotal=12.0,
        discount_percent=0,
        delivery_fee=35.0,
        final_total=47.0,
        delivery_area="Jurong",
        delivery_date="2026-09-25",
    )

    assert result["success"] is True

    order_id = result["order_id"]

    connection = get_connection()

    order = connection.execute(
        """
        SELECT *
        FROM orders
        WHERE order_id = ?
        """,
        (order_id,),
    ).fetchone()

    item = connection.execute(
        """
        SELECT *
        FROM order_items
        WHERE order_id = ?
        """,
        (order_id,),
    ).fetchone()

    connection.close()

    assert order is not None
    assert order["customer_id"] == "CUST-001"
    assert order["status"] == "CONFIRMED"

    assert item is not None
    assert item["sku"] == "CBL-210"
    assert item["quantity"] == 1
    assert item["unit_price"] == 12.0

    _delete_test_orders()


def test_create_order_rolls_back_on_item_failure():
    _delete_test_orders()

    result = create_order(
        customer_id="CUST-001",
        items=[
            {
                "sku": "CBL-210",
                "quantity": 1,
                "unit_price": 12.0,
            },
            {
                "sku": "CBL-210",
                "quantity": 2,
                "unit_price": 12.0,
            },
        ],
        product_subtotal=36.0,
        discount_percent=0,
        delivery_fee=35.0,
        final_total=71.0,
        delivery_area="Jurong",
        delivery_date="2026-09-25",
    )

    assert result["success"] is False
    assert result["error"] == "ORDER_CREATION_FAILED"

    connection = get_connection()

    orders = connection.execute(
        """
        SELECT *
        FROM orders
        WHERE order_id LIKE 'SO-DEMO-%'
          AND customer_id = 'CUST-001'
        """
    ).fetchall()

    connection.close()

    assert orders == []
    