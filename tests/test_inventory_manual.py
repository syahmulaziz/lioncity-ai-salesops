from app.tools.inventory import check_inventory


print("\nTEST 1 - Enough stock")
result = check_inventory("CBL-210", 300)
print(result)


print("\nTEST 2 - Not enough stock")
result = check_inventory("CBL-210", 500)
print(result)


print("\nTEST 3 - Product does not exist")
result = check_inventory("ABC-999", 20)
print(result)