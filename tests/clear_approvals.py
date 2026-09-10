from app.database import get_connection


connection = get_connection()
cursor = connection.cursor()

cursor.execute(
    "DELETE FROM approval_requests"
)

connection.commit()
connection.close()

print("Approval queue cleared.")