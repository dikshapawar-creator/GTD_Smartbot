import os
import sys

# Add current dir to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db.session import SessionLocal
from app.models.auth import Tenant, User, UserTenant

db = SessionLocal()

tenants = db.query(Tenant).all()
print("--- TENANTS ---")
for t in tenants:
    print(f"ID: {t.id}, Name: {t.name}, Key: {t.tenant_key}, Active: {t.is_active}")

users = db.query(User).filter(User.email.like('%diksha%')).all()
print("\n--- USERS (diksha) ---")
for u in users:
    print(f"ID: {u.id}, Email: {u.email}, Tenant_ID: {u.tenant_id}, SuperAdmin: {u.is_super_admin}")
    
user_tenants = db.query(UserTenant).filter(UserTenant.user_id.in_([u.id for u in users])).all()
print("\n--- USER_TENANTS ---")
for ut in user_tenants:
    print(f"User_ID: {ut.user_id}, Tenant_ID: {ut.tenant_id}, Primary: {ut.is_primary}, Status: {ut.status}")

db.close()
