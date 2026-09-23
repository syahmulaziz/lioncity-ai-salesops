from app.database import (
    get_connection,
    get_latest_sales_state,
)


def test_confirmed_order_clears_current_quote():
    """
    SCRUM-30:
    Once an order is confirmed, it is no longer
    an active quote in the Sales Console.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO sales_events (
            event_type,
            customer_id,
            amount,
            details
        )
        VALUES (?, ?, ?, ?)
    """, (
        "ORDER_CONFIRMED",
        "SCRUM30-TEST",
        105.00,
        "SO-SCRUM30-TEST",
    ))

    connection.commit()
    connection.close()

    state = get_latest_sales_state()

    assert state["status"] == "ORDER_CONFIRMED"
    assert state["quote_amount"] is None