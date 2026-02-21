from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, text
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime
from app.db.session import Base

class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=text("GETDATE()"))

    users = relationship("User", back_populates="tenant")
    audit_logs = relationship("AuditLog", back_populates="tenant")

class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)
    level = Column(Integer, nullable=False) # 3: administrator, 2: admin, 1: sales
    created_at = Column(DateTime, server_default=text("GETDATE()"))

    users = relationship("User", back_populates="role")

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    is_active = Column(Boolean, default=True)
    token_version = Column(Integer, default=1)
    created_at = Column(DateTime, server_default=text("GETDATE()"))
    updated_at = Column(DateTime, nullable=True, onupdate=text("GETDATE()"))

    role = relationship("Role", back_populates="users")
    tenant = relationship("Tenant", back_populates="users")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    password_resets = relationship("PasswordReset", back_populates="user", cascade="all, delete-orphan")

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String(255), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=text("GETDATE()"))

    user = relationship("User", back_populates="refresh_tokens")

class PasswordReset(Base):
    __tablename__ = "password_resets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String(255), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=text("GETDATE()"))

    user = relationship("User", back_populates="password_resets")

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_user_id = Column(Integer, nullable=True) # ID of user performing action
    action = Column(String(255), nullable=False)
    target_user_id = Column(Integer, nullable=True) # ID of affected user
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    created_at = Column(DateTime, server_default=text("GETDATE()"))

    tenant = relationship("Tenant", back_populates="audit_logs")
