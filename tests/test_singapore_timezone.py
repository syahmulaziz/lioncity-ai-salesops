from datetime import datetime
from zoneinfo import ZoneInfo


def test_singapore_business_timezone():
    singapore_now = datetime.now(
        ZoneInfo("Asia/Singapore")
    )

    assert singapore_now.utcoffset().total_seconds() == 8 * 60 * 60