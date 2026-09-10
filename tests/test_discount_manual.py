from pprint import pprint

from app.tools.discount import check_discount_authority


print("\nTEST 1 - 3%")
pprint(
    check_discount_authority(3)
)


print("\nTEST 2 - 5%")
pprint(
    check_discount_authority(5)
)


print("\nTEST 3 - 10%")
pprint(
    check_discount_authority(10)
)