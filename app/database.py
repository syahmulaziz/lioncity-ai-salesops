import sqlite3
from pathlib import Path


# Find the root folder of our project
BASE_DIR = Path(__file__).resolve().parent.parent

# Our SQLite database will live inside /data
DB_PATH = BASE_DIR / "data" / "lioncity.db"


def get_connection():
    """
    Create and return a connection to the LionCity database.
    """
    connection = sqlite3.connect(DB_PATH)

    # This allows us to access columns by name later.
    connection.row_factory = sqlite3.Row

    return connection

def create_tables():
    """
    Create the database tables required by LionCity.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            customer_id TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            contact_name TEXT NOT NULL,
            phone TEXT NOT NULL UNIQUE,
            account_tier TEXT NOT NULL,
            delivery_area TEXT,
            assigned_sales_rep TEXT
        )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        customer_id TEXT NOT NULL,
        order_date TEXT NOT NULL,
        delivery_area TEXT,
        status TEXT NOT NULL,
        FOREIGN KEY (customer_id)
            REFERENCES customers(customer_id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS order_items (
        order_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT NOT NULL,
        sku TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL,
        FOREIGN KEY (order_id)
            REFERENCES orders(order_id),
        FOREIGN KEY (sku)
            REFERENCES products(sku),
        UNIQUE (order_id, sku)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS customer_prices (
        customer_id TEXT NOT NULL,
        sku TEXT NOT NULL,
        unit_price REAL NOT NULL,
        PRIMARY KEY (customer_id, sku),
        FOREIGN KEY (customer_id)
            REFERENCES customers(customer_id),
        FOREIGN KEY (sku)
            REFERENCES products(sku)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS delivery_slots (
        delivery_area TEXT NOT NULL,
        delivery_date TEXT NOT NULL,
        delivery_fee REAL NOT NULL,
        remaining_capacity INTEGER NOT NULL,
        PRIMARY KEY (delivery_area, delivery_date)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS approval_requests (
        approval_id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT NOT NULL,
        approval_type TEXT NOT NULL,
        requested_percent REAL NOT NULL,
        approved_percent REAL,
        status TEXT NOT NULL DEFAULT 'PENDING',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
""")

    connection.commit()
    connection.close()

def seed_customers():
    """
    Insert sample LionCity customers for our prototype.
    """

    connection = get_connection()
    cursor = connection.cursor()

    customers = [
        (
            "CUST-001",
            "Apex Engineering Pte Ltd",
            "Syahmul Aziz",
            "+6581658457",
            "GOLD",
            "Jurong",
            "Marcus"
        ),
        (
            "CUST-002",
            "BrightWorks Services Pte Ltd",
            "Daniel Lim",
            "+6591112222",
            "STANDARD",
            "Woodlands",
            "Sarah"
        )
    ]

    cursor.executemany("""
        INSERT OR IGNORE INTO customers (
            customer_id,
            company_name,
            contact_name,
            phone,
            account_tier,
            delivery_area,
            assigned_sales_rep
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, customers)

    connection.commit()
    connection.close()

def show_customers():
    """
    Display all customers currently stored in the database.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("SELECT * FROM customers")

    customers = cursor.fetchall()

    for customer in customers:
        print(
            customer["customer_id"],
            customer["company_name"],
            customer["contact_name"],
            customer["phone"],
            customer["account_tier"],
            customer["delivery_area"],
            customer["assigned_sales_rep"]
        )
    connection.close()

def seed_products():
    """
    Insert sample LionCity products.
    """

    connection = get_connection()
    cursor = connection.cursor()

    products = [
        (
            "CBL-210",
            "Industrial Cable",
            "Heavy-duty industrial electrical cable",
            "Electrical",
            12.00
        ),
        (
            "ADP-120",
            "Industrial Adapter",
            "Industrial power adapter",
            "Electrical",
            18.00
        ),
        (
            "TIE-100",
            "Heavy Duty Cable Tie",
            "Heavy-duty cable ties for industrial use",
            "Accessories",
            2.00
        )
    ]

    cursor.executemany("""
        INSERT OR IGNORE INTO products (
            sku,
            product_name,
            description,
            category,
            list_price
        )
        VALUES (?, ?, ?, ?, ?)
    """, products)

    connection.commit()
    connection.close()

def seed_inventory():
    """
    Insert sample stock quantities.
    """

    connection = get_connection()
    cursor = connection.cursor()

    inventory = [
        ("CBL-210", 486),
        ("ADP-120", 121),
        ("TIE-100", 670)
    ]

    cursor.executemany("""
        INSERT OR IGNORE INTO inventory (
            sku,
            available_quantity
        )
        VALUES (?, ?)
    """, inventory)

    connection.commit()
    connection.close()

def show_products_with_inventory():
    """
    Display products together with their current inventory.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            products.sku,
            products.product_name,
            products.list_price,
            inventory.available_quantity
        FROM products
        JOIN inventory
            ON products.sku = inventory.sku
    """)

    products = cursor.fetchall()

    for product in products:
        print(
            product["sku"],
            "|",
            product["product_name"],
            "| Price: $",
            product["list_price"],
            "| Stock:",
            product["available_quantity"]
        )

    connection.close()

