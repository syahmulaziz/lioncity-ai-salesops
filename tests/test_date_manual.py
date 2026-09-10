from pprint import pprint

from app.tools.date_tools import resolve_date


print("\nTEST 1 - Next Tuesday")
pprint(
    resolve_date(
        "Tuesday",
        "2026-09-10"
    )
)


print("\nTEST 2 - Next Friday")
pprint(
    resolve_date(
        "Friday",
        "2026-09-10"
    )
)


print("\nTEST 3 - Same weekday")
pprint(
    resolve_date(
        "Thursday",
        "2026-09-10"
    )
)