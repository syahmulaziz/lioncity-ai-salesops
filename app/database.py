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

    # HAFIZAH: ADD CREATE PRODUCT AND INVENTORY TABLE 
    # =====================================================
    # PRODUCTS
    # =====================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            sku TEXT PRIMARY KEY,
            product_name TEXT NOT NULL,
            description TEXT,
            category TEXT,
            list_price REAL NOT NULL) 
    """)

    # =====================================================
    # INVENTORY
    # =====================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            sku TEXT PRIMARY KEY,
            available_quantity INTEGER NOT NULL,
            FOREIGN KEY (sku)
                REFERENCES products(sku))
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

    # HAFIZAH: ADDED sku, requested_quantity, order_value and reason
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS approval_requests (
            approval_id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            approval_type TEXT NOT NULL,
            requested_percent REAL NOT NULL,
            approved_percent REAL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            sku TEXT,
            requested_quantity INTEGER,
            order_value REAL,
            reason TEXT,
            order_id TEXT
        )
    """)

    # HAFIZAH: UPGRADE EXISTING APPROVAL_REQUESTS TABLE
    # Existing deployments may already have approval_requests
    # without the commercial authority fields.
    cursor.execute("""
        PRAGMA table_info(approval_requests)
    """)

    existing_columns = {
        row["name"]
        for row in cursor.fetchall()
    }

    approval_columns = {
        "sku": "TEXT",
        "requested_quantity": "INTEGER",
        "order_value": "REAL",
        "reason": "TEXT",
        "order_id": "TEXT",
    }

    for column_name, column_type in approval_columns.items():
        if column_name not in existing_columns:
            cursor.execute(
                f"ALTER TABLE approval_requests "
                f"ADD COLUMN {column_name} {column_type}"
            )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_messages (
            message_id TEXT PRIMARY KEY,
            phone TEXT NOT NULL,
            processed_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            phone TEXT,
            customer_id TEXT,
            amount REAL,
            details TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # HAFIZAH: ADDED COMMERCIAL_POLICIES TABLE
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS commercial_policies (
            policy_key TEXT PRIMARY KEY,
            policy_value REAL NOT NULL,
            description TEXT)
    """) 

    connection.commit()
    connection.close()

# HAFIZAH: ADDED SEED_COMMERCIAL_POLICIES() AND GET_COMMERCIAL_POLICIES()
def seed_commercial_policies():
    """
    Insert default AI commercial authority limits

    Existing values are preserved so that settings changed
    through the admin dashboard are not overwritten.
    """

    connection = get_connection()
    cursor = connection.cursor()

    policies = [
        (
            "MAX_QUANTITY_PER_SKU",
            500,
            "Maximum quantity per SKU the AI can approve"
        ),(
            "MAX_ORDER_VALUE",
            10000,
            "Maximum order value the AI can approve without human approval"
        ),(
            "MAX_DISCOUNT_PERCENT",
            5,
            "Maximum discount percentage the AI can approve"
        )
    ]

    cursor.executemany("""
        INSERT OR IGNORE INTO commercial_policies(
            policy_key,
            policy_value,
            description)
        VALUES (?, ?, ?)
    """, policies)

    connection.commit()
    connection.close()

# HAFIZAH: ADDED GET_COMMERCIAL_POLICIES()
def get_commercial_policies():
    """
    Return all commercial policy settings.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT policy_key, policy_value, description
        FROM commercial_policies
        ORDER BY policy_key
    """)

    rows = cursor.fetchall()
    connection.close()

    return [dict(row) for row in rows]

# HAFIZAH: ADDED UPDATE_COMMERCIAL_POLICY()
def update_commercial_policy (policy_key: str, policy_value: float):
    """
    Update an existing commercial policy threshold
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE commercial_policies
        SET policy_value = ?
        WHERE policy_key = ?
    """, (policy_value, policy_key))

    if cursor.rowcount == 0:
        connection.close()

        return {
            "success": False,
            "error": "POLICY_NOT_FOUND",
            "policy_key": policy_key
        }

    connection.commit()
    connection.close()

    return {
        "success": True,
        "policy_key": policy_key,
        "policy_value": policy_value
    }



def seed_customers():
    """
    Insert sample LionCity customers for our prototype.
    """

    connection = get_connection()
    cursor = connection.cursor()

    customers = [
        (
            "CUST-001",
            "Cat King Pte Ltd",
            "Syahmul Aziz",
            "+6581658457",
            "GOLD",
            "Tuas",
            "Zoro"
        ),
        (
            "CUST-002",
            "Family First",
            "Dominic",
            "+6582094108",
            "STANDARD",
            "Chua Chu Kang",
            "Xiu Ming"
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

def add_product_with_inventory(
    sku: str,
    product_name: str,
    description: str,
    category: str,
    list_price: float,
    available_quantity: int,
):
    """
    Add a new product and its initial inventory
    as one database transaction.
    """

    sku = sku.strip().upper()
    product_name = product_name.strip()
    description = description.strip()
    category = category.strip()

    if not sku or not product_name:
        return {
            "success": False,
            "error": "SKU_AND_PRODUCT_NAME_REQUIRED",
        }

    if list_price < 0:
        return {
            "success": False,
            "error": "INVALID_LIST_PRICE",
        }

    if available_quantity < 0:
        return {
            "success": False,
            "error": "INVALID_QUANTITY",
        }

    connection = get_connection()
    cursor = connection.cursor()

    try:

        cursor.execute("""
            INSERT INTO products (
                sku,
                product_name,
                description,
                category,
                list_price
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            sku,
            product_name,
            description,
            category,
            list_price,
        ))

        cursor.execute("""
            INSERT INTO inventory (
                sku,
                available_quantity
            )
            VALUES (?, ?)
        """, (
            sku,
            available_quantity,
        ))

        connection.commit()

        return {
            "success": True,
            "sku": sku,
            "product_name": product_name,
            "available_quantity": available_quantity,
        }

    except sqlite3.IntegrityError:

        connection.rollback()

        return {
            "success": False,
            "error": "SKU_ALREADY_EXISTS",
            "sku": sku,
        }

    except Exception as error:

        connection.rollback()

        return {
            "success": False,
            "error": str(error),
        }

    finally:

        connection.close()

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

