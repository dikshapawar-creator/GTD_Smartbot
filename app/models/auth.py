from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, text, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.session import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    api_key = Column(String(255), unique=True, nullable=True, index=True)
    domain = Column(String(255), unique=True, nullable=True, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=text("GETDATE()"))

    users = relationship("User", back_populates="tenant")
    roles = relationship("Role", back_populates="tenant")
    audit_logs = relationship("AuditLog", back_populates="tenant")
    user_tenants = relationship("UserTenant", back_populates="tenant")


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    description = Column(String(255), nullable=True)
    level = Column(Integer, nullable=False)  # 4: super_admin, 3: administrator, 2: admin, 1: sales
    created_at = Column(DateTime, server_default=text("GETDATE()"))

    tenant = relationship("Tenant", back_populates="roles")
    users = relationship("User", back_populates="role")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=True)
    password_hash = Column(String(255), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)  # Primary/default (backward compat)
    is_active = Column(Boolean, default=True)
    is_super_admin = Column(Boolean, default=False, server_default=text("0"))  # Super admin bypass
    token_version = Column(Integer, default=1)
    created_at = Column(DateTime, server_default=text("GETDATE()"))
    updated_at = Column(DateTime, nullable=True, onupdate=text("GETDATE()"))

    role = relationship("Role", back_populates="users")
    tenant = relationship("Tenant", back_populates="users")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    password_resets = relationship("PasswordReset", back_populates="user", cascade="all, delete-orphan")
    user_tenants = relationship("UserTenant", back_populates="user", cascade="all, delete-orphan")

    @property
    def tenant_access(self):
        """Helper to return a list of simplified tenant records."""
        return [
            {
                "tenant_id": ut.tenant_id,
                "tenant_name": ut.tenant.name if ut.tenant else str(ut.tenant_id),
                "status": ut.status,
                "is_primary": ut.is_primary,
            } for ut in (self.user_tenants or [])
        ]


class UserTenant(Base):
    """Maps users to their accessible tenants (multi-tenant per user)."""
    __tablename__ = "user_tenants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    status = Column(Boolean, default=True)       # 1=active, 0=inactive
    is_primary = Column(Boolean, default=False)  # marks default/primary tenant
    created_at = Column(DateTime, server_default=text("GETDATE()"))

    user = relationship("User", back_populates="user_tenants")
    tenant = relationship("Tenant", back_populates="user_tenants")

    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_user_tenant"),
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    token_hash = Column(String(255), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=text("GETDATE()"))

    user = relationship("User", back_populates="refresh_tokens")


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1)
    token_hash = Column(String(255), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=text("GETDATE()"))

    user = relationship("User", back_populates="password_resets")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_user_id = Column(Integer, nullable=True)
    action = Column(String(255), nullable=False)
    target_user_id = Column(Integer, nullable=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    created_at = Column(DateTime, server_default=text("GETDATE()"))

    tenant = relationship("Tenant", back_populates="audit_logs")
