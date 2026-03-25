from sqlalchemy.orm import Session
from fastapi import HTTPException
from typing import List, Optional
from datetime import datetime

from app.models.auth import User, UserTenant, Tenant
from app.services.audit_service import AuditService


class UserTenantService:

    @staticmethod
    def assign_tenants(
        db: Session,
        user_id: int,
        tenant_ids: List[int],
        primary_tenant_id: int,
        actor_user_id: int = None
    ) -> List[UserTenant]:
        """
        Upsert user_tenants rows for a user.
        Sets is_primary for the designated primary tenant.
        """
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        for tid in tenant_ids:
            tenant = db.query(Tenant).filter(Tenant.id == tid, Tenant.is_active == True).first()
            if not tenant:
                raise HTTPException(status_code=400, detail=f"Tenant {tid} not found or inactive")

            existing = db.query(UserTenant).filter(
                UserTenant.user_id == user_id,
                UserTenant.tenant_id == tid
            ).first()

            if existing:
                existing.status = True
                existing.is_primary = (tid == primary_tenant_id)
            else:
                db.add(UserTenant(
                    user_id=user_id,
                    tenant_id=tid,
                    status=True,
                    is_primary=(tid == primary_tenant_id)
                ))

        # Ensure primary tenant flag is only on the right row
        db.query(UserTenant).filter(
            UserTenant.user_id == user_id,
            UserTenant.tenant_id != primary_tenant_id
        ).update({"is_primary": False})

        db.commit()

        if actor_user_id:
            AuditService.log_action(
                db, f"TENANTS_ASSIGNED(user={user_id},tenants={tenant_ids})",
                primary_tenant_id, actor_user_id=actor_user_id
            )

        return db.query(UserTenant).filter(UserTenant.user_id == user_id).all()

    @staticmethod
    def get_active_tenants(db: Session, user_id: int) -> List[UserTenant]:
        return db.query(UserTenant).filter(
            UserTenant.user_id == user_id,
            UserTenant.status == True
        ).all()

    @staticmethod
    def set_tenant_status(
        db: Session,
        user_id: int,
        tenant_id: int,
        status: bool,
        actor_id: int = None
    ) -> UserTenant:
        row = db.query(UserTenant).filter(
            UserTenant.user_id == user_id,
            UserTenant.tenant_id == tenant_id
        ).first()
        if not row:
            raise HTTPException(status_code=404, detail="User-tenant mapping not found")

        row.status = status
        db.commit()
        db.refresh(row)

        if actor_id:
            action = "TENANT_ACTIVATED" if status else "TENANT_DEACTIVATED"
            AuditService.log_action(
                db, f"{action}(user={user_id},tenant={tenant_id})",
                tenant_id, actor_user_id=actor_id
            )
        return row
