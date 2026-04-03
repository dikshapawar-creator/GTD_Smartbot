from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Any
import json

class IntentConfigBase(BaseModel):
    intent_key: str = Field(..., max_length=50, description="Unique identifier for the intent")
    keywords: List[str] = Field(..., description="List of keywords to trigger this intent")
    response_text: Optional[str] = Field(None, max_length=2000, description="The response text for this intent")
    metadata_json: Optional[dict] = Field(None, description="Additional metadata for the intent (e.g., CTA actions)")
    is_active: bool = Field(True, description="Whether this intent is active")

class IntentConfigCreate(IntentConfigBase):
    pass

class IntentConfigUpdate(BaseModel):
    intent_key: Optional[str] = None
    keywords: Optional[List[str]] = None
    response_text: Optional[str] = None
    metadata_json: Optional[dict] = None
    is_active: Optional[bool] = None

class IntentConfigRead(IntentConfigBase):
    id: int

    @field_validator("keywords", mode="before")
    @classmethod
    def decode_keywords(cls, v):
        """Handles UTF-16 LE encoded keyword strings stored by SQL Server."""
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            if '\x00' in v:
                try:
                    v = v.encode('latin1').decode('utf-16-le').rstrip('\x00')
                except Exception:
                    v = v.replace('\x00', '')
            v = v.strip()
            if not v:
                return []
            if v.startswith('[') and v.endswith(']'):
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(k).strip() for k in parsed if k]
                except json.JSONDecodeError:
                    inner = v.strip('[]')
                    return [k.strip().strip('"').strip("'") for k in inner.split(',') if k.strip()]
            return [k.strip().strip('"').strip("'") for k in v.split(',') if k.strip()]
        return []

    @field_validator("metadata_json", mode="before")
    @classmethod
    def decode_metadata_json(cls, v):
        """Handles UTF-16 LE encoded JSON strings for metadata_json."""
        if v is None or isinstance(v, dict):
            return v
        if isinstance(v, str):
            # Strip UTF-16 null bytes
            if '\x00' in v:
                try:
                    v = v.encode('latin1').decode('utf-16-le').rstrip('\x00')
                except Exception:
                    v = v.replace('\x00', '')
            v = v.strip()
            if not v or v in ('{}', ''):
                return None
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return None
        return None

    @field_validator("response_text", mode="before")
    @classmethod
    def decode_response_text(cls, v):
        """Strip any residual UTF-16 null bytes from response text."""
        if v and isinstance(v, str) and '\x00' in v:
            try:
                return v.encode('latin1').decode('utf-16-le').rstrip('\x00')
            except Exception:
                return v.replace('\x00', '')
        return v

    class Config:
        from_attributes = True