def seed_orders():
    """
    Insert sample historical orders.
    """

    connection = get_connection()
    cursor = connection.cursor()

    orders = [
        (
            "SO-2026-1731",
            "CUST-001",
            "2026-08-18",
            "Jurong",
            "COMPLETED"
        ),
        (
            "SO-2026-1602",
            "CUST-001",
            "2026-07-10",
            "Jurong",
            "COMPLETED"
        ),
        (
            "SO-2026-1710",
            "CUST-002",
            "2026-08-12",
            "Woodlands",
            "COMPLETED"
        )
    ]

    cursor.executemany("""
        INSERT OR IGNORE INTO orders (
            order_id,
            customer_id,
            order_date,
            delivery_area,
            status
        )
        VALUES (?, ?, ?, ?, ?)
    """, orders)

    connection.commit()
    connection.close()

def seed_order_items():
    """
    Insert line items belonging to historical orders.
    """

    connection = get_connection()
    cursor = connection.cursor()

    order_items = [
        # Apex Engineering - August order
        (
            "SO-2026-1731",
            "CBL-210",
            200,
            12.00
        ),
        (
            "SO-2026-1731",
            "ADP-120",
            50,
            18.00
        ),
        (
            "SO-2026-1731",
            "TIE-100",
            100,
            2.00
        ),

        # Apex Engineering - July order
        (
            "SO-2026-1602",
            "CBL-210",
            100,
            12.50
        ),
        (
            "SO-2026-1602",
            "TIE-100",
            50,
            2.00
        ),

        # BrightWorks - August order
        (
            "SO-2026-1710",
            "ADP-120",
            20,
            18.50
        )
    ]

    cursor.executemany("""
        INSERT OR IGNORE INTO order_items (
            order_id,
            sku,
            quantity,
            unit_price
        )
        VALUES (?, ?, ?, ?)
    """, order_items)

    connection.commit()
    connection.close()

def seed_customer_prices():
    """
    Insert customer-specific contracted prices.
    """

    connection = get_connection()
    cursor = connection.cursor()

    customer_prices = [
        ("CUST-001", "CBL-210", 12.00),
        ("CUST-001", "ADP-120", 18.00),
        ("CUST-001", "TIE-100", 2.00),

        ("CUST-002", "ADP-120", 18.50)
    ]

    cursor.executemany("""
        INSERT OR IGNORE INTO customer_prices (
            customer_id,
            sku,
            unit_price
        )
        VALUES (?, ?, ?)
    """, customer_prices)

    connection.commit()
    connection.close()

def seed_delivery_slots():
    """
    Insert sample delivery availability.
    """

    connection = get_connection()
    cursor = connection.cursor()

    delivery_slots = [
        (
            "Jurong",
            "2026-09-15",
            35.00,
            4
        ),
        (
            "Jurong",
            "2026-09-16",
            35.00,
            0
        ),
        (
            "Woodlands",
            "2026-09-15",
            40.00,
            2
        )
    ]

    cursor.executemany("""
        INSERT OR IGNORE INTO delivery_slots (
            delivery_area,
            delivery_date,
            delivery_fee,
            remaining_capacity
        )
        VALUES (?, ?, ?, ?)
    """, delivery_slots)

    connection.commit()
    connection.close()

