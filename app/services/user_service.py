from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from typing import List
from uuid import UUID

from app.models.auth import User, Role
from app.core.security import get_password_hash, validate_password
from app.schemas.user import UserCreate
from app.services.audit_service import AuditService

class UserService:
    @staticmethod
    def create_user_hierarchical(db: Session, creator: User, user_in: UserCreate) -> User:
        """
        Rules:
        - administrator (3) can create any role.
        - admin (2) can create sales (1) only.
        - Must be same tenant.
        """
        # 1. Email check
        existing = db.query(User).filter(User.email == user_in.email).first()
        if existing:
            raise HTTPException(status_code=400, detail="User already exists")

        # 2. Role validation
        target_role = db.query(Role).filter(Role.name == user_in.role_name).first()
        if not target_role:
            raise HTTPException(status_code=400, detail="Invalid role")

        # 3. Hierarchy check
        if creator.role.level == 2: # Admin
            if target_role.level >= 2:
                AuditService.log_action(db, f"CREATE_USER_DENIED_HIERARCHY({user_in.email})", creator.tenant_id, actor_user_id=creator.id)
                raise HTTPException(status_code=403, detail="Admins can only create Sales accounts.")
        
        if creator.role.level < 2: # Sales
            raise HTTPException(status_code=403, detail="Sales users cannot create accounts.")

        # 4. Create User (Locked to creator's tenant)
        new_user = User(
            email=user_in.email,
            password_hash=get_password_hash(user_in.password),
            role_id=target_role.id,
            tenant_id=creator.tenant_id,
            is_active=True
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        AuditService.log_action(
            db, "USER_CREATED", creator.tenant_id, 
            actor_user_id=creator.id, target_user_id=new_user.id
        )
        return new_user

    @staticmethod
    def list_users(db: Session, tenant_id: int) -> List[User]:
        """Tenant isolation: Only results from same tenant."""
        return db.query(User).filter(User.tenant_id == tenant_id).all()

    @staticmethod
    def deactivate_user(db: Session, user_id: int, creator: User) -> bool:
        """
        Rules:
        - Only administrator (level 3)
        - Same tenant
        - Cannot deactivate self
        - Admin cannot deactivate higher/equal level? (Specific rule: Admin cannot deactivate administrator)
        """
        if creator.role.level < 3:
             raise HTTPException(status_code=403, detail="Only Administrators can deactivate users.")

        target = db.query(User).filter(User.id == user_id, User.tenant_id == creator.tenant_id).first()
        if not target:
            return False

        if target.id == creator.id:
            raise HTTPException(status_code=400, detail="You cannot deactivate yourself.")

        target.is_active = False
        db.commit()

        AuditService.log_action(
            db, "USER_DEACTIVATED", creator.tenant_id, 
            actor_user_id=creator.id, target_user_id=target.id
        )
        return True
