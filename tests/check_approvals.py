from pprint import pprint

from app.database import get_pending_approvals


print("\nPENDING APPROVALS")
pprint(
    get_pending_approvals()
)