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

        # 4. Create User (Legacy tenant_id = creator's or primary)
        primary_tid = user_in.tenant_ids[0] if user_in.tenant_ids else creator.tenant_id
        new_user = User(
            email=user_in.email,
            password_hash=get_password_hash(user_in.password),
            role_id=target_role.id,
            tenant_id=primary_tid,
            is_active=True
        )
        db.add(new_user)
        db.flush() # Get ID for mapping
        
        # 5. Assign Tenants via UserTenantService
        from app.services.user_tenant_service import UserTenantService
        t_ids = user_in.tenant_ids or [creator.tenant_id]
        UserTenantService.assign_tenants(
            db, 
            user_id=new_user.id, 
            tenant_ids=t_ids,
            primary_tenant_id=primary_tid,
            actor_user_id=creator.id
        )

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
        - Must be same tenant
        - Cannot deactivate self
        - Hierarchy: Can only deactivate users with a LOWER role level than yours.
        - Level 3 (Administrator) can deactivate Level 2 and Below.
        - Level 2 (Manager) can deactivate Level 1.
        """
        target = db.query(User).filter(User.id == user_id, User.tenant_id == creator.tenant_id).first()
        if not target:
            return False

        if target.id == creator.id:
            raise HTTPException(status_code=400, detail="You cannot deactivate yourself.")

        # Hierarchy Check
        if creator.role.level < 3: # Not a super admin
            if target.role.level >= creator.role.level:
                raise HTTPException(
                    status_code=403, 
                    detail="Access denied: You can only deactivate users with a lower role level than yours."
                )
        
        # Level 2 minimum required to deactivate anyone
        if creator.role.level < 2:
            raise HTTPException(status_code=403, detail="Sales roles cannot deactivate users.")

        target.is_active = False
        db.commit()

        AuditService.log_action(
            db, "USER_DEACTIVATED", creator.tenant_id, 
            actor_user_id=creator.id, target_user_id=target.id
        )
        return True

    @staticmethod
    def update_user(db: Session, user_id: int, user_in: any, creator: User) -> User:
        """
        Partial update for users.
        - Hierarchical checks for role changes.
        """
        target = db.query(User).filter(User.id == user_id, User.tenant_id == creator.tenant_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")

        # 1. Role Change Validation
        if user_in.role_name:
            target_role = db.query(Role).filter(Role.name == user_in.role_name).first()
            if not target_role:
                raise HTTPException(status_code=400, detail="Invalid role")
            
            # Hierarchy: Admin (2) cannot create/promote to Admin (2) or Administrator (3)
            if creator.role.level == 2 and target_role.level >= 2:
                raise HTTPException(status_code=403, detail="Admins can only assign Sales roles.")
            
            target.role_id = target_role.id

        # 2. Other Fields
        if user_in.is_active is not None:
            if target.id == creator.id and user_in.is_active is False:
                raise HTTPException(status_code=400, detail="Cannot deactivate self")
            target.is_active = user_in.is_active

        db.commit()
        db.refresh(target)
        
        AuditService.log_action(
            db, "USER_UPDATED", creator.tenant_id,
            actor_user_id=creator.id, target_user_id=target.id
        )
        return target