# HAFIZAH: REPLACED CREATE_APPROVAL_REQUEST TO
# SUPPORT SKU, REQUESTED_QUANTITY, ORDER_VALUE AND REASON
def create_approval_request(
    phone: str,
    requested_percent: float = 0,
    approval_type: str = "DISCOUNT",
    sku: str = None,
    requested_quantity: int = None,
    order_value: float = None,
    reason: str = None,
):
    """
    Create a human approval request.

    Supports discount approvals and commercial authority
    escalations such as high quantity and high order value.

    A customer may only have one unresolved approval
    request at a time.

    Unresolved statuses:
        PENDING
        APPROVED

    PROCESSED approvals are considered completed.
    """

    connection = get_connection()
    cursor = connection.cursor()

    # -------------------------------------------------
    # Check for an existing unresolved approval.
    # -------------------------------------------------

    cursor.execute("""
        SELECT
            approval_id,
            status,
            approval_type,
            requested_percent,
            approved_percent,
            sku,
            requested_quantity,
            order_value,
            reason
        FROM approval_requests
        WHERE phone = ?
          AND status IN ('PENDING', 'APPROVED')
        ORDER BY approval_id DESC
        LIMIT 1
    """, (
        phone,
    ))

    existing = cursor.fetchone()

    if existing is not None:

        result = {
            "success": True,
            "approval_id": existing["approval_id"],
            "already_exists": True,
            "status": existing["status"],
            "approval_type": existing["approval_type"],
            "requested_percent": existing["requested_percent"],
            "approved_percent": existing["approved_percent"],
            "sku": existing["sku"],
            "requested_quantity": existing["requested_quantity"],
            "order_value": existing["order_value"],
            "reason": existing["reason"],
        }

        connection.close()

        return result

    # -------------------------------------------------
    # No unresolved request exists.
    # Create a new one.
    # -------------------------------------------------

    cursor.execute("""
        INSERT INTO approval_requests (
            phone,
            approval_type,
            requested_percent,
            status,
            sku,
            requested_quantity,
            order_value,
            reason
        )
        VALUES (?, ?, ?, 'PENDING', ?, ?, ?, ?)
    """, (
        phone,
        approval_type,
        requested_percent,
        sku,
        requested_quantity,
        order_value,
        reason,
    ))

    approval_id = cursor.lastrowid

    connection.commit()
    connection.close()

    return {
        "success": True,
        "approval_id": approval_id,
        "already_exists": False,
        "status": "PENDING",
        "approval_type": approval_type,
        "requested_percent": requested_percent,
        "approved_percent": None,
        "sku": sku,
        "requested_quantity": requested_quantity,
        "order_value": order_value,
        "reason": reason,
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


# =========================================================
# DISCOUNT REJECTION (Feature A)
# =========================================================
#
# REJECT DISCOUNT is a SEPARATE, explicit human decision - it is NOT an
# approval of 0%. The status column is unconstrained TEXT, so the literal
# 'REJECTED' is storable with no schema migration.
#
# reject_request() mirrors approve_request(): a single atomic guarded
# UPDATE that only fires on a currently-PENDING row. This makes every
# unsafe transition fail safely with success=False (rowcount 0):
#   PENDING   -> REJECTED : allowed (rowcount 1)
#   REJECTED  -> REJECTED : refused (already resolved, not PENDING)
#   APPROVED  -> REJECTED : refused (completed decision preserved)
#   PROCESSED -> REJECTED : refused (completed decision preserved)
#   unknown id           : refused (no matching PENDING row)
# It never sets approved_percent (a rejection has no approved value) and
# never sets order_id (a rejection never creates an order), so a rejected
# row can never be mistaken for an approved 0% decision or a fulfilled
# commercial-authority order.
def reject_request(
    approval_id: int
):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE approval_requests
        SET status = 'REJECTED'
        WHERE approval_id = ?
          AND status = 'PENDING'
    """, (
        approval_id,
    ))

    connection.commit()

    changed = cursor.rowcount

    connection.close()

    return {
        "success": changed == 1,
        "approval_id": approval_id,
        "status": "REJECTED" if changed == 1 else None,
    }


def get_rejected_unprocessed_requests():
    """
    Return REJECTED-but-not-yet-processed decisions, oldest first, exactly
    mirroring get_approved_unprocessed_requests(). /process-approvals uses
    this to resume the customer's conversation with a trusted rejection.
    A row leaves this set once mark_approval_processed() advances it to
    PROCESSED, giving the same at-least-once idempotency as the approval
    path (no new machinery).
    """
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT *
        FROM approval_requests
        WHERE status = 'REJECTED'
        ORDER BY approval_id ASC
    """)

    rows = cursor.fetchall()

    connection.close()

    return [dict(row) for row in rows]

