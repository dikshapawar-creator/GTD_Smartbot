import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel, EmailStr

from app.core.dependencies import get_db
from app.models.auth import User
from app.api.deps import require_role
from app.models.email_config import EmailConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/email-config", tags=["Email Configuration"])

class EmailConfigUpdate(BaseModel):
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from_email: EmailStr
    smtp_from_name: str
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    confirmation_template: Optional[str] = None
    reset_password_template: Optional[str] = None

@router.get("/{tenant_id}")
def get_tenant_email_config(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(4)) # Super Admin only
):
    config = db.query(EmailConfig).filter(EmailConfig.tenant_id == tenant_id).first()
    if not config:
        # Return default or empty structure
        return {
            "tenant_id": tenant_id,
            "smtp_host": "",
            "smtp_port": 587,
            "smtp_user": "",
            "smtp_password": "",
            "smtp_from_email": "",
            "smtp_from_name": "Chatbot Support",
            "smtp_use_tls": True,
            "smtp_use_ssl": False,
            "confirmation_template": "",
            "reset_password_template": ""
        }
    return config

@router.put("/{tenant_id}")
def update_tenant_email_config(
    tenant_id: int,
    config_in: EmailConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(4))
):
    config = db.query(EmailConfig).filter(EmailConfig.tenant_id == tenant_id).first()
    
    if not config:
        config = EmailConfig(tenant_id=tenant_id)
        db.add(config)
    
    # Update fields from Pydantic model
    update_data = config_in.dict()
    for field, value in update_data.items():
        setattr(config, field, value)
    
    try:
        db.commit()
        db.refresh(config)
        return config
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update email config for tenant {tenant_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update configuration")
