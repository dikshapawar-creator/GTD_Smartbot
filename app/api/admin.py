from fastapi import APIRouter, Depends
from app.api.deps import require_role
from app.models.auth import User

router = APIRouter(prefix="/admin", tags=["Administration (High Privilege)"])

@router.get("/dashboard")
def get_admin_dashboard(current_user: User = Depends(require_role(2))):
    """
    Access point for Administrators and Admins.
    Note: 'administrator' bypasses this specifically in our require_role dependency.
    """
    return {
        "message": f"Welcome to the Admin Dashboard, {current_user.email}",
        "role": current_user.role.name,
        "privileged_data": "Top secret enterprise trade metrics"
    }

@router.get("/system-stats")
def get_system_stats(current_user: User = Depends(require_role(3))):
    """
    Access point restricted ONLY to 'administrator'.
    """
    return {
        "status": "operational",
        "load": "0.45",
        "database": "connected (MSSQL)"
    }
