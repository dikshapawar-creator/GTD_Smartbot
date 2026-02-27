import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.auth import User, Role, Tenant, RefreshToken, PasswordReset
from app.core.security import (
    get_password_hash, verify_password, hash_token,
    create_access_token, secure_compare
)
from app.core.config import settings
from app.services.audit_service import AuditService

import logging
logger = logging.getLogger(__name__)

# System tenant ID used for pre-tenant events (invalid token attempts only)
# The failed login is associated with tenant_id of the found user
SYSTEM_SENTINEL_TENANT_ID = None  # Only used for invalid-token bootstrap attempts

class AuthService:
    @staticmethod
    def setup_admin(db: Session, email: str, password: str, tenant_name: str, setup_token: str) -> User:
        """
        One-time bootstrap: Create first tenant and administrator.
        
        CORRECT ORDER:
        1. Validate setup_token (no audit log on failure - no tenant exists yet)
        2. Check if admin already exists (no audit log on failure - no tenant exists)
        3. Create Tenant
        4. Create Admin User
        5. Log BOOTSTRAP_SUCCESS with real tenant.id
        """
        # 1. Constant-time token verification — NO audit log, no tenant exists yet
        if not secure_compare(setup_token, settings.ADMIN_SETUP_TOKEN):
            raise HTTPException(status_code=403, detail="Invalid setup token")

        # 2. Prevent multi-bootstrap — NO audit log, we don't know which tenant to log to
        admin_role = db.query(Role).filter(Role.name == "administrator").first()
        if not admin_role:
            raise HTTPException(status_code=500, detail="Roles not initialized. Run seeder.")

        any_admin = db.query(User).filter(User.role_id == admin_role.id).first()
        if any_admin:
            raise HTTPException(status_code=403, detail="System already bootstrapped.")

        # 3. Create Tenant FIRST
        tenant = Tenant(name=tenant_name)
        db.add(tenant)
        db.commit()
        db.refresh(tenant)

        # 4. Create Admin User
        user = User(
            email=email,
            password_hash=get_password_hash(password),
            role_id=admin_role.id,
            tenant_id=tenant.id,
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # 5. Log audit WITH valid tenant.id (tenant now exists)
        AuditService.log_action(
            db, "BOOTSTRAP_SUCCESS",
            tenant_id=tenant.id,
            actor_user_id=user.id
        )
        return user

    @staticmethod
    def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
        user = db.query(User).filter(User.email == email, User.is_active == True).first()
        if not user or not verify_password(password, user.password_hash):
            # If user was found, log with their tenant, else skip audit log
            if user:
                AuditService.log_action(db, f"LOGIN_FAILED", user.tenant_id, actor_user_id=user.id)
            # No audit log for unknown email — no valid tenant_id available
            return None
        return user

    @staticmethod
    def create_session(db: Session, user: User) -> Tuple[str, str]:
        access_token = create_access_token(
            user_id=user.id,
            email=user.email,
            role_name=user.role.name,
            role_level=user.role.level,
            tenant_id=user.tenant_id,
            token_version=user.token_version
        )
        refresh_token = secrets.token_urlsafe(64)

        db_token = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh_token),
            expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        )
        db.add(db_token)
        db.commit()

        AuditService.log_action(db, "LOGIN_SUCCESS", user.tenant_id, actor_user_id=user.id)
        return access_token, refresh_token

    @staticmethod
    def refresh_session(db: Session, refresh_token: str) -> Tuple[str, str]:
        token_hash = hash_token(refresh_token)
        db_token = db.query(RefreshToken).filter(
            RefreshToken.token_hash == token_hash,
            RefreshToken.expires_at > datetime.utcnow(),
            RefreshToken.is_revoked == False
        ).first()

        if not db_token:
            logger.warning(f"Refresh failed: Token hash {token_hash} not found or invalid.")
            raise HTTPException(status_code=401, detail="Invalid session")

        user = db_token.user
        if not user.is_active:
            raise HTTPException(status_code=403, detail="User deactivated")

        # Rotate tokens
        db_token.is_revoked = True
        db.commit()

        return AuthService.create_session(db, user)

    @staticmethod
    def forgot_password(db: Session, email: str):
        """Standard behavior: Always return Success."""
        user = db.query(User).filter(User.email == email, User.is_active == True).first()
        if user:
            # Revoke any previous unused tokens for this user
            db.query(PasswordReset).filter(
                PasswordReset.user_id == user.id,
                PasswordReset.is_used == False
            ).update({"is_used": True}) # Marking as used effectively revokes it

            raw_token = secrets.token_urlsafe(32)
            db_reset = PasswordReset(
                user_id=user.id,
                token_hash=hash_token(raw_token),
                expires_at=datetime.utcnow() + timedelta(minutes=15)
            )
            db.add(db_reset)
            db.commit()
            # MOCK EMAIL: In real app, call mailer(email, raw_token)
            print(f"MOCK EMAIL to {email}: Reset token is {raw_token}")
            AuditService.log_action(db, "PASSWORD_RESET_REQUESTED", user.tenant_id, actor_user_id=user.id)
        # Unknown email: silently ignore, do NOT log (no valid tenant_id)

    @staticmethod
    def reset_password(db: Session, token: str, new_password: str) -> bool:
        t_hash = hash_token(token)
        reset_req = db.query(PasswordReset).filter(
            PasswordReset.token_hash == t_hash
        ).first()

        if not reset_req:
            raise HTTPException(status_code=400, detail="Invalid reset token. Please request a new one.")

        if reset_req.is_used:
             raise HTTPException(status_code=400, detail="This token has already been used.")

        if reset_req.expires_at < datetime.utcnow():
             raise HTTPException(status_code=400, detail="Reset token has expired. Please request a new one.")

        user = reset_req.user
        user.password_hash = get_password_hash(new_password)
        user.token_version += 1  # Invalidate all existing JWTs
        reset_req.is_used = True

        # Revoke all refresh tokens
        db.query(RefreshToken).filter(RefreshToken.user_id == user.id).update({"is_revoked": True})
        db.commit()

        AuditService.log_action(db, "PASSWORD_RESET_SUCCESS", user.tenant_id, actor_user_id=user.id)
        return True
