from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional, List

from app.core.dependencies import get_db
from app.models.intent_config import IntentConfig
from app.schemas.intents import IntentConfigCreate, IntentConfigRead, IntentConfigUpdate
from app.api.deps import require_role
from app.models.auth import User
from app.core.tenant_resolver import TenantResolver
from app.core.db_utils import verify_tenant_access
from app.services.audit_service import AuditService


router = APIRouter(prefix="/intents", tags=["Intent Management"])

@router.get("/", response_model=List[IntentConfigRead])
def list_intents(
    request: Request,
    db: Session = Depends(get_db), 
    current_user: User = Depends(require_role(2))
):
    """List all intent configurations. Tenant is resolved securely via headers/token."""
    target_tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)
    
    return db.query(IntentConfig).filter(IntentConfig.tenant_id == target_tenant_id).all()


@router.get("/{intent_key}", response_model=IntentConfigRead)
def get_intent(
    intent_key: str, 
    request: Request,
    db: Session = Depends(get_db), 
    current_user: User = Depends(require_role(2))
):
    """Retrieve a specific intent. Tenant is resolved securely via headers/token."""
    target_tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)

    intent = db.query(IntentConfig).filter(
        IntentConfig.intent_key == intent_key,
        IntentConfig.tenant_id == target_tenant_id
    ).first()
    if not intent:
        raise HTTPException(status_code=404, detail=f"Intent '{intent_key}' not found")
    return intent

@router.post("/", response_model=IntentConfigRead, status_code=status.HTTP_201_CREATED)
async def create_intent(
    intent_in: IntentConfigCreate, 
    request: Request,
    db: Session = Depends(get_db), 
    current_user: User = Depends(require_role(2))
):
    """Create a new intent configuration. Tenant is resolved securely via headers/token."""
    target_tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)

    existing = db.query(IntentConfig).filter(
        IntentConfig.intent_key == intent_in.intent_key,
        IntentConfig.tenant_id == target_tenant_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Intent '{intent_in.intent_key}' already exists for this tenant")
    
    intent = IntentConfig(
        intent_key=intent_in.intent_key,
        keywords=intent_in.keywords,
        response_text=intent_in.response_text,
        metadata_json=intent_in.metadata_json,
        tenant_id=target_tenant_id
    )
    db.add(intent)
    db.commit()
    db.refresh(intent)
    
    # 🔥 Audit Log
    AuditService.log_action(db, f"INTENT_CREATED: {intent.intent_key}", target_tenant_id)


    # 🔥 Broadcast to CRM Dashboard
    from app.core.socket_manager import socket_manager
    await socket_manager.broadcast_event(
        "INTENT_CREATED",
        {
            "id": intent.id,
            "intent_key": intent.intent_key,
            "intent_name": intent.intent_key # IntentConfig doesn't have intent_name, using key
        },
        tenant_id=target_tenant_id
    )

    return intent

@router.patch("/{intent_key}", response_model=IntentConfigRead)
async def update_intent(
    intent_key: str, 
    intent_in: IntentConfigUpdate, 
    request: Request,
    db: Session = Depends(get_db), 
    current_user: User = Depends(require_role(2))
):
    """Update an existing intent. Tenant is resolved securely via headers/token."""
    target_tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)

    intent = db.query(IntentConfig).filter(
        IntentConfig.intent_key == intent_key,
        IntentConfig.tenant_id == target_tenant_id
    ).first()
    if not intent:
        raise HTTPException(status_code=404, detail=f"Intent '{intent_key}' not found")
    
    update_data = intent_in.model_dump(exclude_unset=True)
    
    # Uniqueness check for intent_key rename
    if "intent_key" in update_data and update_data["intent_key"] != intent.intent_key:
        collision = db.query(IntentConfig).filter(
            IntentConfig.intent_key == update_data["intent_key"],
            IntentConfig.tenant_id == target_tenant_id
        ).first()
        if collision:
            raise HTTPException(
                status_code=400, 
                detail=f"Intent key '{update_data['intent_key']}' already exists for this tenant."
            )

    for field, value in update_data.items():
        setattr(intent, field, value)
    
    db.commit()
    db.refresh(intent)

    # 🔥 Broadcast to CRM Dashboard
    from app.core.socket_manager import socket_manager
    await socket_manager.broadcast_event(
        "INTENT_UPDATED",
        {
            "id": intent.id,
            "intent_key": intent.intent_key,
            "intent_name": intent.intent_key
        },
        tenant_id=target_tenant_id
    )

    return intent

@router.delete("/{intent_key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_intent(
    intent_key: str, 
    request: Request,
    db: Session = Depends(get_db), 
    current_user: User = Depends(require_role(2))
):
    """Delete an intent. Tenant is resolved securely via headers/token."""
    target_tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)

    intent = db.query(IntentConfig).filter(
        IntentConfig.intent_key == intent_key,
        IntentConfig.tenant_id == target_tenant_id
    ).first()
    if not intent:
        raise HTTPException(status_code=404, detail=f"Intent '{intent_key}' not found")
    
    intent_id = intent.id
    intent_name = intent.intent_key
    db.delete(intent)
    db.commit()
    
    # 🔥 Audit Log
    AuditService.log_action(db, f"INTENT_DELETED: {intent_name}", target_tenant_id)


    # 🔥 Broadcast to CRM Dashboard
    from app.core.socket_manager import socket_manager
    await socket_manager.broadcast_event(
        "INTENT_DELETED",
        {"id": intent_id, "intent_key": intent_key},
        tenant_id=target_tenant_id
    )

    return None
