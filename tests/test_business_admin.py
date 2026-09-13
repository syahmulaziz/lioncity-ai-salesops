from pprint import pprint

from app.database import (
    add_customer,
    update_customer,
    remove_customer,
    add_delivery_slot,
    update_delivery_capacity,
    remove_delivery_slot,
)


print("\n" + "=" * 60)
print("CUSTOMER TEST 1 - ADD")
print("=" * 60)

pprint(
    add_customer(
        customer_id="CUST-TEST",
        company_name="Test Company Pte Ltd",
        contact_name="Test Customer",
        phone="+6599990000",
        account_tier="STANDARD",
        delivery_area="Tuas",
        assigned_sales_rep="Sarah",
    )
)


print("\n" + "=" * 60)
print("CUSTOMER TEST 2 - UPDATE")
print("=" * 60)

pprint(
    update_customer(
        customer_id="CUST-TEST",
        company_name="Updated Test Company Pte Ltd",
        contact_name="Test Customer",
        phone="+6599990000",
        account_tier="GOLD",
        delivery_area="Jurong",
        assigned_sales_rep="Marcus",
    )
)


print("\n" + "=" * 60)
print("CUSTOMER TEST 3 - REMOVE")
print("=" * 60)

pprint(
    remove_customer(
        "CUST-TEST"
    )
)


print("\n" + "=" * 60)
print("DELIVERY TEST 1 - ADD")
print("=" * 60)

pprint(
    add_delivery_slot(
        delivery_area="Tuas",
        delivery_date="2026-09-20",
        delivery_fee=45.0,
        remaining_capacity=3,
    )
)


print("\n" + "=" * 60)
print("DELIVERY TEST 2 - UPDATE")
print("=" * 60)

pprint(
    update_delivery_capacity(
        "Tuas",
        "2026-09-20",
        5,
    )
)


print("\n" + "=" * 60)
print("DELIVERY TEST 3 - REMOVE")
print("=" * 60)

pprint(
    remove_delivery_slot(
        "Tuas",
        "2026-09-20",
    )
)