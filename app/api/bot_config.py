import os
import uuid
import logging
from typing import Optional
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.config import settings
from app.api.deps import require_role
from app.models.auth import User
from app.models.bot_config import BotConfig
from app.schemas.bot_config import BotConfigResponse, BotConfigUpdate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Bot Configuration"])

# ── Directory for uploaded logos ──────────────────────────────────────
LOGO_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "logos")
os.makedirs(LOGO_DIR, exist_ok=True)


def _get_or_create_config(db: Session, tenant_id: int) -> BotConfig:
    """Get existing config or create default for tenant."""
    config = db.query(BotConfig).filter(BotConfig.tenant_id == tenant_id).first()
    if not config:
        config = BotConfig(
            tenant_id=tenant_id,
            chatbot_name="GTD Support",
            chatbot_logo_url="/logo.png",
            fab_tooltip="Trade Support",
            welcome_text="Welcome to GTD Service."
        )
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


@router.get("/bot-config", response_model=BotConfigResponse)
def get_bot_config(
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    Public endpoint to fetch chatbot branding configuration.
    Accepts tenant_id to support multiple websites.
    """
    target_tenant_id = tenant_id if tenant_id is not None else settings.DEFAULT_TENANT_ID
    logger.info(f"Fetching bot config for tenant: {target_tenant_id}")
    
    config = db.query(BotConfig).filter(BotConfig.tenant_id == target_tenant_id).first()
    if not config:
        # Fallback to default tenant if specific one not found
        config = db.query(BotConfig).filter(BotConfig.tenant_id == settings.DEFAULT_TENANT_ID).first()
        
    if not config:
        raise HTTPException(status_code=404, detail="Bot configuration not found")
    return BotConfigResponse.model_validate(config)


@router.put("/admin/bot-config", response_model=BotConfigResponse)
def update_bot_config(
    payload: BotConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(2))
):
    """Admin-only: Update chatbot name, logo URL, tooltip, or welcome text."""
    config = _get_or_create_config(db, current_user.tenant_id)

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(config, field, value)

    db.commit()
    db.refresh(config)
    logger.info(f"BotConfig updated by user {current_user.id}: {update_data}")
    return BotConfigResponse.model_validate(config)


@router.post("/admin/bot-config/upload-logo")
async def upload_bot_logo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(2))
):
    """Admin-only: Upload a logo image. Saves to static/logos/ and updates config."""
    # Validate file type
    allowed_types = {"image/png", "image/jpeg", "image/svg+xml", "image/webp", "image/gif"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"File type '{file.content_type}' not allowed. Use PNG, JPG, SVG, WebP, or GIF.")

    # Generate unique filename
    ext = os.path.splitext(file.filename or "logo.png")[1] or ".png"
    filename = f"chatbot_logo_{current_user.tenant_id}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = os.path.join(LOGO_DIR, filename)

    # Save file
    contents = await file.read()
    with open(filepath, "wb") as f:
        f.write(contents)

    # Update config with the served URL
    logo_url = f"/static/logos/{filename}"
    config = _get_or_create_config(db, current_user.tenant_id)
    config.chatbot_logo_url = logo_url
    db.commit()
    db.refresh(config)

    logger.info(f"Logo uploaded by user {current_user.id}: {logo_url}")
    return {"logo_url": logo_url, "message": "Logo uploaded successfully"}
