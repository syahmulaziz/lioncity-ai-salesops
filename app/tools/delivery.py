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

def get_next_available_delivery_slot(
    delivery_area: str,
    after_date: str
):
    """
    Return the earliest available delivery slot for an area
    strictly after the supplied date.

    The result is sourced directly from delivery_slots.
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
          AND delivery_date > ?
          AND remaining_capacity > 0
        ORDER BY delivery_date ASC
        LIMIT 1
    """, (
        delivery_area,
        after_date,
    ))

    slot = cursor.fetchone()

    connection.close()

    if slot is None:
        return {
            "success": True,
            "delivery_area": delivery_area,
            "after_date": after_date,
            "available": False,
            "reason": "NO_FUTURE_DELIVERY_SLOT",
        }

    return {
        "success": True,
        "delivery_area": slot["delivery_area"],
        "delivery_date": slot["delivery_date"],
        "available": True,
        "delivery_fee": slot["delivery_fee"],
        "remaining_capacity": slot["remaining_capacity"],
    }