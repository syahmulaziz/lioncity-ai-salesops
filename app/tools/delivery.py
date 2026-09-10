from app.database import get_connection


def check_delivery(
    delivery_area: str,
    delivery_date: str
):
    """
    Check whether delivery is available for
    a particular area and date.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            delivery_area,
            delivery_date,
            delivery_fee,
            remaining_capacity
        FROM delivery_slots
        WHERE delivery_area = ?
          AND delivery_date = ?
    """, (delivery_area, delivery_date))

    slot = cursor.fetchone()

    connection.close()

    if slot is None:
        return {
            "success": True,
            "delivery_area": delivery_area,
            "delivery_date": delivery_date,
            "available": False,
            "reason": "NO_DELIVERY_SLOT"
        }

    remaining_capacity = slot["remaining_capacity"]

    return {
        "success": True,
        "delivery_area": slot["delivery_area"],
        "delivery_date": slot["delivery_date"],
        "available": remaining_capacity > 0,
        "delivery_fee": slot["delivery_fee"],
        "remaining_capacity": remaining_capacity
    }