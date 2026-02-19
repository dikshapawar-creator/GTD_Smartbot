from pydantic import BaseModel, EmailStr, ConfigDict, Field
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

class ResponseType(str, Enum):
    MESSAGE = "MESSAGE"
    CTA = "CTA"

class SessionInitResponse(BaseModel):
    session_token: str
    message: str
    state: ChatState

class ChatMessageRequest(BaseModel):
    # sessionId removed from body for security
    message: str

class ChatMessageResponse(BaseModel):
    # Backward compatibility: returning sessionId
    sessionId: str
    message: str
    state: ChatState
    type: ResponseType = ResponseType.MESSAGE
    cta_label: Optional[str] = None
    action: Optional[str] = None
    intent: Optional[str] = None # For visibility in Swagger/Debug
    has_greeted: Optional[bool] = None

class LeadResponse(BaseModel):
    id: UUID
    name: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    trade_type: Optional[str] = None
    country_interested: Optional[str] = None
    product: Optional[str] = None
    requirement_type: Optional[str] = None
    status: Optional[str] = "NEW"
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class LeadSubmitRequest(BaseModel):
    full_name: str
    company_name: str
    website: Optional[str] = None
    business_email: EmailStr
    contact_number: str

class ConversationResponse(BaseModel):
    id: int # Changed to int for BIGINT PK compatibility
    lead_id: str
    message: str
    sender: str
    timestamp: datetime
    model_config = ConfigDict(from_attributes=True)
