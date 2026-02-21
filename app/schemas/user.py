from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
from datetime import datetime
from app.core.security import validate_password

class UserBase(BaseModel):
    email: EmailStr
    is_active: Optional[bool] = True

class UserCreate(UserBase):
    password: str
    role_name: str # administrator, admin, sales

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

class RoleResponse(BaseModel):
    id: int
    name: str
    level: int
    class Config:
        from_attributes = True

class UserResponse(UserBase):
    id: int
    tenant_id: int
    role: RoleResponse
    token_version: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class TenantResponse(BaseModel):
    id: int
    name: str
    is_active: bool
    created_at: datetime
    class Config:
        from_attributes = True
