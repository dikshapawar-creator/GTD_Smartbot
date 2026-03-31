from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.dependencies import get_db
from app.api.deps import get_current_user
from app.schemas.auth import LoginRequest, Token, RefreshRequest, ForgotPasswordRequest, ResetPasswordRequest
from app.schemas.auth_setup import AdminSetupRequest
from app.schemas.user import UserResponse
from app.services.auth_service import AuthService
from app.models.auth import User

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/setup-admin", response_model=UserResponse)
def setup_admin(req: AdminSetupRequest, db: Session = Depends(get_db)):
    """
    ONE-TIME BOOTSTRAP: Create first tenant and administrator.
    Only works if zero administrators exist in the entire database.
    """
    return AuthService.setup_admin(
        db, req.email, req.password, req.tenant_name, req.setup_token
    )

@router.post("/login")
def login(login_req: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate user. Returns access_token + refresh_token.
    
    Enterprise Flow:
    - Store access_token in memory (Redux/Context).
    - Store refresh_token in localStorage.
    - Use role/role_level to route to correct dashboard.
    - Call POST /auth/refresh when access_token expires (after expires_in seconds).
    """
    user = AuthService.authenticate_user(db, login_req.email, login_req.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token, refresh_token = AuthService.create_session(db, user)
    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60  # convert to seconds
    
    from app.models.auth import Tenant
    if user.is_super_admin:
        all_tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
        tenant_access = [
            {
                "tenant_id": t.id,
                "tenant_name": t.name,
                "status": t.is_active,
                "is_primary": t.id == user.tenant_id
            } for t in all_tenants
        ]
        tenant_ids = [t.id for t in all_tenants]
    else:
        tenant_access = [
            {
                "tenant_id": ut.tenant_id,
                "tenant_name": ut.tenant.name if ut.tenant else str(ut.tenant_id),
                "status": ut.status,
                "is_primary": ut.is_primary
            } for ut in user.user_tenants
        ] if user.user_tenants else []
        tenant_ids = [ut.tenant_id for ut in user.user_tenants if ut.status] if user.user_tenants else [user.tenant_id]

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.name,
            "role_level": user.role.level,
            "tenant_id": user.tenant_id,
            "tenant_ids": tenant_ids,
            "primary_tenant_id": next((ut.tenant_id for ut in user.user_tenants if ut.is_primary), user.tenant_id) if user.user_tenants else user.tenant_id,
            "is_super_admin": user.is_super_admin,
            "tenant_access": tenant_access
        }
    }

@router.post("/refresh")
def refresh(refresh_req: RefreshRequest, db: Session = Depends(get_db)):
    """
    Rotate tokens silently using a valid refresh token.
    Frontend should call this BEFORE the access_token expires (use expires_in).
    """
    access_token, new_refresh_token = AuthService.refresh_session(db, refresh_req.refresh_token)
    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    
    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "expires_in": expires_in,
    }

@router.post("/forgot-password")
def forgot_password(req: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Standard security: Always return Success message."""
    AuthService.forgot_password(db, req.email)
    return {"message": "If an account exists, a reset link has been sent to your email."}

@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset password and invalidate all existing JWTs by incrementing version."""
    AuthService.reset_password(db, req.token, req.new_password)
    return {"message": "Password successfully reset. Please log in with your new password."}

@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get current authenticated user's profile."""
    if current_user.is_super_admin:
        # Dynamically inject all active tenants for super admins
        from app.models.auth import Tenant, UserTenant
        all_tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
        
        # 🔄 BACKFILL: Ensure this Super Admin has a UserTenant record for EVERY active tenant
        for t in all_tenants:
            existing = db.query(UserTenant).filter(
                UserTenant.user_id == current_user.id,
                UserTenant.tenant_id == t.id
            ).first()
            if not existing:
                new_map = UserTenant(
                    user_id=current_user.id,
                    tenant_id=t.id,
                    status=True,
                    is_primary=(t.id == current_user.tenant_id)
                )
                db.add(new_map)
        db.commit()

        # We construct a dictionary matching UserResponse because we shouldn't mutate the db object's relationship
        user_dict = {
            "id": current_user.id,
            "email": current_user.email,
            "is_active": current_user.is_active,
            "full_name": current_user.full_name,
            "tenant_id": current_user.tenant_id,
            "is_super_admin": current_user.is_super_admin,
            "role": current_user.role,
            "token_version": current_user.token_version,
            "created_at": current_user.created_at,
            "updated_at": current_user.updated_at,
            "tenant_access": [
                {
                    "tenant_id": t.id,
                    "tenant_name": t.name,
                    "status": t.is_active,
                    "is_primary": t.id == current_user.tenant_id
                } for t in all_tenants
            ]
        }
        return user_dict
    
    return current_user
