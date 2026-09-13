import os

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request
from fastapi.responses import PlainTextResponse

from app.agent import SalesAgent

from app.database import (
    create_approval_request,
    get_approved_unprocessed_requests,
    mark_approval_processed,
    reset_demo_data,
    is_message_processed,
    mark_message_processed,
    log_sales_event,
)

# =========================================================
# ENVIRONMENT VARIABLES
# =========================================================

load_dotenv()


WHATSAPP_ACCESS_TOKEN = os.getenv(
    "WHATSAPP_ACCESS_TOKEN"
)

WHATSAPP_PHONE_NUMBER_ID = os.getenv(
    "WHATSAPP_PHONE_NUMBER_ID"
)


# This is OUR verification token.
# It must match the token configured in Meta Webhooks.
VERIFY_TOKEN = "lioncity-demo-verify"


# =========================================================
# VALIDATE CONFIGURATION
# =========================================================

if not WHATSAPP_ACCESS_TOKEN:
    print(
        "WARNING: WHATSAPP_ACCESS_TOKEN "
        "was not found in .env"
    )


if not WHATSAPP_PHONE_NUMBER_ID:
    print(
        "WARNING: WHATSAPP_PHONE_NUMBER_ID "
        "was not found in .env"
    )


# =========================================================
# FASTAPI APPLICATION
# =========================================================

app = FastAPI(
    title="LionCity WhatsApp API"
)


# =========================================================
# CUSTOMER CONVERSATION SESSIONS
# =========================================================
#
# FastAPI keeps one SalesAgent instance for each
# WhatsApp customer.
#
# Example:
#
# +6581658457
#       ↓
# SalesAgent(...)
#
# This lets:
#
# Message 1 → quote
# Message 2 → discount request
# Message 3 → deal
#
# remain part of the same Claude conversation.
# =========================================================

customer_agents = {}


def normalize_phone(
    whatsapp_number: str
):
    """
    Convert Meta's phone format:

        6581658457

    into LionCity's format:

        +6581658457
    """

    if whatsapp_number.startswith("+"):
        return whatsapp_number

    return f"+{whatsapp_number}"


def get_customer_agent(
    whatsapp_number: str
):
    """
    Get or create the persistent SalesAgent
    for a WhatsApp customer.

    Creating a new agent represents the start
    of a new sales conversation.
    """

    normalized_phone = normalize_phone(
        whatsapp_number
    )

    if normalized_phone not in customer_agents:

        print(
            "\nCREATING NEW SALES AGENT FOR:",
            normalized_phone
        )

        customer_agents[
            normalized_phone
        ] = SalesAgent(
            phone=normalized_phone
        )

        # A new in-memory SalesAgent represents
        # one new sales conversation.
        log_sales_event(
            event_type="CONVERSATION_STARTED",
            phone=normalized_phone,
            details=(
                "WhatsApp sales conversation started"
            ),
        )

        print(
            "SALES EVENT LOGGED: "
            "CONVERSATION_STARTED"
        )

    return customer_agents[
        normalized_phone
    ]


# =========================================================
# SEND WHATSAPP MESSAGE
# =========================================================

