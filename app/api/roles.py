from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.dependencies import get_db
from app.api.deps import require_role
from app.models.auth import Role, User
from app.schemas.role import RoleCreate, RoleUpdate, RoleResponse

router = APIRouter(prefix="/roles", tags=["Role Management"])

@router.get("/", response_model=List[RoleResponse])
def list_roles(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(2)) # Admins can list roles
):
    """List all available roles."""
    return db.query(Role).all()

@router.post("/", response_model=RoleResponse)
def create_role(
    role_in: RoleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(3)) # Only SuperAdmin can create roles
):
    """Create a new role."""
    existing = db.query(Role).filter(Role.name == role_in.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Role already exists")
    
    new_role = Role(**role_in.model_dump())
    db.add(new_role)
    db.commit()
    db.refresh(new_role)
    return new_role

@router.put("/{id}", response_model=RoleResponse)
def update_role(
    id: int,
    role_in: RoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(3))
):
    """Update role metadata."""
    role = db.query(Role).filter(Role.id == id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    if role_in.name and role_in.name != role.name:
        existing = db.query(Role).filter(Role.name == role_in.name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Role name already exists")
            
    update_data = role_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(role, key, value)
    
    try:
        db.commit()
        db.refresh(role)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Database error occurred.")
        
    return role

@router.delete("/{id}")
def delete_role(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(3))
):
    """Delete a role if not assigned to any user."""
    role = db.query(Role).filter(Role.id == id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    # Check if role is assigned
    user_count = db.query(User).filter(User.role_id == id).count()
    if user_count > 0:
        raise HTTPException(status_code=400, detail="Cannot delete role assigned to users")
    
    db.delete(role)
    db.commit()
    return {"message": "Role deleted successfully"}
