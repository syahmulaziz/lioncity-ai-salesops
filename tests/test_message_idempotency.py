from app.database import (
    is_message_processed,
    mark_message_processed,
    reset_demo_data,
)


TEST_MESSAGE_ID = "wamid.TEST-123"
TEST_PHONE = "+6581658457"


reset_demo_data()


print("\nTEST 1 - New message")

print(
    is_message_processed(
        TEST_MESSAGE_ID
    )
)


print("\nTEST 2 - Mark processed")

print(
    mark_message_processed(
        TEST_MESSAGE_ID,
        TEST_PHONE
    )
)


print("\nTEST 3 - Same message again")

print(
    is_message_processed(
        TEST_MESSAGE_ID
    )
)