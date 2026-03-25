from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from typing import List
from app.core.dependencies import get_db
from app.api.deps import get_current_user, require_role, require_super_admin
from app.models.auth import User, UserTenant, Tenant
from app.schemas.user import (
    UserCreate, UserUpdate, UserResponse,
    AssignTenantsRequest, TenantStatusUpdate, UserTenantRead
)
from app.services.user_service import UserService
from app.services.user_tenant_service import UserTenantService

router = APIRouter(prefix="/users", tags=["User Management"])


@router.post("/create", response_model=UserResponse)
async def create_user(
    user_in: UserCreate, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(require_role(2))
):
    """
    Create a new user within YOUR tenant.
    - administrator (3) can create any role.
    - admin (2) can create sales (1) only.
    """
    new_user = UserService.create_user_hierarchical(db, current_user, user_in)
    
    # 🔥 Broadcast to CRM Dashboard
    from app.core.socket_manager import socket_manager
    await socket_manager.broadcast_event(
        "USER_CREATED",
        {
            "id": new_user.id,
            "full_name": new_user.full_name,
            "email": new_user.email,
            "role": new_user.role.name if new_user.role else "Unknown"
        },
        tenant_id=new_user.tenant_id
    )
    
    return new_user


@router.get("/", response_model=List[UserResponse])
def list_users(
    db: Session = Depends(get_db), 
    current_user: User = Depends(require_role(2))
):
    """List users. Super admins see all, admins see their own tenant."""
    query = db.query(User).options(
        joinedload(User.role),
        joinedload(User.user_tenants).joinedload(UserTenant.tenant)
    )
    
    # Super admins see everything; system admins see their bucket
    if not current_user.is_super_admin:
        query = query.filter(User.tenant_id == current_user.tenant_id)
        
    users = query.all()
    return users


@router.delete("/{id}")
async def deactivate_user(
    id: int, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(require_role(3))
):
    """
    Soft delete user within your tenant.
    - Only administrator.
    - Cannot deactivate self.
    """
    user = db.query(User).filter(User.id == id).first()
    target_tenant_id = user.tenant_id if user else None
    
    success = UserService.deactivate_user(db, id, current_user)
    if not success:
        raise HTTPException(status_code=404, detail="User not found in your tenant.")
    
    # 🔥 Broadcast to CRM Dashboard
    if target_tenant_id:
        from app.core.socket_manager import socket_manager
        await socket_manager.broadcast_event(
            "USER_DEACTIVATED",
            {"id": id},
            tenant_id=target_tenant_id
        )
        
    return {"message": "User successfully deactivated."}


@router.put("/{id}", response_model=UserResponse)
async def update_user(
    id: int,
    user_in: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(2))
):
    """
    Update a user. 
    - Admins (2) can change roles to Sales (1).
    - Administrators (3) can change any role.
    """
    updated_user = UserService.update_user(db, id, user_in, current_user)
    
    # 🔥 Broadcast to CRM Dashboard
    from app.core.socket_manager import socket_manager
    await socket_manager.broadcast_event(
        "USER_UPDATED",
        {
            "id": updated_user.id,
            "full_name": updated_user.full_name,
            "email": updated_user.email,
            "role": updated_user.role.name if updated_user.role else "Unknown"
        },
        tenant_id=updated_user.tenant_id
    )
    
    return updated_user


@router.post("/assign-tenants")
def assign_tenants(
    payload: AssignTenantsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin)
):
    """
    Assign or update tenant access for a user.
    Super Admin only.
    """
    rows = UserTenantService.assign_tenants(
        db,
        user_id=payload.user_id,
        tenant_ids=payload.tenant_ids,
        primary_tenant_id=payload.primary_tenant_id,
        actor_user_id=current_user.id
    )
    return {
        "message": f"Assigned {len(rows)} tenant(s) to user {payload.user_id}",
        "tenants": [
            {
                "tenant_id": r.tenant_id,
                "is_primary": r.is_primary,
                "status": r.status
            } for r in rows
        ]
    }


@router.patch("/tenant-status")
def set_tenant_status(
    payload: TenantStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin)
):
    """
    Activate or deactivate a user's access to a specific tenant.
    Super Admin only.
    """
    row = UserTenantService.set_tenant_status(
        db,
        user_id=payload.user_id,
        tenant_id=payload.tenant_id,
        status=payload.status,
        actor_id=current_user.id
    )
    action = "activated" if payload.status else "deactivated"
    return {
        "message": f"Tenant {payload.tenant_id} {action} for user {payload.user_id}",
        "status": row.status
    }
