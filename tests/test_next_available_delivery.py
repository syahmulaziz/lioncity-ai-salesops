from app import agent as agent_module


def test_next_available_delivery_tool_returns_earliest_slot(
    monkeypatch,
):
    """
    SCRUM-18:
    Agent must be able to retrieve the earliest available
    delivery slot after an unavailable requested date.
    """

    def fake_next_slot(delivery_area, after_date):
        assert delivery_area == "Tengah"
        assert after_date == "2026-09-22"

        return {
            "success": True,
            "delivery_area": "Tengah",
            "after_date": "2026-09-22",
            "available": True,
            "delivery_date": "2026-09-24",
            "delivery_fee": 35.0,
            "remaining_capacity": 10,
        }

    monkeypatch.setattr(
        agent_module,
        "get_next_available_delivery_slot",
        fake_next_slot,
    )

    result = agent_module.execute_tool(
        "get_next_available_delivery_slot",
        {
            "delivery_area": "Tengah",
            "after_date": "2026-09-22",
        },
    )

    assert result["success"] is True
    assert result["available"] is True
    assert result["delivery_area"] == "Tengah"
    assert result["delivery_date"] == "2026-09-24"
    assert result["delivery_fee"] == 35.0
    assert result["remaining_capacity"] == 10

def test_next_available_delivery_tool_is_exposed_to_agent():
    tool = next(
        (
            tool
            for tool in agent_module.TOOLS
            if tool["name"] == "get_next_available_delivery_slot"
        ),
        None,
    )

    assert tool is not None

    assert (
        "delivery_area"
        in tool["input_schema"]["properties"]
    )

    assert (
        "after_date"
        in tool["input_schema"]["properties"]
    )

    assert set(
        tool["input_schema"]["required"]
    ) == {
        "delivery_area",
        "after_date",
    }