def get_table_data(table_name: str):
    """
    Return all rows from an approved LionCity table.
    Used by the Business Data admin screen.
    """

    allowed_tables = {
        "customers",
        "products",
        "inventory",
        "orders",
        "order_items",
        "customer_prices",
        "delivery_slots"
    }

    if table_name not in allowed_tables:
        raise ValueError(
            f"Table not allowed: {table_name}"
        )

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        f"SELECT * FROM {table_name}"
    )

    rows = cursor.fetchall()

    connection.close()

    return [
        dict(row)
        for row in rows
    ]

def update_inventory(
    sku: str,
    available_quantity: int
):
    """
    Update available inventory for a product.
    """

    if available_quantity < 0:
        return {
            "success": False,
            "error": "INVALID_QUANTITY"
        }

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE inventory
        SET available_quantity = ?
        WHERE sku = ?
    """, (
        available_quantity,
        sku
    ))

    connection.commit()

    updated_rows = cursor.rowcount

    connection.close()

    if updated_rows == 0:
        return {
            "success": False,
            "error": "SKU_NOT_FOUND",
            "sku": sku
        }

    return {
        "success": True,
        "sku": sku,
        "available_quantity":
            available_quantity
    }

def update_delivery_capacity(
    delivery_area: str,
    delivery_date: str,
    remaining_capacity: int
):
    """
    Update delivery capacity for an existing slot.
    """

    if remaining_capacity < 0:
        return {
            "success": False,
            "error": "INVALID_CAPACITY"
        }

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE delivery_slots
        SET remaining_capacity = ?
        WHERE delivery_area = ?
          AND delivery_date = ?
    """, (
        remaining_capacity,
        delivery_area,
        delivery_date
    ))

    connection.commit()

    updated_rows = cursor.rowcount

    connection.close()

    if updated_rows == 0:
        return {
            "success": False,
            "error": "DELIVERY_SLOT_NOT_FOUND"
        }

    return {
        "success": True,
        "delivery_area": delivery_area,
        "delivery_date": delivery_date,
        "remaining_capacity":
            remaining_capacity
    }

def create_approval_request(
    phone: str,
    requested_percent: float
):
    connection = get_connection()
    cursor = connection.cursor()

    # Avoid duplicate pending requests.
    cursor.execute("""
        SELECT approval_id
        FROM approval_requests
        WHERE phone = ?
          AND status = 'PENDING'
        ORDER BY approval_id DESC
        LIMIT 1
    """, (phone,))

    existing = cursor.fetchone()

    if existing is not None:
        connection.close()

        return {
            "success": True,
            "approval_id": existing["approval_id"],
            "already_exists": True
        }

    cursor.execute("""
        INSERT INTO approval_requests (
            phone,
            approval_type,
            requested_percent,
            status
        )
        VALUES (?, 'DISCOUNT', ?, 'PENDING')
    """, (
        phone,
        requested_percent
    ))

    approval_id = cursor.lastrowid

    connection.commit()
    connection.close()

    return {
        "success": True,
        "approval_id": approval_id,
        "already_exists": False
    }


def get_pending_approvals():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT *
        FROM approval_requests
        WHERE status = 'PENDING'
        ORDER BY created_at ASC
    """)

    rows = cursor.fetchall()

    connection.close()

    return [dict(row) for row in rows]


def approve_request(
    approval_id: int,
    approved_percent: float
):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE approval_requests
        SET
            approved_percent = ?,
            status = 'APPROVED'
        WHERE approval_id = ?
          AND status = 'PENDING'
    """, (
        approved_percent,
        approval_id
    ))

    connection.commit()

    changed = cursor.rowcount

    connection.close()

    return {
        "success": changed == 1,
        "approval_id": approval_id,
        "approved_percent": approved_percent
    }


def get_approved_unprocessed_requests():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT *
        FROM approval_requests
        WHERE status = 'APPROVED'
        ORDER BY approval_id ASC
    """)

    rows = cursor.fetchall()

    connection.close()

    return [dict(row) for row in rows]


def mark_approval_processed(
    approval_id: int
):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE approval_requests
        SET status = 'PROCESSED'
        WHERE approval_id = ?
    """, (approval_id,))

    connection.commit()
    connection.close()

if __name__ == "__main__":
    print("Database location:", DB_PATH)

    create_tables()

    seed_customers()
    seed_products()
    seed_inventory()
    seed_orders()
    seed_order_items()
    seed_customer_prices()
    seed_delivery_slots()

    print("\nCUSTOMERS")
    show_customers()

    print("\nPRODUCTS & INVENTORY")
    show_products_with_inventory