from sqlalchemy.orm import Session
from typing import Optional
from app.models.auth import AuditLog

class AuditService:
    @staticmethod
    def log_action(
        db: Session,
        action: str,
        tenant_id: int,  # REQUIRED — always pass a valid tenant_id
        actor_user_id: Optional[int] = None,
        target_user_id: Optional[int] = None
    ):
        """Append a record to the audit_logs table. tenant_id must always be valid."""
        log = AuditLog(
            actor_user_id=actor_user_id,
            action=action,
            target_user_id=target_user_id,
            tenant_id=tenant_id
        )
        db.add(log)
        db.commit()