# HAFIZAH: FIND MATCHING COMMERCIAL AUTHORITY APPROVAL
def get_matching_commercial_approval(
    phone: str,
    sku: str,
    requested_quantity: int,
    order_value: float,
    discount_percent: float,
):
    """
    Return an approved commercial-authority request
    matching the proposed transaction.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT *
        FROM approval_requests
        WHERE phone = ?
          AND approval_type = 'COMMERCIAL_AUTHORITY'
          AND status = 'APPROVED'
          AND sku = ?
          AND requested_quantity = ?
          AND ABS(order_value - ?) < 0.01
          AND ABS(approved_percent - ?) < 0.01
        ORDER BY approval_id DESC
        LIMIT 1
    """, (
        phone,
        sku,
        requested_quantity,
        order_value,
        discount_percent,
    ))

    row = cursor.fetchone()
    connection.close()

    return dict(row) if row else None

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

def set_approval_order_id(
    approval_id: int,
    order_id: str
):
    """
    Associate a successfully persisted order with the
    commercial approval that authorised it.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE approval_requests
        SET order_id = ?
        WHERE approval_id = ?
    """, (
        order_id,
        approval_id,
    ))

    connection.commit()
    changed = cursor.rowcount
    connection.close()

    return {
        "success": changed == 1,
        "approval_id": approval_id,
        "order_id": order_id,
    }


def get_approval_by_id(
    approval_id: int
):
    """
    Retrieve one approval request by ID.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT *
        FROM approval_requests
        WHERE approval_id = ?
    """, (
        approval_id,
    ))

    row = cursor.fetchone()
    connection.close()

    return dict(row) if row else None

