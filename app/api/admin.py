"""
Admin API — Dynamic configuration management for intents and greetings.
Allows unauthorized management (per user request) of bot behavior.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional

from app.core.dependencies import get_db
from app.models.intent_config import IntentConfig
from pydantic import BaseModel

router = APIRouter(prefix="/admin", tags=["Admin Configuration"])

class IntentUpdateSchema(BaseModel):
    keywords: List[str]
    response_text: str
    metadata_json: Optional[Dict[str, Any]] = None

@router.get("/configs", summary="Get all intent and greeting configurations")
def get_all_configs(db: Session = Depends(get_db)):
    """
    Returns all dynamic configurations for the GTT Smartbot.
    """
    return db.query(IntentConfig).all()

@router.put("/configs/{intent_key}", summary="Update a specific intent or greeting configuration")
def update_config(intent_key: str, update_req: IntentUpdateSchema, db: Session = Depends(get_db)):
    """
    Updates keywords and response templates for a specific intent (e.g., GREETING or SALES_DEMO).
    """
    config = db.query(IntentConfig).filter(IntentConfig.intent_key == intent_key).first()
    if not config:
        # If it doesn't exist, we create it
        config = IntentConfig(intent_key=intent_key)
        db.add(config)
    
    config.keywords = update_req.keywords
    config.response_text = update_req.response_text
    if update_req.metadata_json is not None:
        config.metadata_json = update_req.metadata_json
        
    db.commit()
    db.refresh(config)
    
    return {
        "success": True,
        "intent_key": intent_key,
        "message": f"Configuration for {intent_key} updated successfully."
    }

# Specific convenience endpoints if needed
@router.get("/greetings")
def get_greetings(db: Session = Depends(get_db)):
    return db.query(IntentConfig).filter(IntentConfig.intent_key == "GREETING").first()

@router.get("/intents")
def get_intents(db: Session = Depends(get_db)):
    # Return all except greetings
    return db.query(IntentConfig).filter(IntentConfig.intent_key != "GREETING").all()
