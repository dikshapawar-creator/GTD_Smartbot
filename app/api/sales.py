from fastapi import APIRouter, Depends
from app.api.deps import require_role
from app.models.auth import User

router = APIRouter(prefix="/sales", tags=["Sales CRM Access"])

@router.get("/leads-overview")
def get_sales_leads(current_user: User = Depends(require_role(1))):
    """
    Access point for Sales role.
    Note: 'administrator' bypasses this too.
    """
    return {
        "message": f"Welcome Sales Team, {current_user.email}",
        "action_items": [
            "Follow up with 5 new trade leads",
            "Update CRM status for qualified prospects"
        ]
    }
