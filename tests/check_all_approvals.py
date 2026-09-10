from pprint import pprint

from app.database import get_connection


connection = get_connection()
cursor = connection.cursor()

cursor.execute("""
    SELECT *
    FROM approval_requests
    ORDER BY approval_id
""")

rows = cursor.fetchall()

connection.close()

print("\nALL APPROVAL REQUESTS")

pprint([
    dict(row)
    for row in rows
])