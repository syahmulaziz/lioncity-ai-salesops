from app.database import (
    create_approval_request,
    approve_request,
    get_connection,
)


def test_salesperson_can_approve_custom_discount():
    phone = "SCRUM20-TEST"

    # Clean up any previous test data first.
    connection = get_connection()
    connection.execute(
        "DELETE FROM approval_requests WHERE phone = ?",
        (phone,),
    )
    connection.commit()
    connection.close()

    created = create_approval_request(
        phone=phone,
        requested_percent=10.0,
    )

    assert created["success"] is True

    approval_id = created["approval_id"]

    result = approve_request(
        approval_id=approval_id,
        approved_percent=9.0,
    )

    assert result["success"] is True
    assert result["approved_percent"] == 9.0

    connection = get_connection()

    row = connection.execute(
        """
        SELECT status, requested_percent, approved_percent
        FROM approval_requests
        WHERE approval_id = ?
        """,
        (approval_id,),
    ).fetchone()

    # Clean up after test.
    connection.execute(
        "DELETE FROM approval_requests WHERE phone = ?",
        (phone,),
    )
    connection.commit()
    connection.close()

    assert row["status"] == "APPROVED"
    assert row["requested_percent"] == 10.0
    assert row["approved_percent"] == 9.0
