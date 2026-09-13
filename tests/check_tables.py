from app.database import get_connection


connection = get_connection()
cursor = connection.cursor()

cursor.execute("""
    SELECT name
    FROM sqlite_master
    WHERE type = 'table'
    ORDER BY name
""")

tables = cursor.fetchall()

connection.close()


print("\nDATABASE TABLES")

for table in tables:
    print(table["name"])