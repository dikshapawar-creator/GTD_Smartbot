from pydantic import BaseModel, Field
from typing import Optional, List, Any

class IntentConfigBase(BaseModel):
    intent_key: str = Field(..., max_length=50, description="Unique identifier for the intent")
    keywords: List[str] = Field(..., description="List of keywords to trigger this intent")
    response_text: Optional[str] = Field(None, max_length=1000, description="The response text for this intent")
    metadata_json: Optional[dict] = Field(None, description="Additional metadata for the intent (e.g., CTA actions)")

class IntentConfigCreate(IntentConfigBase):
    pass

class IntentConfigUpdate(BaseModel):
    keywords: Optional[List[str]] = None
    response_text: Optional[str] = None
    metadata_json: Optional[dict] = None

class IntentConfigRead(IntentConfigBase):
    id: int

    class Config:
        from_attributes = True
