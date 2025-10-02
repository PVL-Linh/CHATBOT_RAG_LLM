# tools/seed_users.py
from ..Login.login_required import upsert_user, list_users
upsert_user("admin",  password="admin@123",  roles="admin")
upsert_user("leader1", password="Leader@123", roles="manager_marketing,marketing")
upsert_user("staff1",  password="Staff@123",  roles="marketing")
print(list_users())
