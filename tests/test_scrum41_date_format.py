from app.agent import _format_customer_date


def test_customer_date_formats_iso_as_dd_mm_yyyy():
    """
    SCRUM-41:
    Customer-facing dates must use DD-MM-YYYY.
    """

    assert (
        _format_customer_date("2026-09-24")
        == "24-09-2026"
    )


def test_customer_date_formatter_does_not_change_invalid_value():
    """
    SCRUM-41:
    Unexpected/non-ISO values must not break customer responses.
    """

    assert (
        _format_customer_date("not-a-date")
        == "not-a-date"
    )


def test_customer_date_formatter_handles_none():
    """
    SCRUM-41:
    Missing dates remain missing rather than being fabricated.
    """

    assert _format_customer_date(None) is None
