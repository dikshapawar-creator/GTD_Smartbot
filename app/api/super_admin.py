"""
Super Admin API — GTT Smartbot v5.x
Only accessible to users with is_super_admin=True.
Provides cross-tenant user and tenant management.
"""
import secrets
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_db
from app.api.deps import require_super_admin
from app.models.auth import User, Role, Tenant, UserTenant
from app.schemas.user import (
    SuperAdminUserCreate, SuperAdminTenantCreate,
    TenantResponse, UserResponse, TenantUpdate
)
from app.core.security import get_password_hash, validate_password, generate_tenant_key
from app.services.user_tenant_service import UserTenantService
from app.services.audit_service import AuditService

router = APIRouter(prefix="/super-admin", tags=["Super Admin"])


@router.post("/create-tenant", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
def create_tenant(
    payload: SuperAdminTenantCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin)
):
    """Create a new tenant. Super Admin only."""
    # Check domain uniqueness
    if payload.domain:
        existing = db.query(Tenant).filter(Tenant.domain == payload.domain).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Domain '{payload.domain}' already exists")

    api_key = payload.api_key or secrets.token_urlsafe(32)
    # 🧪 Automated Short Key Generation
    tenant_key = generate_tenant_key(length=8)

    tenant = Tenant(
        name=payload.name,
        tenant_key=tenant_key,
        domain=payload.domain,
        api_key=api_key,
        is_active=True
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    # 🔄 Auto-assign ALL Super Admins to the new tenant
    # This ensures it shows up in their workspace switcher immediately.
    super_admins = db.query(User).filter(User.is_super_admin == True).all()
    for admin in super_admins:
        # Check if already assigned (unlikely but safe)
        existing_assignment = db.query(UserTenant).filter(
            UserTenant.user_id == admin.id,
            UserTenant.tenant_id == tenant.id
        ).first()
        
        if not existing_assignment:
            assignment = UserTenant(
                user_id=admin.id,
                tenant_id=tenant.id,
                status=True,
                is_primary=False
            )
            db.add(assignment)
    
    db.commit()

    AuditService.log_action(
        db, f"TENANT_CREATED({tenant.name})",
        tenant.id, actor_user_id=current_user.id
    )
    return tenant


@router.patch("/tenants/{tenant_id}", response_model=TenantResponse)
def update_tenant(
    tenant_id: int,
    payload: TenantUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin)
):
    """Update tenant details (e.g. is_active). Super Admin only."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if payload.name is not None: tenant.name = payload.name
    if payload.domain is not None: tenant.domain = payload.domain
    if payload.is_active is not None: tenant.is_active = payload.is_active

    db.commit()
    db.refresh(tenant)

    AuditService.log_action(
        db, f"TENANT_UPDATED({tenant.name}, active={tenant.is_active})",
        tenant.id, actor_user_id=current_user.id
    )
    return tenant


@router.post("/create-user", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user_multi_tenant(
    payload: SuperAdminUserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin)
):
    """
    Create a user assigned to multiple tenants in one request. Super Admin only.
    - Creates the user with primary_tenant_id as their users.tenant_id
    - Populates user_tenants for all provided tenant_ids
    """
    # Validate email uniqueness
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Validate role by name
    role = db.query(Role).filter(Role.name == payload.role_name).first()
    if not role:
        raise HTTPException(status_code=400, detail=f"Invalid role name: {payload.role_name}")

    # Validate primary tenant exists
    primary_tenant = db.query(Tenant).filter(
        Tenant.id == payload.primary_tenant_id, Tenant.is_active == True
    ).first()
    if not primary_tenant:
        raise HTTPException(status_code=400, detail="Primary tenant not found or inactive")

    # Validate primary_tenant_id is in tenant_ids
    if payload.primary_tenant_id not in payload.tenant_ids:
        raise HTTPException(status_code=400, detail="primary_tenant_id must be included in tenant_ids")

    new_user = User(
        email=payload.email,
        full_name=payload.full_name,
        password_hash=get_password_hash(payload.password),
        role_id=role.id,
        tenant_id=payload.primary_tenant_id,  # primary for backward compat
        is_active=True,
        is_super_admin=False
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Assign all tenants
    UserTenantService.assign_tenants(
        db,
        user_id=new_user.id,
        tenant_ids=payload.tenant_ids,
        primary_tenant_id=payload.primary_tenant_id,
        actor_user_id=current_user.id
    )

    AuditService.log_action(
        db, f"SUPER_ADMIN_USER_CREATED({new_user.email},tenants={payload.tenant_ids})",
        payload.primary_tenant_id, actor_user_id=current_user.id
    )

    db.refresh(new_user)
    return new_user


@router.get("/tenants", response_model=List[TenantResponse])
def list_all_tenants(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin)
):
    """List all tenants in the system. Super Admin only."""
    return db.query(Tenant).order_by(Tenant.created_at.desc()).all()


@router.get("/users", response_model=List[UserResponse])
def list_all_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin)
):
    """List all users across all tenants. Super Admin only."""
    return db.query(User).all()
