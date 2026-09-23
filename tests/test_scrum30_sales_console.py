import app.agent as agent_module
from app.agent import SalesAgent
from app.database import (
    get_connection,
    get_latest_sales_state,
)


def test_confirmed_order_clears_current_quote():
    """
    SCRUM-30:
    Once an order is confirmed, it is no longer
    an active quote in the Sales Console.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO sales_events (
            event_type,
            customer_id,
            amount,
            details
        )
        VALUES (?, ?, ?, ?)
    """, (
        "ORDER_CONFIRMED",
        "SCRUM30-TEST",
        105.00,
        "SO-SCRUM30-TEST",
    ))

    connection.commit()
    connection.close()

    state = get_latest_sales_state()

    assert state["status"] == "ORDER_CONFIRMED"
    assert state["quote_amount"] is None

def test_active_quotation_displays_current_quote():
    """
    SCRUM-30:
    A normal active quotation must appear as the
    Current Quote and must not inherit an old discount.
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
        "QUOTATION_PREVIEW",
        "+6580000030",
        "SCRUM30-QUOTE-TEST",
        230.00,
        "CBL-300",
    ))

    connection.commit()
    connection.close()

    state = get_latest_sales_state()

    assert state["status"] == "AI_HANDLING"
    assert state["quote_amount"] == 230.00
    assert state["discount_percent"] is None
    assert state["order_id"] is None

def test_customer_price_persists_active_quote(monkeypatch):
    """
    SCRUM-30:
    The normal pricing flow must persist the trusted subtotal
    so Sales Console can display it as the active Current Quote.
    """

    monkeypatch.setattr(
        agent_module,
        "get_claude_client",
        lambda: object(),
    )

    agent = SalesAgent(phone="+6580000030")

    agent.enquiry.product_sku = "CBL-300"
    agent.enquiry.quantity = 33

    logged = []

    monkeypatch.setattr(
        agent_module,
        "log_sales_event",
        lambda **kwargs: logged.append(kwargs),
    )

    pricing_result = {
        "success": True,
        "sku": "CBL-300",
        "quantity": 33,
        "unit_price": 10.0,
        "subtotal": 330.0,
    }

    agent._ingest_tool_side_effects(
        "get_customer_price",
        pricing_result,
    )

    assert agent.enquiry.verified_subtotal == 330.0
    assert len(logged) == 1

    event = logged[0]

    assert event["event_type"] == "QUOTATION_PREVIEW"
    assert event["phone"] == "+6580000030"
    assert event["amount"] == 330.0
    assert event["details"] == "CBL-300"
