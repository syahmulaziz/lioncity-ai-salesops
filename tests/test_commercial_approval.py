from app import agent as agent_module


def test_existing_commercial_approval_prevents_duplicate(monkeypatch):
    """
    An exact transaction that already has human approval
    must not create another approval request.
    """

    existing_approval = {
        "approval_id": 999,
        "phone": "TEST-PHONE",
        "approval_type": "COMMERCIAL_AUTHORITY",
        "status": "APPROVED",
        "sku": "CBL-210",
        "requested_quantity": 701,
        "order_value": 15001.0,
        "requested_percent": 9.0,
        "approved_percent": 9.0,
        "reason": "HIGH_QUANTITY,HIGH_VALUE,EXCESSIVE_DISCOUNT",
    }

    monkeypatch.setattr(
        agent_module,
        "evaluate_commercial_authority",
        lambda sku, quantity, order_value, discount_percent: {
            "success": True,
            "requires_human_approval": True,
            "reasons": [
                "HIGH_QUANTITY",
                "HIGH_VALUE",
                "EXCESSIVE_DISCOUNT",
            ],
        },
    )

    monkeypatch.setattr(
        agent_module,
        "get_matching_commercial_approval",
        lambda **kwargs: existing_approval,
    )

    def fail_if_new_approval_created(**kwargs):
        raise AssertionError(
            "Duplicate approval request was created"
        )

    monkeypatch.setattr(
        agent_module,
        "create_approval_request",
        fail_if_new_approval_created,
    )

    result = agent_module.execute_tool(
        "evaluate_commercial_authority",
        {
            "phone": "TEST-PHONE",
            "sku": "CBL-210",
            "quantity": 701,
            "order_value": 15001.0,
            "discount_percent": 9.0,
        },
    )

    assert result["success"] is True
    assert result["requires_human_approval"] is False
    assert result["human_approved"] is True
    assert result["approval"]["approval_id"] == 999


def test_unapproved_transaction_creates_approval(monkeypatch):
    """
    If no exact human approval exists, an over-authority
    transaction must still create an approval request.
    """

    monkeypatch.setattr(
        agent_module,
        "evaluate_commercial_authority",
        lambda sku, quantity, order_value, discount_percent: {
            "success": True,
            "requires_human_approval": True,
            "reasons": ["HIGH_VALUE"],
        },
    )

    monkeypatch.setattr(
        agent_module,
        "get_matching_commercial_approval",
        lambda **kwargs: None,
    )

    created = {}

    def fake_create_approval_request(**kwargs):
        created.update(kwargs)

        return {
            "success": True,
            "approval_id": 1000,
        }

    monkeypatch.setattr(
        agent_module,
        "create_approval_request",
        fake_create_approval_request,
    )

    result = agent_module.execute_tool(
        "evaluate_commercial_authority",
        {
            "phone": "TEST-PHONE",
            "sku": "CBL-210",
            "quantity": 701,
            "order_value": 15001.0,
            "discount_percent": 9.0,
        },
    )

    assert result["success"] is True
    assert result["requires_human_approval"] is True

    assert created["approval_type"] == "COMMERCIAL_AUTHORITY"
    assert created["phone"] == "TEST-PHONE"
    assert created["sku"] == "CBL-210"
    assert created["requested_quantity"] == 701
    assert created["order_value"] == 15001.0
    assert created["requested_percent"] == 9.0

def test_commercial_approval_resumes_agent(monkeypatch):
    """
    A commercial authority approval must inject trusted human
    context and resume the existing SalesAgent conversation.
    """

    agent = object.__new__(agent_module.SalesAgent)

    agent.messages = []
    logged = []

    def fake_log_activity(activity_type, message, details=None):
        logged.append({
            "activity_type": activity_type,
            "message": message,
            "details": details,
        })

    agent.log_activity = fake_log_activity

    resumed = {"called": False}

    def fake_continue():
        resumed["called"] = True

        return {
            "success": True,
            "response": "Approved transaction resumed.",
        }

    monkeypatch.setattr(
        agent,
        "_continue_after_human_action",
        fake_continue,
    )

    approval = {
        "approval_id": 999,
        "phone": "TEST-PHONE",
        "approval_type": "COMMERCIAL_AUTHORITY",
        "sku": "CBL-210",
        "requested_quantity": 701,
        "order_value": 15001.0,
        "requested_percent": 9.0,
        "approved_percent": 9.0,
        "reason": (
            "HIGH_QUANTITY,HIGH_VALUE,"
            "EXCESSIVE_DISCOUNT"
        ),
    }

    result = agent.apply_commercial_authority_approval(
        approval
    )

    assert result["success"] is True
    assert resumed["called"] is True

    assert len(agent.messages) == 1

    trusted_message = agent.messages[0]

    assert trusted_message["role"] == "user"

    assert (
        "[TRUSTED HUMAN COMMERCIAL AUTHORITY APPROVAL]"
        in trusted_message["content"]
    )

    assert "CBL-210" in trusted_message["content"]
    assert "701" in trusted_message["content"]
    assert "15001.0" in trusted_message["content"]
    assert "9.0%" in trusted_message["content"]

    assert len(logged) == 1
    assert (
        logged[0]["activity_type"]
        == "commercial_authority_approval"
    )