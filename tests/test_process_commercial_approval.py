from app import whatsapp_api


class FakeCommercialAgent:
    def __init__(self):
        self.received_approval = None

    def apply_commercial_authority_approval(self, approval):
        self.received_approval = approval

        return {
            "success": True,
            "response": "Your approved transaction can proceed.",
        }

    def apply_human_approval(self, approved_discount_percent):
        raise AssertionError(
            "Legacy discount approval path should not be used "
            "for COMMERCIAL_AUTHORITY."
        )


def test_process_commercial_approval_resumes_and_sends_whatsapp(
    monkeypatch,
):
    phone = "+6599999999"
    approval_id = 999

    approval = {
        "approval_id": approval_id,
        "phone": phone,
        "approval_type": "COMMERCIAL_AUTHORITY",
        "status": "APPROVED",
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

    fake_agent = FakeCommercialAgent()

    # Put the fake agent into the same in-memory session
    # dictionary used by /process-approvals.
    whatsapp_api.customer_agents.clear()
    whatsapp_api.customer_agents[phone] = fake_agent

    monkeypatch.setattr(
        whatsapp_api,
        "get_approved_unprocessed_requests",
        lambda: [approval],
    )

    sent_messages = []

    def fake_send_whatsapp_message(recipient, message):
        sent_messages.append({
            "recipient": recipient,
            "message": message,
        })

        return {"success": True}

    monkeypatch.setattr(
        whatsapp_api,
        "send_whatsapp_message",
        fake_send_whatsapp_message,
    )

    processed_ids = []

    monkeypatch.setattr(
        whatsapp_api,
        "mark_approval_processed",
        lambda approval_id: processed_ids.append(
            approval_id
        ),
    )

    logged_events = []

    def fake_log_sales_event(**kwargs):
        logged_events.append(kwargs)

    monkeypatch.setattr(
        whatsapp_api,
        "log_sales_event",
        fake_log_sales_event,
    )

    result = whatsapp_api.process_approvals()

    assert result["success"] is True
    assert result["processed"] == [approval_id]
    assert result["skipped"] == []

    # Correct commercial method received the approval.
    assert fake_agent.received_approval == approval

    # Customer received the resumed conversation.
    assert len(sent_messages) == 1
    assert sent_messages[0]["recipient"] == phone
    assert (
        sent_messages[0]["message"]
        == "Your approved transaction can proceed."
    )

    # Approval was consumed only after successful processing.
    assert processed_ids == [approval_id]

    assert len(logged_events) == 1

    whatsapp_api.customer_agents.clear()