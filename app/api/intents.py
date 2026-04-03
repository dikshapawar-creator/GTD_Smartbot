from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional, List
import logging
import json

from app.core.dependencies import get_db
from app.models.intent_config import IntentConfig
from app.schemas.intents import IntentConfigCreate, IntentConfigRead, IntentConfigUpdate
from app.api.deps import require_role
from app.models.auth import User
from app.core.tenant_resolver import TenantResolver
from app.core.db_utils import verify_tenant_access
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

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
        keywords=json.dumps(intent_in.keywords),  # Serialize list to JSON string for DB
        response_text=intent_in.response_text,
        metadata_json=json.dumps(intent_in.metadata_json) if intent_in.metadata_json else None,
        tenant_id=target_tenant_id
    )
    db.add(intent)
    db.commit()
    db.refresh(intent)
    
    # 🔥 Clear intent cache so bot picks up new data immediately
    from app.services.intent_service import intent_cache
    intent_cache.pop(target_tenant_id, None)
    logger.info(f"[INTENT] Cache cleared for tenant {target_tenant_id} after CREATE")

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
        if field == 'keywords' and isinstance(value, list):
            value = json.dumps(value)  # Serialize list to JSON string for DB
        elif field == 'metadata_json' and isinstance(value, dict):
            value = json.dumps(value)
        setattr(intent, field, value)
    
    db.commit()
    db.refresh(intent)

    # 🔥 Clear intent cache so bot picks up changes immediately
    from app.services.intent_service import intent_cache
    intent_cache.pop(target_tenant_id, None)
    logger.info(f"[INTENT] Cache cleared for tenant {target_tenant_id} after UPDATE")

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
    
    # 🔥 Clear intent cache so bot picks up deletion immediately
    from app.services.intent_service import intent_cache
    intent_cache.pop(target_tenant_id, None)
    logger.info(f"[INTENT] Cache cleared for tenant {target_tenant_id} after DELETE")

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


@router.post("/clone-from/{source_tenant_id}", status_code=status.HTTP_200_OK)
async def clone_intents_from_tenant(
    source_tenant_id: int,
    request: Request,
    overwrite: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(3))  # Admin+ only
):
    """
    Clone all intents from a source tenant to the current tenant.
    Used by 'Clone from Workspace' in the CRM Settings > Intents page.
    Set overwrite=true to replace existing intents with the same key.
    """
    target_tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)

    if source_tenant_id == target_tenant_id:
        raise HTTPException(status_code=400, detail="Source and target tenant must be different.")

    source_intents = db.query(IntentConfig).filter(
        IntentConfig.tenant_id == source_tenant_id,
        IntentConfig.is_active == True
    ).all()

    if not source_intents:
        raise HTTPException(status_code=404, detail=f"No active intents found for source tenant {source_tenant_id}.")

    created = 0
    skipped = 0
    overwritten = 0

    for src in source_intents:
        existing = db.query(IntentConfig).filter(
            IntentConfig.intent_key == src.intent_key,
            IntentConfig.tenant_id == target_tenant_id
        ).first()

        # Read clean keywords from source (CleanText already decoded it)
        raw_keywords = src.keywords  # Already clean string from CleanText decorator
        raw_metadata = src.metadata_json  # Already clean string

        if existing:
            if overwrite:
                existing.keywords = raw_keywords
                existing.response_text = src.response_text
                existing.metadata_json = raw_metadata
                existing.is_active = src.is_active
                overwritten += 1
            else:
                skipped += 1
            continue

        new_intent = IntentConfig(
            intent_key=src.intent_key,
            keywords=raw_keywords,
            response_text=src.response_text,
            metadata_json=raw_metadata,
            is_active=src.is_active,
            tenant_id=target_tenant_id
        )
        db.add(new_intent)
        created += 1

    db.commit()

    # Clear intent cache for target tenant
    from app.services.intent_service import intent_cache
    intent_cache.pop(target_tenant_id, None)

    AuditService.log_action(db, f"INTENTS_CLONED: from tenant {source_tenant_id} ({created} created, {overwritten} overwritten, {skipped} skipped)", target_tenant_id)

    logger.info(f"[INTENT] Cloned {created} intents from tenant {source_tenant_id} to {target_tenant_id} (overwritten={overwritten}, skipped={skipped})")

    return {
        "success": True,
        "created": created,
        "overwritten": overwritten,
        "skipped": skipped,
        "source_tenant_id": source_tenant_id,
        "target_tenant_id": target_tenant_id
    }
