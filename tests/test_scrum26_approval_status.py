import app.database as database


def _cleanup(phone):
    connection = database.get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        DELETE FROM approval_requests
        WHERE phone = ?
        """,
        (phone,),
    )

    cursor.execute(
        """
        DELETE FROM sales_events
        WHERE phone = ?
        """,
        (phone,),
    )

    connection.commit()
    connection.close()


def test_human_approval_required_only_while_pending():
    """
    SCRUM-26 regression.

    Sales Console must show HUMAN_APPROVAL only while
    a human decision is genuinely pending.

    Once the human approves the request, the dashboard
    must stop claiming that human approval is required.
    """

    phone = "+6599990026"

    database.create_tables()
    _cleanup(phone)

    try:

        # Give get_latest_sales_state() an active event.
        database.log_sales_event(
            event_type="CUSTOMER_MESSAGE",
            phone=phone,
            details="SCRUM-26 regression test",
        )

        approval = database.create_approval_request(
            phone=phone,
            requested_percent=0,
            approval_type="COMMERCIAL_AUTHORITY",
            sku="CBL-210",
            requested_quantity=600,
            order_value=7235.0,
            reason="HIGH_QUANTITY",
        )

        approval_id = approval["approval_id"]

        # ---------------------------------------------
        # BEFORE human decision
        # ---------------------------------------------

        pending_state = database.get_latest_sales_state()

        assert pending_state["status"] == "HUMAN_APPROVAL"
        assert (
            pending_state["status_label"]
            == "Human Approval Required"
        )

        # ---------------------------------------------
        # Human approves
        # ---------------------------------------------

        result = database.approve_request(
            approval_id=approval_id,
            approved_percent=0,
        )

        assert result["success"] is True

        # ---------------------------------------------
        # AFTER human decision
        #
        # APPROVED means the human has already acted.
        # The dashboard must therefore NOT continue
        # claiming that human approval is required.
        # ---------------------------------------------

        approved_state = database.get_latest_sales_state()

        assert approved_state["status"] != "HUMAN_APPROVAL"
        assert (
            approved_state["status_label"]
            != "Human Approval Required"
        )

        # ---------------------------------------------
        # Fully consumed decision
        # ---------------------------------------------

        database.mark_approval_processed(
            approval_id
        )

        processed_state = database.get_latest_sales_state()

        assert processed_state["status"] != "HUMAN_APPROVAL"
        assert (
            processed_state["status_label"]
            != "Human Approval Required"
        )

    finally:

        _cleanup(phone)