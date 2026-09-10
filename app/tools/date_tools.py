from datetime import date, timedelta


WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6
}


def resolve_date(
    requested_day: str,
    current_date: str
):
    """
    Convert a weekday such as 'Tuesday' into the
    next matching calendar date.
    """

    requested_day_normalized = (
        requested_day.strip().lower()
    )

    if requested_day_normalized not in WEEKDAYS:

        return {
            "success": False,
            "error": "UNSUPPORTED_DATE_EXPRESSION",
            "requested_day": requested_day
        }

    today = date.fromisoformat(current_date)

    target_weekday = WEEKDAYS[
        requested_day_normalized
    ]

    days_ahead = (
        target_weekday - today.weekday()
    ) % 7

    # If customer says the same weekday as today,
    # interpret it as the NEXT occurrence.
    if days_ahead == 0:
        days_ahead = 7

    resolved = today + timedelta(
        days=days_ahead
    )

    return {
        "success": True,
        "requested_day": requested_day,
        "current_date": current_date,
        "resolved_date": resolved.isoformat(),
        "resolved_weekday": resolved.strftime("%A")
    }