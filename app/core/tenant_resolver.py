import logging
from typing import Optional, List
from fastapi import Request, HTTPException, status
from sqlalchemy.orm import Session
from app.models.auth import Tenant, UserTenant, User
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

class TenantResolver:
    @staticmethod
    def resolve_public_tenant(db: Session, request: Request) -> int:
        """
        Resolves tenant_id for public/iframe endpoints using tenant_key or api_key.
        Strict validation: No default fallbacks.
        """
        tenant_key = (
            request.query_params.get("tenant_key") or 
            request.query_params.get("key") or 
            request.headers.get("tenant-key") or 
            request.headers.get("X-Tenant-Key")
        )
        api_key = request.headers.get("x-api-key") or request.query_params.get("api_key")
        
        tenant_id = None

        if tenant_key:
            tenant = db.query(Tenant).filter(Tenant.tenant_key == tenant_key, Tenant.is_active == True).first()
            if tenant:
                tenant_id = tenant.id
            else:
                logger.warning(f"Invalid tenant_key attempt: {tenant_key}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, 
                    detail="Invalid or missing tenant context."
                )

        elif api_key:
            tenant = TenantService.get_tenant_by_api_key(db, api_key)
            if tenant:
                tenant_id = tenant.id
            else:
                logger.warning(f"Invalid api_key attempt: {api_key}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, 
                    detail="Invalid API key."
                )

        if not tenant_id:
            logger.error(f"Tenant resolution failed for public path: {request.url.path}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="Tenant context required."
            )
            
        return tenant_id

    @staticmethod
    def resolve_admin_tenant(db: Session, request: Request, current_user: User) -> int:
        """
        Resolves tenant_id for admin/CRM endpoints.
        Enforces user-tenant mapping constraints.
        """
        # 1. Super Admin override
        requested_tid = request.headers.get("X-Tenant-ID") or request.query_params.get("tenant_id")
        
        is_super = getattr(current_user, 'is_super_admin', False) or getattr(current_user, '_jwt_is_super_admin', False)
        jwt_authorized_ids = getattr(current_user, '_jwt_tenant_ids', [])
        
        if requested_tid:
            try:
                target_id = int(requested_tid)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid Tenant ID format")

            # Check mapping if not super admin
            if not is_super:
                if target_id not in jwt_authorized_ids:
                    # Double check DB in case JWT is slightly stale
                    mapping = db.query(UserTenant).filter(
                        UserTenant.user_id == current_user.id,
                        UserTenant.tenant_id == target_id,
                        UserTenant.status == True
                    ).first()
                    if not mapping:
                        logger.warning(f"User {current_user.id} attempted unauthorized access to tenant {target_id}")
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Access denied for this workspace."
                        )
            return target_id

        # 2. Fallback to Primary Tenant from JWT or User record
        primary_tid = getattr(current_user, '_jwt_primary_tenant_id', current_user.tenant_id)
        return primary_tid