def reset_demo_data():
    """
    Restore mutable LionCity prototype data
    to the known hero-demo starting state.
    """

    connection = get_connection()
    cursor = connection.cursor()

    # -------------------------------------------------
    # Clear human approval workflow.
    # -------------------------------------------------

    cursor.execute("""
        DELETE FROM approval_requests
    """)

    # -------------------------------------------------
    # Restore hero-demo delivery capacity.
    # -------------------------------------------------

    delivery_values = [
        (4, "Jurong", "2026-09-15"),
        (0, "Jurong", "2026-09-16"),
        (2, "Woodlands", "2026-09-15"),
    ]

    cursor.executemany("""
        UPDATE delivery_slots
        SET remaining_capacity = ?
        WHERE delivery_area = ?
          AND delivery_date = ?
    """, delivery_values)

    cursor.execute("""
        DELETE FROM processed_messages
    """)

    cursor.execute("""
        DELETE FROM sales_events
    """)

    connection.commit()
    connection.close()

    return {
        "success": True,
        "message": "Demo data reset successfully."
    }

def is_message_processed(
    message_id: str
):
    """
    Check whether a WhatsApp message has already
    been processed by LionCity.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT message_id
        FROM processed_messages
        WHERE message_id = ?
    """, (
        message_id,
    ))

    row = cursor.fetchone()

    connection.close()

    return row is not None


def mark_message_processed(
    message_id: str,
    phone: str
):
    """
    Record a successfully processed WhatsApp message.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO processed_messages (
            message_id,
            phone
        )
        VALUES (?, ?)
    """, (
        message_id,
        phone,
    ))

    connection.commit()
    connection.close()

    return {
        "success": True,
        "message_id": message_id,
    }

def log_sales_event(
    event_type: str,
    phone: str = None,
    customer_id: str = None,
    amount: float = None,
    details: str = None
):
    """
    Record an observable SalesOps business event.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO sales_events (
            event_type,
            phone,
            customer_id,
            amount,
            details
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        event_type,
        phone,
        customer_id,
        amount,
        details,
    ))

    event_id = cursor.lastrowid

    connection.commit()
    connection.close()

    return {
        "success": True,
        "event_id": event_id,
        "event_type": event_type,
    }


def get_sales_events():
    """
    Return SalesOps events newest first.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT *
        FROM sales_events
        ORDER BY event_id DESC
    """)

    rows = cursor.fetchall()

    connection.close()

    return [
        dict(row)
        for row in rows
    ]

def get_sales_metrics():
    """
    Calculate live SalesOps metrics from persisted events.
    """

    connection = get_connection()
    cursor = connection.cursor()


    # ---------------------------------------------
    # SALES CONVERSATIONS
    # ---------------------------------------------

    cursor.execute("""
        SELECT COUNT(*)
        FROM sales_events
        WHERE event_type = 'CONVERSATION_STARTED'
    """)

    conversations = cursor.fetchone()[0]


    # ---------------------------------------------
    # CUSTOMER MESSAGES
    # ---------------------------------------------

    cursor.execute("""
        SELECT COUNT(*)
        FROM sales_events
        WHERE event_type = 'CUSTOMER_MESSAGE'
    """)

    customer_messages = cursor.fetchone()[0]


    # ---------------------------------------------
    # APPROVALS REQUIRED
    # ---------------------------------------------

    cursor.execute("""
        SELECT COUNT(*)
        FROM sales_events
        WHERE event_type = 'HUMAN_APPROVAL_REQUIRED'
    """)

    approvals_required = cursor.fetchone()[0]


    # ---------------------------------------------
    # SALESPERSON REQUESTED
    # ---------------------------------------------

    cursor.execute("""
        SELECT COUNT(*)
        FROM sales_events
        WHERE event_type = 'HUMAN_HANDOFF_REQUESTED'
    """)

    salesperson_requested = cursor.fetchone()[0]

    # ---------------------------------------------
    # CONFIRMED ORDERS
    # ---------------------------------------------

    cursor.execute("""
        SELECT COUNT(*)
        FROM sales_events
        WHERE event_type = 'ORDER_CONFIRMED'
    """)

    orders = cursor.fetchone()[0]


    # ---------------------------------------------
    # REVENUE
    # ---------------------------------------------

    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM sales_events
        WHERE event_type = 'ORDER_CONFIRMED'
    """)

    revenue = cursor.fetchone()[0]


    connection.close()


    return {
        "conversations": conversations,
        "customer_messages": customer_messages,
        "approvals_required": approvals_required,
        "salesperson_requested": salesperson_requested,
        "orders_confirmed": orders,
        "revenue": float(revenue),
    }