def send_whatsapp_message(
    recipient: str,
    message: str
):
    """
    Send a normal text message through
    Meta WhatsApp Cloud API.
    """

    if not WHATSAPP_ACCESS_TOKEN:
        raise ValueError(
            "WHATSAPP_ACCESS_TOKEN "
            "is missing from .env"
        )

    if not WHATSAPP_PHONE_NUMBER_ID:
        raise ValueError(
            "WHATSAPP_PHONE_NUMBER_ID "
            "is missing from .env"
        )

    # Meta expects recipient without "+"
    clean_recipient = recipient.lstrip("+")

    url = (
        "https://graph.facebook.com/v26.0/"
        f"{WHATSAPP_PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": (
            f"Bearer {WHATSAPP_ACCESS_TOKEN}"
        ),
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_recipient,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": message,
        },
    }

    print("\n" + "-" * 60)
    print("SENDING WHATSAPP MESSAGE")
    print("-" * 60)

    print(
        "TO:",
        clean_recipient
    )

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=30,
    )

    print(
        "WHATSAPP SEND STATUS:",
        response.status_code
    )

    print(
        "WHATSAPP SEND RESPONSE:",
        response.text
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/")
def health_check():
    """
    Simple endpoint used to verify that
    FastAPI/ngrok is working.
    """

    return {
        "status": "ok",
        "service": "LionCity WhatsApp API",
    }


# =========================================================
# META WEBHOOK VERIFICATION
# =========================================================

@app.get("/webhook")
def verify_webhook(
    hub_mode: str = Query(
        default=None,
        alias="hub.mode",
    ),
    hub_verify_token: str = Query(
        default=None,
        alias="hub.verify_token",
    ),
    hub_challenge: str = Query(
        default=None,
        alias="hub.challenge",
    ),
):
    """
    Meta calls this endpoint when verifying
    our webhook URL.
    """

    if (
        hub_mode == "subscribe"
        and hub_verify_token == VERIFY_TOKEN
    ):

        print(
            "WhatsApp webhook "
            "verified successfully."
        )

        return PlainTextResponse(
            content=hub_challenge
        )

    print(
        "WhatsApp webhook verification failed."
    )

    return PlainTextResponse(
        content="Verification failed",
        status_code=403,
    )


# =========================================================
# RECEIVE WHATSAPP EVENTS
# =========================================================

@app.post("/webhook")
async def receive_webhook(
    request: Request
):
    """
    Receive events from Meta WhatsApp Cloud API.

    For the prototype we process TEXT messages only.

    Status updates, delivery receipts and other
    webhook events are safely ignored.
    """

    payload = await request.json()

    print("\n")
    print("=" * 60)
    print("WHATSAPP WEBHOOK RECEIVED")
    print("=" * 60)

    try:

        # =================================================
        # STEP 1
        # Navigate Meta webhook structure
        # =================================================

        entries = payload.get(
            "entry",
            []
        )

        if not entries:

            print(
                "No entry found. Ignoring event."
            )

            return {
                "status": "ignored",
                "reason": "NO_ENTRY",
            }


        changes = entries[0].get(
            "changes",
            []
        )

        if not changes:

            print(
                "No changes found. Ignoring event."
            )

            return {
                "status": "ignored",
                "reason": "NO_CHANGES",
            }


        value = changes[0].get(
            "value",
            {}
        )


        # =================================================
        # STEP 2
        # Ignore delivery/read/status events
        # =================================================

        messages = value.get(
            "messages"
        )

        if not messages:

            print(
                "No customer message in event. "
                "Ignoring."
            )

            return {
                "status": "ignored",
                "reason": "NO_CUSTOMER_MESSAGE",
            }


        message = messages[0]

        # =================================================
        # IDEMPOTENCY CHECK
        # =================================================

        message_id = message.get("id")

        if not message_id:

            print(
                "WhatsApp message has no message ID. "
                "Ignoring."
            )

            return {
                "status": "ignored",
                "reason": "NO_MESSAGE_ID",
            }


        if is_message_processed(
            message_id
        ):

            print("\n" + "-" * 60)
            print("DUPLICATE WHATSAPP MESSAGE IGNORED")
            print("-" * 60)

            print(
                "MESSAGE ID:",
                message_id
            )

            return {
                "status": "ignored",
                "reason": "DUPLICATE_MESSAGE",
                "message_id": message_id,
            }

        # =================================================
        # STEP 3
        # Only process text messages
        # =================================================

        message_type = message.get(
            "type"
        )

        if message_type != "text":

            print(
                "Unsupported message type:",
                message_type
            )

            return {
                "status": "ignored",
                "reason": "UNSUPPORTED_MESSAGE_TYPE",
            }


        # =================================================
        # STEP 4
        # Extract customer phone and message
        # =================================================

        sender = message.get(
            "from"
        )

        text_data = message.get(
            "text",
            {}
        )

        customer_message = text_data.get(
            "body",
            ""
        ).strip()


        if not sender:

            print(
                "Sender missing from WhatsApp event."
            )

            return {
                "status": "ignored",
                "reason": "NO_SENDER",
            }


        if not customer_message:

            print(
                "Customer message is empty."
            )

            return {
                "status": "ignored",
                "reason": "EMPTY_MESSAGE",
            }


        normalized_phone = normalize_phone(
            sender
        )

        log_sales_event(
            event_type="CUSTOMER_MESSAGE",
            phone=normalized_phone,
            details=customer_message,
        )

        print(
            "SALES EVENT LOGGED: CUSTOMER_MESSAGE"
        )

        print(
            "FROM:",
            normalized_phone
        )

        print(
            "MESSAGE:",
            customer_message
        )


        # =================================================
        # STEP 5
        # Get persistent SalesAgent
        # =================================================

        agent = get_customer_agent(
            sender
        )


        # =================================================
        # STEP 6
        # Run the REAL LionCity AI Sales Agent
        # =================================================

        result = agent.send(
            customer_message
        )


        # =================================================
        # STEP 7
        # If the agent requires HUMAN approval,
        # write that request into shared SQLite.
        #
        # IMPORTANT:
        # Nothing here runs if there is no approval.
        # =================================================

        if agent.pending_approval is not None:

            approval = (
                agent.pending_approval
            )

            requested_discount = (
                approval.get(
                    "requested_discount_percent"
                )
            )

            if requested_discount is not None:

                approval_result = (
                    create_approval_request(
                        phone=normalized_phone,
                        requested_percent=
                            requested_discount,
                    )
                )

                # =================================================
                # SALESOPS — HUMAN ESCALATION
                # =================================================

                if not approval_result.get(
                    "already_exists",
                    False
                ):

                    log_sales_event(
                        event_type="HUMAN_APPROVAL_REQUIRED",
                        phone=normalized_phone,
                        details=(
                            f"Discount requested: "
                            f"{requested_discount}%"
                        ),
                    )

                    print(
                        "SALES EVENT LOGGED: "
                        "HUMAN_APPROVAL_REQUIRED"
                    )

                print("\n" + "-" * 60)
                print(
                    "APPROVAL REQUEST "
                    "WRITTEN TO DATABASE"
                )
                print("-" * 60)

                print(
                    approval_result
                )


        # =================================================
        # STEP 8
        # Prepare customer-facing response
        # =================================================

        if result.get("success"):

            reply = result.get(
                "response",
                ""
            )

        else:

            reply = (
                "Sorry, I couldn't complete "
                "your request right now."
            )


        if not reply:

            reply = (
                "Sorry, I couldn't generate "
                "a response right now."
            )


        # =================================================
        # STEP 9
        # Send response back to REAL WhatsApp
        # =================================================

        send_result = (
            send_whatsapp_message(
                recipient=sender,
                message=reply,
            )
        )

        # =================================================
        # MESSAGE SUCCESSFULLY PROCESSED
        # =================================================
        #
        # Only mark the inbound WhatsApp message as
        # processed after:
        #
        # 1. Claude completed its work
        # 2. Business tools completed
        # 3. The reply was successfully accepted by Meta
        #
        # If something fails earlier, Meta may retry and
        # LionCity can safely process it again.
        # =================================================

        mark_message_processed(
            message_id=message_id,
            phone=normalized_phone,
        )

        print(
            "MESSAGE MARKED AS PROCESSED:",
            message_id
        )


        print("\n" + "=" * 60)
        print(
            "WHATSAPP MESSAGE PROCESSED SUCCESSFULLY"
        )
        print("=" * 60)


        return {
            "status": "processed",
            "sender": normalized_phone,
            "approval_required": (
                agent.pending_approval
                is not None
            ),
            "whatsapp_result": send_result,
        }


    # =====================================================
    # ERROR HANDLING
    # =====================================================

    except Exception as error:

        print("\n" + "!" * 60)
        print("WHATSAPP PROCESSING ERROR")
        print("!" * 60)

        print(
            type(error).__name__,
            ":",
            str(error)
        )

        # For this prototype we return HTTP 200 even
        # when processing fails, otherwise Meta may
        # repeatedly retry the same webhook event.
        #
        # For production we would implement proper
        # retry/idempotency handling.

        return {
            "status": "error",
            "error_type":
                type(error).__name__,
            "message":
                str(error),
        }

    # =========================================================
# PROCESS HUMAN APPROVALS
# =========================================================

@app.post("/process-approvals")
def process_approvals():
    """
    Apply human decisions made in the Sales Console.

    Streamlit writes the human decision to SQLite.
    This endpoint retrieves approved decisions,
    resumes the correct in-memory SalesAgent,
    and sends the revised offer back to WhatsApp.
    """

    approvals = (
        get_approved_unprocessed_requests()
    )

    processed = []
    skipped = []

    print("\n" + "=" * 60)
    print("PROCESSING HUMAN APPROVALS")
    print("=" * 60)

    for approval in approvals:

        approval_id = approval[
            "approval_id"
        ]

        phone = approval[
            "phone"
        ]

        approved_percent = approval[
            "approved_percent"
        ]

        print(
            "\nApproval:",
            approval_id
        )

        print(
            "Customer:",
            phone
        )

        print(
            "Approved discount:",
            approved_percent
        )

        # -------------------------------------------------
        # Find the SAME SalesAgent that handled the
        # WhatsApp conversation.
        # -------------------------------------------------

        agent = customer_agents.get(
            phone
        )

        if agent is None:

            print(
                "No active SalesAgent found "
                "for customer."
            )

            skipped.append({
                "approval_id": approval_id,
                "reason": "NO_ACTIVE_AGENT",
            })

            continue

        # -------------------------------------------------
        # Resume Claude with trusted human decision.
        # -------------------------------------------------

        result = agent.apply_human_approval(
            approved_discount_percent=
                approved_percent
        )

        if not result.get("success"):

            print(
                "Agent could not apply approval:",
                result
            )

            skipped.append({
                "approval_id": approval_id,
                "reason": "AGENT_REJECTED_APPROVAL",
            })

            continue

        # -------------------------------------------------
        # Send revised offer to REAL WhatsApp.
        # -------------------------------------------------

        send_whatsapp_message(
            recipient=phone,
            message=result["response"],
        )

        # -------------------------------------------------
        # SALESOPS — HUMAN DECISION
        # -------------------------------------------------

        log_sales_event(
            event_type="HUMAN_APPROVAL_APPROVED",
            phone=phone,
            details=(
                f"Approved discount: "
                f"{approved_percent}%"
            ),
        )

        print(
            "SALES EVENT LOGGED: "
            "HUMAN_APPROVAL_APPROVED"
        )

        # -------------------------------------------------
        # Mark decision as consumed so it isn't sent twice.
        # -------------------------------------------------

        mark_approval_processed(
            approval_id
        )

        processed.append(
            approval_id
        )

        print(
            "Approval applied successfully."
        )

    return {
        "success": True,
        "processed": processed,
        "skipped": skipped,
    }

# =========================================================
# RESET DEMO
# =========================================================

@app.post("/reset-demo")
def reset_demo():
    """
    Reset the LionCity prototype to a known starting state.
    """

    print("\n" + "=" * 60)
    print("RESETTING LIONCITY DEMO")
    print("=" * 60)

    # Clear all in-memory WhatsApp conversations.
    customer_agents.clear()

    # Restore mutable SQLite demo data.
    result = reset_demo_data()

    print("Customer conversations cleared.")
    print("Approval queue cleared.")
    print("Inventory restored.")
    print("Delivery capacity restored.")

    return {
        "success": True,
        "database": result,
        "active_agents": len(customer_agents),
    }