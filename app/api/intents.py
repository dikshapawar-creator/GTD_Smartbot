from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_db
from app.models.intent_config import IntentConfig
from app.schemas.intents import IntentConfigCreate, IntentConfigRead, IntentConfigUpdate

router = APIRouter(prefix="/intents", tags=["Intent Management"])

@router.get("/", response_model=List[IntentConfigRead])
def list_intents(db: Session = Depends(get_db)):
    """List all intent configurations."""
    return db.query(IntentConfig).all()

@router.get("/{intent_key}", response_model=IntentConfigRead)
def get_intent(intent_key: str, db: Session = Depends(get_db)):
    """Retrieve a specific intent by its unique key."""
    intent = db.query(IntentConfig).filter(IntentConfig.intent_key == intent_key).first()
    if not intent:
        raise HTTPException(status_code=404, detail=f"Intent '{intent_key}' not found")
    return intent

@router.post("/", response_model=IntentConfigRead, status_code=status.HTTP_201_CREATED)
def create_intent(intent_in: IntentConfigCreate, db: Session = Depends(get_db)):
    """Create a new intent configuration."""
    existing = db.query(IntentConfig).filter(IntentConfig.intent_key == intent_in.intent_key).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Intent '{intent_in.intent_key}' already exists")
    
    intent = IntentConfig(
        intent_key=intent_in.intent_key,
        keywords=intent_in.keywords,
        response_text=intent_in.response_text,
        metadata_json=intent_in.metadata_json
    )
    db.add(intent)
    db.commit()
    db.refresh(intent)
    return intent

@router.patch("/{intent_key}", response_model=IntentConfigRead)
def update_intent(intent_key: str, intent_in: IntentConfigUpdate, db: Session = Depends(get_db)):
    """Update an existing intent configuration."""
    intent = db.query(IntentConfig).filter(IntentConfig.intent_key == intent_key).first()
    if not intent:
        raise HTTPException(status_code=404, detail=f"Intent '{intent_key}' not found")
    
    update_data = intent_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(intent, field, value)
    
    db.commit()
    db.refresh(intent)
    return intent

@router.delete("/{intent_key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_intent(intent_key: str, db: Session = Depends(get_db)):
    """Delete an intent configuration."""
    intent = db.query(IntentConfig).filter(IntentConfig.intent_key == intent_key).first()
    if not intent:
        raise HTTPException(status_code=404, detail=f"Intent '{intent_key}' not found")
    
    db.delete(intent)
    db.commit()
    return None
