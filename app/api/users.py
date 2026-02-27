from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.dependencies import get_db
from app.api.deps import get_current_user, require_role
from app.models.auth import User
from app.schemas.user import UserCreate, UserUpdate, UserResponse
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["User Management"])

@router.post("/create", response_model=UserResponse)
def create_user(
    user_in: UserCreate, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(require_role(2)) # Min Level 2 (Admin)
):
    """
    Create a new user within YOUR tenant.
    - administrator (3) can create any role.
    - admin (2) can create sales (1) only.
    """
    return UserService.create_user_hierarchical(db, current_user, user_in)

@router.get("/", response_model=List[UserResponse])
def list_users(
    db: Session = Depends(get_db), 
    current_user: User = Depends(require_role(2)) # Admins can see their own tenant users
):
    """List users within your tenant."""
    return UserService.list_users(db, current_user.tenant_id)

@router.delete("/{id}")
def deactivate_user(
    id: int, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(require_role(3)) # Level 3: administrator only
):
    """
    Soft delete user within your tenant.
    - Only administrator.
    - Cannot deactivate self.
    """
    success = UserService.deactivate_user(db, id, current_user)
    if not success:
        raise HTTPException(status_code=404, detail="User not found in your tenant.")
    return {"message": "User successfully deactivated."}

@router.put("/{id}", response_model=UserResponse)
def update_user(
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
    return UserService.update_user(db, id, user_in, current_user)
