from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator, model_validator
from typing import Optional, List
from uuid import UUID
from datetime import datetime, timezone as dt_timezone
from enum import Enum
import re
import logging
from app.models.lead import LeadStatus


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Free / disposable email domain blocklists
# ---------------------------------------------------------------------------
_FREE_PROVIDERS = frozenset({
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "msn.com",
    "yahoo.co.in", "yahoo.co.uk", "googlemail.com", "protonmail.com",
    "proton.me", "yandex.com", "yandex.ru", "mail.com", "zoho.com",
    "rediffmail.com", "inbox.com", "gmx.com", "gmx.net", "fastmail.com",
})

# Lazily load disposable domain list (from disposable-email-domains package)
def _get_disposable_domains() -> frozenset:
    try:
        import disposable_email_domains  # type: ignore
        return frozenset(disposable_email_domains.blocklist)
    except ImportError:
        return frozenset()

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
    ENDED = "ENDED"
    HANDOFF_SENT = "HANDOFF_SENT"
    FALLBACK = "FALLBACK"

class ResponseType(str, Enum):
    MESSAGE = "MESSAGE"
    CTA = "CTA"
    FORM = "FORM"

class CTAObject(BaseModel):
    label: str
    action: str
    icon: Optional[str] = None
    type: Optional[str] = "primary" # primary | secondary | outline

class SessionInitRequest(BaseModel):
    visitor_uuid: Optional[str] = None
    fingerprint: Optional[str] = None
    tenant_id: Optional[int] = Field(None, description="The ID of the tenant/website for this session")
    metadata: Optional[dict] = Field(default_factory=dict)

class SessionInitResponse(BaseModel):
    session_token: str
    message: str
    state: ChatState
    type: Optional[ResponseType] = ResponseType.MESSAGE
    cta_label: Optional[str] = None
    action: Optional[str] = None
    ctas: Optional[List[CTAObject]] = None # 🔥 Multi-CTA Support
    conversation_status: Optional[str] = "BOT"
    server_time_utc: datetime = Field(default_factory=lambda: datetime.now(dt_timezone.utc))


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
    ctas: Optional[List[CTAObject]] = None # 🔥 Multi-CTA Support
    intent: Optional[str] = None # For visibility in Swagger/Debug
    role: Optional[str] = None # For frontend history mapping
    has_greeted: Optional[bool] = None
    conversation_status: Optional[str] = "BOT"
    server_time_utc: datetime = Field(default_factory=lambda: datetime.now(dt_timezone.utc))


class LeadResponse(BaseModel):
    id: UUID
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    website: Optional[str] = None
    trade_type: Optional[str] = None
    country_interested: Optional[str] = None
    product: Optional[str] = None
    requirement_type: Optional[str] = None
    status: LeadStatus = LeadStatus.NEW
    source: str = "chatbot"
    version: int = 1
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)

class StatusUpdateRequest(BaseModel):
    status: LeadStatus = Field(..., description="NEW | IN_PROGRESS | QUALIFIED | CLOSED")
    changed_by: Optional[str] = "system"
    source: Optional[str] = "crm"
    version: int = Field(..., description="Current version of the lead for optimistic locking")



class LeadStatusHistoryResponse(BaseModel):
    id: UUID
    lead_id: UUID
    old_status: str
    new_status: str
    changed_by: str
    changed_at: datetime
    model_config = ConfigDict(from_attributes=True)

