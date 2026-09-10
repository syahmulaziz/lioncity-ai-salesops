from pprint import pprint

from app.tools.delivery import check_delivery


print("\nTEST 1 - Jurong available")
pprint(
    check_delivery(
        "Jurong",
        "2026-09-15"
    )
)


print("\nTEST 2 - Jurong full")
pprint(
    check_delivery(
        "Jurong",
        "2026-09-16"
    )
)


print("\nTEST 3 - Woodlands available")
pprint(
    check_delivery(
        "Woodlands",
        "2026-09-15"
    )
)


print("\nTEST 4 - No delivery slot")
pprint(
    check_delivery(
        "Jurong",
        "2026-09-17"
    )
)