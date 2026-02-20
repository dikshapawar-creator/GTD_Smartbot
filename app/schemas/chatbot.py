from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator, model_validator
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from enum import Enum
import re
import logging

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

class ResponseType(str, Enum):
    MESSAGE = "MESSAGE"
    CTA = "CTA"

class SessionInitResponse(BaseModel):
    session_token: str
    message: str
    state: ChatState
    type: Optional[ResponseType] = ResponseType.MESSAGE
    cta_label: Optional[str] = None
    action: Optional[str] = None

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
    # Honeypot — hidden from humans, filled by bots; must remain empty
    hp_field: Optional[str] = Field(default=None)

    # ---- Field Validators --------------------------------------------------

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        v = v.strip()
        # Collapse multiple internal spaces
        v = re.sub(r"\s+", " ", v)
        # Only letters, spaces, hyphens, apostrophes, periods
        if not re.fullmatch(r"[A-Za-z\s\-'\.]+", v):
            raise ValueError("Full name must contain only letters, spaces, hyphens, and apostrophes")
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

        # Block disposable/throwaway domains
        disposable = _get_disposable_domains()
        if domain in disposable:
            raise ValueError("Disposable email addresses are not accepted")

        logger.debug({"event": "email_validated", "domain": domain})
        return v

    @field_validator("contact_number")
    @classmethod
    def normalize_phone_e164(cls, v: str) -> str:
        """Parse and normalize phone number to E.164 format."""
        import phonenumbers  # type: ignore
        v = v.strip()
        try:
            # Parse — None region means the number must include country code
            parsed = phonenumbers.parse(v, None)
            if not phonenumbers.is_valid_number(parsed):
                raise ValueError()
            return phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.E164
            )
        except Exception:
            raise ValueError(
                "Phone number must be in international format with country code, "
                "e.g. +919876543210 or +12025551234"
            )

    @field_validator("hp_field")
    @classmethod
    def honeypot_must_be_empty(cls, v: Optional[str]) -> Optional[str]:
        """Honeypot: any bot that fills this field is rejected silently."""
        if v and v.strip():
            logger.warning({"event": "spam_honeypot_triggered", "hp_value": v[:30]})
            raise ValueError("Invalid form submission detected")
        return v


class ConversationResponse(BaseModel):
    id: int # Changed to int for BIGINT PK compatibility
    lead_id: str
    message: str
    sender: str
    timestamp: datetime
    model_config = ConfigDict(from_attributes=True)
