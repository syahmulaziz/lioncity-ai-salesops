from app.database import get_connection


def find_customer(phone: str):
    """
    Find a LionCity customer using their WhatsApp phone number.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            customer_id,
            company_name,
            contact_name,
            phone,
            account_tier,
            delivery_area,
            assigned_sales_rep
        FROM customers
        WHERE phone = ?
    """, (phone,))

    customer = cursor.fetchone()

    connection.close()

    if customer is None:
        return {
            "success": False,
            "error": "CUSTOMER_NOT_FOUND",
            "phone": phone
        }

    return {
        "success": True,
        "customer_id": customer["customer_id"],
        "company_name": customer["company_name"],
        "contact_name": customer["contact_name"],
        "phone": customer["phone"],
        "account_tier": customer["account_tier"],
        "delivery_area": customer["delivery_area"],
        "assigned_sales_rep": customer["assigned_sales_rep"]
    }