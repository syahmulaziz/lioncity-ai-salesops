from pprint import pprint

from app.database import (
    create_approval_request,
    approve_request,
    get_connection,
)


PHONE = "+6581658457"


def show_all():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT *
        FROM approval_requests
        ORDER BY approval_id
    """)

    rows = cursor.fetchall()

    connection.close()

    pprint([
        dict(row)
        for row in rows
    ])


print("\n" + "=" * 60)
print("TEST 1 - CREATE FIRST APPROVAL")
print("=" * 60)

first = create_approval_request(
    phone=PHONE,
    requested_percent=10,
)

pprint(first)


print("\n" + "=" * 60)
print("TEST 2 - DUPLICATE WHILE PENDING")
print("=" * 60)

second = create_approval_request(
    phone=PHONE,
    requested_percent=10,
)

pprint(second)


print("\n" + "=" * 60)
print("TEST 3 - HUMAN APPROVES FIRST REQUEST")
print("=" * 60)

approved = approve_request(
    approval_id=first["approval_id"],
    approved_percent=7,
)

pprint(approved)


print("\n" + "=" * 60)
print("TEST 4 - DUPLICATE WHILE APPROVED")
print("=" * 60)

third = create_approval_request(
    phone=PHONE,
    requested_percent=10,
)

pprint(third)


print("\n" + "=" * 60)
print("FINAL DATABASE STATE")
print("=" * 60)

show_all()