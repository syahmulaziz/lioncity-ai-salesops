from pprint import pprint

from app.tools.orders import get_previous_orders


print("\nTEST 1 - Apex Engineering")
result = get_previous_orders("CUST-001")
pprint(result)


print("\nTEST 2 - BrightWorks Services")
result = get_previous_orders("CUST-002")
pprint(result)


print("\nTEST 3 - Customer with no history")
result = get_previous_orders("CUST-999")
pprint(result)