from app.database import (
    create_tables,
    create_approval_request,
    approve_request,
    get_approval_by_id,
    get_connection,
)


TEST_PHONE = "+6599990019"


def _cleanup_test_approvals():
    """
    Keep this regression test repeatable.

    Remove only records belonging to the dedicated
    SCRUM-19 test phone number.
    """

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        DELETE FROM approval_requests
        WHERE phone = ?
        """,
        (TEST_PHONE,),
    )

    connection.commit()
    connection.close()


def test_commercial_approval_schema_supports_order_link():
    """
    SCRUM-19 regression:

    A commercial approval must be able to persist the
    order_id of the real order that consumed it.
    """

    create_tables()

    _cleanup_test_approvals()

    try:

        approval = create_approval_request(
            phone=TEST_PHONE,
            requested_percent=0,
            approval_type="COMMERCIAL_AUTHORITY",
            sku="CBL-210",
            requested_quantity=600,
            order_value=7235.0,
            reason="HIGH_QUANTITY",
        )

        approval_id = approval["approval_id"]

        result = approve_request(
            approval_id=approval_id,
            approved_percent=0,
        )

        assert result["success"] is True

        stored = get_approval_by_id(
            approval_id
        )

        assert stored is not None
        assert stored["approval_id"] == approval_id
        assert stored["status"] == "APPROVED"
        assert stored["sku"] == "CBL-210"
        assert stored["requested_quantity"] == 600
        assert stored["order_value"] == 7235.0
        assert stored["order_id"] is None

    finally:

        _cleanup_test_approvals()