import sys
import os

# Add the current directory to sys.path to allow importing from app
sys.path.append(os.getcwd())

from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.session import SessionLocal
from app.models.auth import Tenant, Role, User, UserTenant, AuditLog, RefreshToken, PasswordReset
from app.models.lead import Lead, LeadStatusHistory
from app.models.chat_session import ChatSession
from app.models.chat_message import ChatMessage
from app.models.intent_config import IntentConfig
from app.models.bot_config import BotConfig
from app.models.blocked import BlockedVisitor

def delete_tenant_data(tenant_id: int):
    db: Session = SessionLocal()
    try:
        print(f"--- Starting deletion for Tenant ID: {tenant_id} ---")

        # 0. Legacy Conversations (linked to Leads)
        from app.models.conversation import Conversation
        # Find lead IDs for subquery
        lead_ids = db.query(Lead.id).filter(Lead.tenant_id == tenant_id).all()
        l_ids = [str(lid[0]) for lid in lead_ids]
        if l_ids:
            count = db.query(Conversation).filter(Conversation.lead_id.in_(l_ids)).delete(synchronize_session=False)
            print(f"Deleted {count} legacy Conversations")

        # 1. Chat Messages
        count = db.query(ChatMessage).filter(ChatMessage.tenant_id == tenant_id).delete(synchronize_session=False)
        print(f"Deleted {count} ChatMessages")

        # 2. Lead Status History
        count = db.query(LeadStatusHistory).filter(LeadStatusHistory.tenant_id == tenant_id).delete(synchronize_session=False)
        print(f"Deleted {count} LeadStatusHistory records")

        # 3. Chat Sessions
        count = db.query(ChatSession).filter(ChatSession.tenant_id == tenant_id).delete(synchronize_session=False)
        print(f"Deleted {count} ChatSessions")

        # 4. Leads
        count = db.query(Lead).filter(Lead.tenant_id == tenant_id).delete(synchronize_session=False)
        print(f"Deleted {count} Leads")

        # 5. Intent Configs
        count = db.query(IntentConfig).filter(IntentConfig.tenant_id == tenant_id).delete(synchronize_session=False)
        print(f"Deleted {count} IntentConfigs")

        # 6. Bot Config
        count = db.query(BotConfig).filter(BotConfig.tenant_id == tenant_id).delete(synchronize_session=False)
        print(f"Deleted {count} BotConfigs")

        # 7. Blocked Visitors
        count = db.query(BlockedVisitor).filter(BlockedVisitor.tenant_id == tenant_id).delete(synchronize_session=False)
        print(f"Deleted {count} BlockedVisitors")

        # 8. Audit Logs
        count = db.query(AuditLog).filter(AuditLog.tenant_id == tenant_id).delete(synchronize_session=False)
        print(f"Deleted {count} AuditLogs")

        # 9. Refresh Tokens
        count = db.query(RefreshToken).filter(RefreshToken.tenant_id == tenant_id).delete(synchronize_session=False)
        print(f"Deleted {count} RefreshTokens")

        # 10. Password Resets
        count = db.query(PasswordReset).filter(PasswordReset.tenant_id == tenant_id).delete(synchronize_session=False)
        print(f"Deleted {count} PasswordResets")

        # 11. UserTenant (Associations)
        count = db.query(UserTenant).filter(UserTenant.tenant_id == tenant_id).delete(synchronize_session=False)
        print(f"Deleted {count} UserTenant associations")

        # 12. Users
        # Only delete users whose PRIMARY tenant was this one.
        count = db.query(User).filter(User.tenant_id == tenant_id).delete(synchronize_session=False)
        print(f"Deleted {count} Users")

        # 13. Roles
        count = db.query(Role).filter(Role.tenant_id == tenant_id).delete(synchronize_session=False)
        print(f"Deleted {count} Roles")

        # 14. Tenant
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if tenant:
            name = tenant.name
            db.delete(tenant)
            print(f"Deleted Tenant: {name}")
        else:
            print(f"Tenant with ID {tenant_id} not found.")

        db.commit()
        print("--- DELETION COMPLETE AND COMMITTED ---")
    except Exception as e:
        db.rollback()
        print(f"--- ERROR OCCURRED: {e} ---")
        print("--- CHANGES ROLLED BACK ---")
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            target_id = int(sys.argv[1])
        except ValueError:
            print("Please provide a valid numeric Tenant ID.")
            sys.exit(1)
    else:
        target_id = 4 # Default for this request
    
    delete_tenant_data(target_id)
