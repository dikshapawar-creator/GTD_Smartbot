from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from enum import Enum

class ChatState(str, Enum):
    START = "START"
    TRADE_TYPE = "TRADE_TYPE"
    COUNTRY = "COUNTRY"
    PRODUCT = "PRODUCT"
    NAME = "NAME"
    EMAIL = "EMAIL"
    COMPANY = "COMPANY"
    PHONE = "PHONE"
    REQUIREMENT = "REQUIREMENT"
    COMPLETE = "COMPLETE"

class LeadBase(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    trade_type: Optional[str] = None
    country_interested: Optional[str] = None
    product: Optional[str] = None
    requirement_type: Optional[str] = None
    status: Optional[str] = "NEW"

class LeadCreate(LeadBase):
    pass

class LeadResponse(LeadBase):
    id: UUID
    created_at: datetime
    # Pydantic v2 style for from_orm
    model_config = ConfigDict(from_attributes=True)

class ConversationResponse(BaseModel):
    id: UUID
    lead_id: UUID
    message: str
    sender: str
    timestamp: datetime
    model_config = ConfigDict(from_attributes=True)

class ChatStartResponse(BaseModel):
    sessionId: UUID
    message: str
    state: ChatState

class ChatMessageRequest(BaseModel):
    sessionId: UUID
    message: str

class ChatMessageResponse(BaseModel):
    sessionId: UUID
    message: str
    state: ChatState
