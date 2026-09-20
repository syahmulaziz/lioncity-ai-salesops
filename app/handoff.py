"""
Minimal human-handoff interface for LionCity.

WHY THIS MODULE EXISTS
----------------------
When a customer explicitly asks to speak to a person/salesperson, the system
must record a handoff so a human can follow up. This is a DIFFERENT business
concept from discount approval:

    HUMAN HANDOFF  -> "please connect me to a salesperson"
    APPROVAL       -> "a discount needs a human decision" (approval_requests)

They must never be conflated. This module deliberately does NOT touch
``approval_requests``; it records the handoff as a ``sales_events`` entry using
the EXISTING log_sales_event() API (no database schema change, no Streamlit
redesign, no workflow engine).

TRUST / SAFETY
--------------
- Handoff context is built from VALIDATED enquiry facts supplied by the caller;
  this module does not invent missing values.
- It returns a deterministic result contract (an explicit ``status``) so callers
  never parse natural-language strings.
- It is score-independent: recording a handoff has nothing to do with the
  triage band. A ROUTINE customer can request a human just as validly as a
  HIGH_PRIORITY one.

INTEGRATION SEAM
----------------
A later teammate-owned console can consume ``sales_events`` rows of type
HUMAN_HANDOFF_REQUESTED. That is intentionally left as a read-side integration
point; we do not build it here.
"""

from app.database import log_sales_event


# Deterministic status constants (the result contract).
STATUS_RECORDED = "RECORDED"
STATUS_ERROR = "ERROR"

# The sales_events type used for an explicit customer handoff request. Kept
# distinct from any triage/priority event so the two are always separable.
EVENT_HUMAN_HANDOFF_REQUESTED = "HUMAN_HANDOFF_REQUESTED"


def _summarise_context(context):
    """
    Build a concise, human-readable details string from validated context.

    Only includes values that are actually present; never fabricates. No
    internal reasoning or scores beyond the already-computed priority band
    (which is a plain label, not an instruction).
    """
    if not isinstance(context, dict):
        return "Customer requested a salesperson."

    parts = []
    if context.get("existing_customer") is True and context.get("customer_id"):
        parts.append(f"customer={context['customer_id']}")
    else:
        parts.append("customer=guest")

    if context.get("customer_tier"):
        parts.append(f"tier={context['customer_tier']}")
    if context.get("company_name"):
        parts.append(f"company={context['company_name']}")
    if context.get("product_name"):
        parts.append(f"product={context['product_name']}")
    if context.get("quantity") is not None:
        parts.append(f"qty={context['quantity']}")
    if context.get("quotation_requested") is True:
        parts.append("quotation=yes")
    if context.get("urgent") is True:
        parts.append("urgent=yes")
    if context.get("priority_band"):
        parts.append(f"band={context['priority_band']}")

    return "Salesperson requested | " + ", ".join(parts)


def record_handoff(phone, context, trigger="explicit_request"):
    """
    Record an explicit human-handoff request.

    Parameters
    ----------
    phone : str | None
        The customer's phone reference, if known.
    context : dict
        Validated enquiry context (e.g. built from EnquiryState). Values that
        are absent are simply omitted; nothing is invented.
    trigger : str
        Why the handoff was recorded (e.g. "explicit_request").

    Returns
    -------
    dict deterministic contract:

        {"success": True,  "status": "RECORDED",
         "trigger": <trigger>, "event_type": "HUMAN_HANDOFF_REQUESTED"}

        {"success": False, "status": "ERROR", "message": <str>}
    """
    try:
        details = _summarise_context(context)
        customer_id = None
        if isinstance(context, dict) and context.get("existing_customer") is True:
            customer_id = context.get("customer_id")

        log_sales_event(
            event_type=EVENT_HUMAN_HANDOFF_REQUESTED,
            phone=phone,
            customer_id=customer_id,
            details=f"[{trigger}] {details}",
        )

        return {
            "success": True,
            "status": STATUS_RECORDED,
            "trigger": trigger,
            "event_type": EVENT_HUMAN_HANDOFF_REQUESTED,
        }
    except Exception as error:  # pragma: no cover - defensive
        return {
            "success": False,
            "status": STATUS_ERROR,
            "message": str(error),
        }