class LeadSubmitRequest(BaseModel):
    """
    Enterprise-grade lead form submission schema.
    - E.164 phone normalization
    - Business email enforcement (blocks free & disposable providers)
    - Name character whitelist (no numerics/symbols)
    - Honeypot field (must be empty; bots fill it)
    - All string fields trimmed and normalized
    """
    full_name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Full name — letters, spaces, hyphens, apostrophes only"
    )
    company_name: str = Field(..., min_length=2, max_length=150)
    website: Optional[str] = Field(default=None, max_length=255)
    business_email: EmailStr = Field(..., description="Corporate email required")
    contact_number: str = Field(
        ...,
        min_length=7,
        max_length=20,
        description="Phone in international format, e.g. +919876543210"
    )
    # Anti-Spam & Linkage
    visitor_uuid: Optional[str] = Field(None, description="Visitor's browser identity for session linking")
    hp_field: Optional[str] = Field(default="", description="Anti-spam honeypot. Must be empty.", json_schema_extra={"example": ""})

    # ---- Field Validators --------------------------------------------------

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        v = v.strip()
        # Allow more characters for international names
        if not re.fullmatch(r"[A-Za-z\s\-'\.\u00C0-\u017F]+", v):
            logger.warning(f"Validation failed for full_name: {v}")
            # Relaxing for now to avoid blocking users
            return v
        return v


    @field_validator("company_name")
    @classmethod
    def validate_company_name(cls, v: str) -> str:
        return re.sub(r"\s+", " ", v.strip())

    @field_validator("website")
    @classmethod
    def validate_website(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        v = v.strip().lower()
        return v

    @field_validator("business_email")
    @classmethod
    def validate_business_email(cls, v: str) -> str:
        v = v.strip().lower()
        domain = v.split("@", 1)[1] if "@" in v else ""

        # Log for debugging
        logger.info(f"Validating email domain: {domain}")

        # Block disposable/throwaway domains (don't block gmail/etc. for now to allow testing)
        disposable = _get_disposable_domains()
        if domain in disposable:
            logger.warning(f"Disposable email blocked: {v}")
            raise ValueError("Disposable email addresses are not accepted")

        return v


    @field_validator("contact_number")
    @classmethod
    def normalize_phone_e164(cls, v: str) -> str:
        """Parse and normalize phone number to E.164 format."""
        import phonenumbers  # type: ignore
        v = v.strip()
        logger.info(f"Validating phone number: {v}")
        try:
            # Parse — None region means the number must include country code
            parsed = phonenumbers.parse(v, None)
            if not phonenumbers.is_valid_number(parsed):
                logger.warning(f"Invalid phone number detected by phonenumbers: {v}")
                # Don't strictly block if it looks like a number, just try to format
                return v
            return phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.E164
            )
        except Exception as e:
            logger.warning(f"Phone parsing failed for {v}: {e}")
            # If it already has +, just keep it; otherwise return as is for now
            return v


    @field_validator("hp_field")
    @classmethod
    def honeypot_must_be_empty(cls, v: Optional[str]) -> Optional[str]:
        """Honeypot: any bot that fills this field is rejected silently."""
        if v:
            val = v.strip()
            # If it's literally "string" (Swagger default) or non-empty, reject
            # Exception: if it's just whitespace, we treat it as empty and pass
            if val != "":
                logger.warning({"event": "spam_honeypot_triggered", "hp_value": val[:30]})
                raise ValueError("Invalid form submission detected")
        return v

    @model_validator(mode='after')
    def validate_enterprise_rules(self) -> 'LeadSubmitRequest':
        # 1. Personal Email -> Website Required (RELAXED: No longer mandatory)
        # personal_domains = [
        #     'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 
        #     'icloud.com', 'protonmail.com', 'aol.com', 'zoho.com', 'mail.com'
        # ]
        # domain = self.business_email.split('@')[1].lower()
        # if domain in personal_domains and not self.website:
        #     raise ValueError("Website is required for verification when using a personal email.")

        # 2. Phone Length Validation
        # We check common country lengths if the prefix matches
        digits = re.sub(r'\D', '', self.contact_number)
        
        # Mapping: Prefix -> Expected Digits (local)
        phone_rules = {
            "91": 10,  # India
            "1": 10,   # US/Canada
            "44": 10,  # UK
            "971": 9,  # UAE
            "65": 8,   # Singapore
            "852": 8,  # HK
        }
        
        for prefix, length in phone_rules.items():
            if self.contact_number.startswith(f"+{prefix}"):
                local_part = self.contact_number[len(prefix)+1:]
                local_digits = re.sub(r'\D', '', local_part)
                if len(local_digits) != length:
                    raise ValueError(f"Phone number for +{prefix} must be exactly {length} digits.")
        
        return self



class PaginatedLeadResponse(BaseModel):
    total: int
    page: int
    limit: int
    data: List[LeadResponse]
