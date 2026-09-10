from app.tools.customer import find_customer


print("\nTEST 1 - Apex Engineering")
print(find_customer("+6581658457"))


print("\nTEST 2 - BrightWorks Services")
print(find_customer("+6591112222"))


print("\nTEST 3 - Unknown customer")
print(find_customer("+6599999999"))