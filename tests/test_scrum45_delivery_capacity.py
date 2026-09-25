import sqlite3

import app.tools.order_creation as order_module


def _create_test_db(tmp_path):
    """
    Minimal isolated database containing only the tables required
    by create_order().
    """
    db_path = tmp_path / "scrum45.db"

    connection = sqlite3.connect(db_path)

    connection.executescript(
        """
        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            order_date TEXT NOT NULL,
            delivery_area TEXT,
            status TEXT NOT NULL
        );

        CREATE TABLE order_items (
            order_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL,
            sku TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL
        );

        CREATE TABLE inventory (
            sku TEXT PRIMARY KEY,
            available_quantity INTEGER NOT NULL
        );

        CREATE TABLE delivery_slots (
            delivery_area TEXT NOT NULL,
            delivery_date TEXT NOT NULL,
            delivery_fee REAL NOT NULL,
            remaining_capacity INTEGER NOT NULL,
            PRIMARY KEY (delivery_area, delivery_date)
        );

        INSERT INTO inventory (
            sku,
            available_quantity
        )
        VALUES ('CBL-210', 100);

        INSERT INTO delivery_slots (
            delivery_area,
            delivery_date,
            delivery_fee,
            remaining_capacity
        )
        VALUES (
            'Jurong',
            '2026-09-26',
            35.0,
            5
        );
        """
    )

    connection.commit()
    connection.close()

    return db_path


def _patch_database(monkeypatch, db_path):
    """
    Make order_creation use our isolated SQLite database.
    """

    def fake_get_connection():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        return connection

    monkeypatch.setattr(
        order_module,
        "get_connection",
        fake_get_connection,
    )

    # Keep test independent from sales-event persistence.
    monkeypatch.setattr(
        order_module,
        "log_sales_event",
        lambda **kwargs: None,
    )


def _capacity(db_path):
    connection = sqlite3.connect(db_path)

    value = connection.execute(
        """
        SELECT remaining_capacity
        FROM delivery_slots
        WHERE delivery_area = 'Jurong'
          AND delivery_date = '2026-09-26'
        """
    ).fetchone()[0]

    connection.close()

    return value


def _inventory(db_path):
    connection = sqlite3.connect(db_path)

    value = connection.execute(
        """
        SELECT available_quantity
        FROM inventory
        WHERE sku = 'CBL-210'
        """
    ).fetchone()[0]

    connection.close()

    return value


def test_scrum45_confirmed_order_consumes_one_delivery_slot(
    tmp_path,
    monkeypatch,
):
    """
    SCRUM-45 regression.

    A successfully confirmed order consumes exactly one unit of
    delivery capacity for its selected area/date.
    """
    db_path = _create_test_db(tmp_path)
    _patch_database(monkeypatch, db_path)

    assert _capacity(db_path) == 5

    result = order_module.create_order(
        customer_id="CUST-001",
        items=[
            {
                "sku": "CBL-210",
                "quantity": 10,
                "unit_price": 12.0,
            }
        ],
        product_subtotal=120.0,
        discount_percent=0.0,
        delivery_fee=35.0,
        final_total=155.0,
        delivery_area="Jurong",
        delivery_date="2026-09-26",
    )

    assert result["success"] is True

    assert _capacity(db_path) == 4
    assert _inventory(db_path) == 90


def test_scrum45_failed_order_does_not_consume_delivery_slot(
    tmp_path,
    monkeypatch,
):
    """
    Order + inventory + delivery capacity must be atomic.

    Insufficient inventory causes the entire transaction to roll
    back, including any delivery-capacity mutation.
    """
    db_path = _create_test_db(tmp_path)
    _patch_database(monkeypatch, db_path)

    result = order_module.create_order(
        customer_id="CUST-001",
        items=[
            {
                "sku": "CBL-210",
                "quantity": 999,
                "unit_price": 12.0,
            }
        ],
        product_subtotal=11988.0,
        discount_percent=0.0,
        delivery_fee=35.0,
        final_total=12023.0,
        delivery_area="Jurong",
        delivery_date="2026-09-26",
    )

    assert result["success"] is False

    # Nothing from the failed transaction is consumed.
    assert _capacity(db_path) == 5
    assert _inventory(db_path) == 100


def test_scrum45_full_delivery_slot_rejects_order(
    tmp_path,
    monkeypatch,
):
    """
    create_order must revalidate capacity at persistence time.

    A slot that has become full since check_delivery() must not
    accept another confirmed order.
    """
    db_path = _create_test_db(tmp_path)
    _patch_database(monkeypatch, db_path)

    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        UPDATE delivery_slots
        SET remaining_capacity = 0
        WHERE delivery_area = 'Jurong'
          AND delivery_date = '2026-09-26'
        """
    )
    connection.commit()
    connection.close()

    result = order_module.create_order(
        customer_id="CUST-001",
        items=[
            {
                "sku": "CBL-210",
                "quantity": 10,
                "unit_price": 12.0,
            }
        ],
        product_subtotal=120.0,
        discount_percent=0.0,
        delivery_fee=35.0,
        final_total=155.0,
        delivery_area="Jurong",
        delivery_date="2026-09-26",
    )

    assert result["success"] is False

    assert _capacity(db_path) == 0

    # Inventory must also roll back.
    assert _inventory(db_path) == 100


def test_scrum45_missing_delivery_slot_rejects_order(
    tmp_path,
    monkeypatch,
):
    """
    An order cannot be confirmed against a delivery slot that does
    not exist.
    """
    db_path = _create_test_db(tmp_path)
    _patch_database(monkeypatch, db_path)

    result = order_module.create_order(
        customer_id="CUST-001",
        items=[
            {
                "sku": "CBL-210",
                "quantity": 10,
                "unit_price": 12.0,
            }
        ],
        product_subtotal=120.0,
        discount_percent=0.0,
        delivery_fee=35.0,
        final_total=155.0,
        delivery_area="Tengah",
        delivery_date="2026-09-26",
    )

    assert result["success"] is False

    assert _capacity(db_path) == 5
    assert _inventory(db_path) == 100