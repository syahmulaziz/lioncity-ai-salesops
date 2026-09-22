from datetime import datetime
from zoneinfo import ZoneInfo


def test_singapore_business_timezone():
    singapore_now = datetime.now(
        ZoneInfo("Asia/Singapore")
    )

    assert singapore_now.utcoffset().total_seconds() == 8 * 60 * 60

def test_singapore_date_format_for_order_ids():
    singapore_now = datetime.now(
        ZoneInfo("Asia/Singapore")
    )

    timestamp = singapore_now.strftime(
        "%Y%m%d%H%M%S%f"
    )

    order_id = f"SO-DEMO-{timestamp}"

    expected_date = singapore_now.strftime("%Y%m%d")

    assert order_id.startswith(
        f"SO-DEMO-{expected_date}"
    )
