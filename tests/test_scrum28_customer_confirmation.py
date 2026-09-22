import types

import app.agent as agent_module


def test_preconfirmation_commercial_approval_does_not_create_order(
    monkeypatch
):
    """
    SCRUM-28 regression.

    Human commercial approval authorises the commercial
    terms only. If the customer has not yet confirmed the
    order, approval must NOT create an order.
    """

    agent = object.__new__(
        agent_module.SalesAgent
    )

    agent.messages = []
    agent.activity_log = []
    agent.system_prompt = "TEST SYSTEM PROMPT"

    # Critical SCRUM-28 state:
    #
    # None means create_order was never attempted after
    # explicit customer confirmation.
    agent.pending_commercial_order = None

    agent.log_activity = lambda *args, **kwargs: None
    agent._reset_response_grounding = lambda: None

    approval = {
        "approval_id": 1028,
        "phone": "+6599990028",
        "approval_type": "COMMERCIAL_AUTHORITY",
        "status": "APPROVED",
        "sku": "CBL-210",
        "requested_quantity": 600,
        "order_value": 7235.0,
        "requested_percent": 0.0,
        "approved_percent": 0.0,
        "reason": "HIGH_QUANTITY",
        "order_id": None,
    }

    # If the pre-confirmation path tries to execute ANY
    # business tool, fail immediately.
    def forbidden_handle_tool(*args, **kwargs):
        raise AssertionError(
            "Pre-confirmation human approval must not "
            "execute create_order or any other tool."
        )

    agent._handle_tool = forbidden_handle_tool

    # Stub Claude's continuation. We only care that the
    # application passes the CORRECT trusted instruction:
    # customer has NOT confirmed and no order may be created.
    response = types.SimpleNamespace(
        stop_reason="end_turn",
        content=[
            types.SimpleNamespace(
                type="text",
                text=(
                    "The commercial terms have been approved. "
                    "Would you like to proceed with the order?"
                ),
            )
        ],
    )

    agent.client = types.SimpleNamespace(
        messages=types.SimpleNamespace(
            create=lambda **kwargs: response
        )
    )

    # Keep this unit test focused on approval semantics.
    agent._finalize_customer_response = (
        lambda content: content[0].text
    )

    result = agent.apply_commercial_authority_approval(
        approval
    )

    assert result["success"] is True

    # Most important assertion:
    # no order transaction was manufactured.
    assert agent.pending_commercial_order is None

    trusted_messages = [
        message["content"]
        for message in agent.messages
        if message["role"] == "user"
        and isinstance(message["content"], str)
        and "TRUSTED HUMAN COMMERCIAL AUTHORITY APPROVAL"
        in message["content"]
    ]

    assert len(trusted_messages) == 1

    trusted_message = trusted_messages[0]

    assert "has NOT yet confirmed" in trusted_message
    assert "Do NOT create an order now" in trusted_message