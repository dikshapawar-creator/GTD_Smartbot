from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, List
from datetime import datetime
from app.core.security import validate_password


class UserBase(BaseModel):
    email: EmailStr
    is_active: Optional[bool] = True


class UserCreate(UserBase):
    password: str
    role_name: str

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        if not validate_password(v):
            raise ValueError(
                "Password must be 8+ chars, include upper, lower, number, and special character."
            )
        return v


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None
    role_name: Optional[str] = None


class RoleResponse(BaseModel):
    id: int
    name: str
    level: int
    class Config:
        from_attributes = True


class UserTenantRead(BaseModel):
    """Per-tenant access record returned with user data."""
    tenant_id: int
    tenant_name: str
    status: bool
    is_primary: bool
    class Config:
        from_attributes = True


class UserResponse(UserBase):
    id: int
    tenant_id: int
    full_name: Optional[str] = None
    is_super_admin: bool = False
    role: RoleResponse
    token_version: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    tenant_access: Optional[List[UserTenantRead]] = []

    class Config:
        from_attributes = True


class TenantResponse(BaseModel):
    id: int
    name: str
    domain: Optional[str] = None
    api_key: Optional[str] = None
    is_active: bool
    created_at: datetime
    class Config:
        from_attributes = True


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    is_active: Optional[bool] = None


# ── Super Admin User Creation ─────────────────────────────────────────

class SuperAdminUserCreate(BaseModel):
    """Payload for super admin creating a user across multiple tenants."""
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    role_name: str
    tenant_ids: List[int]
    primary_tenant_id: int

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        if not validate_password(v):
            raise ValueError(
                "Password must be 8+ chars, include upper, lower, number, and special character."
            )
        return v


class SuperAdminTenantCreate(BaseModel):
    """Payload for super admin creating a new tenant."""
    name: str
    domain: Optional[str] = None
    api_key: Optional[str] = None


# ── Tenant Assignment ─────────────────────────────────────────────────

class AssignTenantsRequest(BaseModel):
    user_id: int
    tenant_ids: List[int]
    primary_tenant_id: int


class TenantStatusUpdate(BaseModel):
    user_id: int
    tenant_id: int
    status: bool  # True=active, False=inactive