def get_latest_sales_state():
    """
    Derive the current sales state from persisted SalesOps
    events and approval records.

    Quote amounts are shown only when an authoritative
    persisted amount exists. No demo/default quote values
    are fabricated here.
    """

    connection = get_connection()
    cursor = connection.cursor()

    # -------------------------------------------------
    # Latest sales event
    # -------------------------------------------------

    cursor.execute("""
        SELECT *
        FROM sales_events
        ORDER BY event_id DESC
        LIMIT 1
    """)

    latest_event = cursor.fetchone()

    # -------------------------------------------------
    # Latest approval
    # -------------------------------------------------

    cursor.execute("""
        SELECT *
        FROM approval_requests
        ORDER BY approval_id DESC
        LIMIT 1
    """)

    latest_approval = cursor.fetchone()

    connection.close()

    event = (
        dict(latest_event)
        if latest_event
        else None
    )

    approval = (
        dict(latest_approval)
        if latest_approval
        else None
    )

    # -------------------------------------------------
    # Nothing happening yet
    # -------------------------------------------------

    if event is None:

        return {
            "status": "READY",
            "status_label": "Ready for WhatsApp enquiry",
            "quote_amount": None,
            "discount_percent": None,
            "order_id": None,
        }

    # -------------------------------------------------
    # Order completed
    #
    # ORDER_CONFIRMED.amount is authoritative because
    # it was persisted as part of the confirmed order
    # event.
    # -------------------------------------------------

    if event["event_type"] == "ORDER_CONFIRMED":

        return {
            "status": "ORDER_CONFIRMED",
            "status_label": "Order Confirmed",
            "quote_amount": event["amount"],
            "discount_percent": (
                approval["approved_percent"]
                if approval
                else None
            ),
            "order_id": event["details"],
        }

    # -------------------------------------------------
    # Human decision has been processed.
    #
    # We know the approved percentage, but we do NOT
    # currently have an authoritative persisted revised
    # quote total here. Therefore do not calculate one
    # from old demo constants.
    # -------------------------------------------------

    if (
        approval
        and approval["status"] == "PROCESSED"
    ):

        # A PROCESSED row is a completed human decision. Distinguish a
        # REJECTED-then-processed DISCOUNT from an APPROVED-then-processed
        # decision WITHOUT inferring rejection from a numeric zero:
        # reject_request never writes approved_percent, while approve_request
        # always writes a real value.
        #
        # RECONCILIATION (e213572 / SCRUM-19): a COMMERCIAL_AUTHORITY
        # approval can also reach PROCESSED, and the order-completion flow
        # persists an order_id on it. To guarantee a commercial-authority
        # decision is NEVER shown as "Discount Rejected", require BOTH:
        #   approval_type == 'DISCOUNT'  (only discount decisions can be a
        #                                 discount rejection), AND
        #   approved_percent IS NULL     (a discount rejection has no
        #                                 approved value), AND
        #   order_id IS NULL             (a rejection never created an order).
        if (
            approval.get("approval_type") == "DISCOUNT"
            and approval["approved_percent"] is None
            and approval.get("order_id") is None
        ):

            return {
                "status": "AWAITING_CUSTOMER_REJECTED",
                "status_label": "Awaiting Customer Decision",
                "quote_amount": None,
                "discount_percent": None,
                "decision": "REJECTED",
                "requested_percent": approval["requested_percent"],
                "order_id": None,
            }

        return {
            "status": "AWAITING_CUSTOMER",
            "status_label": "Awaiting Customer Decision",
            "quote_amount": None,
            "discount_percent": approval["approved_percent"],
            "decision": "APPROVED",
            "order_id": None,
        }

    # -------------------------------------------------
    # Waiting for human decision.
    #
    # Approval existence is authoritative; a current
    # quote amount is not available from this state.
    # -------------------------------------------------

    if (
        approval
        and approval["status"] in (
            "PENDING",
            "APPROVED",
        )
    ):

        return {
            "status": "HUMAN_APPROVAL",
            "status_label": "Human Approval Required",
            "quote_amount": None,
            "discount_percent": None,
            "order_id": None,
        }

    # -------------------------------------------------
    # Normal active conversation.
    #
    # A sales event proves that activity exists, but it
    # does NOT prove a S$4,735 quote exists.
    # -------------------------------------------------

    return {
        "status": "AI_HANDLING",
        "status_label": "AI Handling Conversation",
        "quote_amount": None,
        "discount_percent": None,
        "order_id": None,
    }

# =========================================================
# CUSTOMER MANAGEMENT
# =========================================================

