import app.agent as agent_module
from app.enquiry_state import EnquiryState


def _build_agent(customer_message):
    agent = object.__new__(agent_module.SalesAgent)

    agent.phone = "+6581658457"
    agent.enquiry = EnquiryState()
    agent.messages = [
        {
            "role": "user",
            "content": (
                "WhatsApp sender phone: +6581658457\n\n"
                f"Customer message:\n{customer_message}"
            ),
        }
    ]

    agent.activity_log = []
    agent.last_triage = None
    agent._handoff_result_this_cycle = None

    return agent


def test_proceed_does_not_trigger_human_handoff(monkeypatch):
    """
    SCRUM-39 regression:
    'Please proceed' is order progression, not a request
    to speak to a salesperson.
    """

    agent = _build_agent(
        "Please proceed.\nDeliver to Tengah tomorrow."
    )

    handoffs = []

    def forbidden_handoff(*args, **kwargs):
        handoffs.append((args, kwargs))
        raise AssertionError(
            "Proceed instruction must not create a human handoff"
        )

    monkeypatch.setattr(
        agent,
        "_create_handoff",
        forbidden_handoff,
    )

    result = agent._handle_tool(
        "request_human_handoff",
        {
            "reason": "Salesperson requested",
        },
    )

    assert result["success"] is False
    assert result["error"] == "NO_EXPLICIT_HUMAN_REQUEST"

    assert handoffs == []

    assert agent.enquiry.human_requested is not True

    assert agent._handoff_result_this_cycle is None


def test_explicit_salesperson_request_still_allows_handoff(
    monkeypatch,
):
    """
    Safety regression:
    genuine customer requests for a salesperson must
    continue to work.
    """

    agent = _build_agent(
        "Can I speak to a salesperson please?"
    )

    handoffs = []

    def fake_handoff(trigger, reason):
        handoffs.append(
            {
                "trigger": trigger,
                "reason": reason,
            }
        )

        return {
            "success": True,
            "status": "RECORDED",
        }

    monkeypatch.setattr(
        agent,
        "_create_handoff",
        fake_handoff,
    )

    result = agent._handle_tool(
        "request_human_handoff",
        {
            "reason": "Customer asked for salesperson",
        },
    )

    assert result["success"] is True
    assert result["status"] == "RECORDED"

    assert len(handoffs) == 1
    assert handoffs[0]["trigger"] == "explicit_request"

    assert agent.enquiry.human_requested is True

    assert agent._handoff_result_this_cycle == result