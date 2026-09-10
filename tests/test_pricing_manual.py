from pprint import pprint

from app.tools.pricing import get_customer_price


print("\nTEST 1 - Apex contracted price")
pprint(
    get_customer_price(
        "CUST-001",
        "CBL-210",
        300
    )
)


print("\nTEST 2 - BrightWorks contracted price")
pprint(
    get_customer_price(
        "CUST-002",
        "ADP-120",
        20
    )
)


print("\nTEST 3 - Customer without special price")
pprint(
    get_customer_price(
        "CUST-002",
        "TIE-100",
        100
    )
)


print("\nTEST 4 - Unknown product")
pprint(
    get_customer_price(
        "CUST-001",
        "ABC-999",
        20
    )
)