def add_customer(
    customer_id: str,
    company_name: str,
    contact_name: str,
    phone: str,
    account_tier: str,
    delivery_area: str,
    assigned_sales_rep: str,
):
    """
    Add a new customer account.
    """

    connection = get_connection()
    cursor = connection.cursor()

    try:

        cursor.execute("""
            INSERT INTO customers (
                customer_id,
                company_name,
                contact_name,
                phone,
                account_tier,
                delivery_area,
                assigned_sales_rep
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            customer_id,
            company_name,
            contact_name,
            phone,
            account_tier,
            delivery_area,
            assigned_sales_rep,
        ))

        connection.commit()

        return {
            "success": True,
            "customer_id": customer_id,
        }

    except Exception as error:

        connection.rollback()

        return {
            "success": False,
            "error": str(error),
        }

    finally:

        connection.close()


def update_customer(
    customer_id: str,
    company_name: str,
    contact_name: str,
    phone: str,
    account_tier: str,
    delivery_area: str,
    assigned_sales_rep: str,
):
    """
    Update an existing customer account.
    """

    connection = get_connection()
    cursor = connection.cursor()

    try:

        cursor.execute("""
            UPDATE customers
            SET
                company_name = ?,
                contact_name = ?,
                phone = ?,
                account_tier = ?,
                delivery_area = ?,
                assigned_sales_rep = ?
            WHERE customer_id = ?
        """, (
            company_name,
            contact_name,
            phone,
            account_tier,
            delivery_area,
            assigned_sales_rep,
            customer_id,
        ))

        if cursor.rowcount == 0:

            connection.rollback()

            return {
                "success": False,
                "error": "CUSTOMER_NOT_FOUND",
            }

        connection.commit()

        return {
            "success": True,
            "customer_id": customer_id,
        }

    except Exception as error:

        connection.rollback()

        return {
            "success": False,
            "error": str(error),
        }

    finally:

        connection.close()


def remove_customer(
    customer_id: str
):
    """
    Remove a customer account.

    Removal may fail if the database contains
    dependent records protected by foreign keys.
    """

    connection = get_connection()
    cursor = connection.cursor()

    try:

        cursor.execute("""
            DELETE FROM customers
            WHERE customer_id = ?
        """, (
            customer_id,
        ))

        if cursor.rowcount == 0:

            connection.rollback()

            return {
                "success": False,
                "error": "CUSTOMER_NOT_FOUND",
            }

        connection.commit()

        return {
            "success": True,
            "customer_id": customer_id,
        }

    except Exception as error:

        connection.rollback()

        return {
            "success": False,
            "error": str(error),
        }

    finally:

        connection.close()

# =========================================================
# DELIVERY SLOT MANAGEMENT
# =========================================================

def add_delivery_slot(
    delivery_area: str,
    delivery_date: str,
    delivery_fee: float,
    remaining_capacity: int,
):
    """
    Add a new delivery slot.
    """

    connection = get_connection()
    cursor = connection.cursor()

    try:

        cursor.execute("""
            INSERT INTO delivery_slots (
                delivery_area,
                delivery_date,
                delivery_fee,
                remaining_capacity
            )
            VALUES (?, ?, ?, ?)
        """, (
            delivery_area,
            delivery_date,
            delivery_fee,
            remaining_capacity,
        ))

        connection.commit()

        return {
            "success": True,
            "delivery_area": delivery_area,
            "delivery_date": delivery_date,
        }

    except Exception as error:

        connection.rollback()

        return {
            "success": False,
            "error": str(error),
        }

    finally:

        connection.close()


def remove_delivery_slot(
    delivery_area: str,
    delivery_date: str,
):
    """
    Remove an existing delivery slot.
    """

    connection = get_connection()
    cursor = connection.cursor()

    try:

        cursor.execute("""
            DELETE FROM delivery_slots
            WHERE delivery_area = ?
              AND delivery_date = ?
        """, (
            delivery_area,
            delivery_date,
        ))

        if cursor.rowcount == 0:

            connection.rollback()

            return {
                "success": False,
                "error": "DELIVERY_SLOT_NOT_FOUND",
            }

        connection.commit()

        return {
            "success": True,
            "delivery_area": delivery_area,
            "delivery_date": delivery_date,
        }

    except Exception as error:

        connection.rollback()

        return {
            "success": False,
            "error": str(error),
        }

    finally:

        connection.close()

if __name__ == "__main__":
    print("Database location:", DB_PATH)

    create_tables()

    seed_commercial_policies()
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