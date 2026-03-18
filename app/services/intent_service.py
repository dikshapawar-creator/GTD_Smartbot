"""
IntentService — Detects user intent using dynamic SQL-based configurations.
"""
import re
import logging
from enum import Enum
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

class IntentType(Enum):
    GREETING = "GREETING"
    IMPORT_EXPORT = "IMPORT_EXPORT"
    DEMO = "DEMO"
    HANDOFF = "HANDOFF"
    BUYER_SEARCH = "BUYER_SEARCH"
    SUPPLIER_SEARCH = "SUPPLIER_SEARCH"
    HS_CODE_SEARCH = "HS_CODE_SEARCH"
    COMPETITOR_ANALYSIS = "COMPETITOR_ANALYSIS"
    SHIPMENT_RECORDS = "SHIPMENT_RECORDS"
    COUNTRY_TRADE_ANALYSIS = "COUNTRY_TRADE_ANALYSIS"
    PRODUCT_MARKET_RESEARCH = "PRODUCT_MARKET_RESEARCH"
    PRICING_INQUIRY = "PRICING_INQUIRY"
    REQUEST_DEMO = "REQUEST_DEMO"
    LEAD_COLLECTION = "LEAD_COLLECTION"
    UNKNOWN = "UNKNOWN"

def detect_intent(db: Session, message: str) -> IntentType:
    """
    Detects user intent using dynamic configuration from the database.
    Strict priority:
    1. HANDOFF
    2. Dynamic Intents from DB (matching keywords)
    3. Fallback to UNKNOWN
    """
    if not message:
        return IntentType.UNKNOWN

    message = message.lower().strip()

    # 1. HANDOFF (Highest Priority - Hardcoded safety)
    if any(word in message for word in [
        "agent", "human", "representative", "call me", 
        "no", "skip", "not interested", "later", "talk to person"
    ]):
        return IntentType.HANDOFF

    # 2. Dynamic DB-based Detection
    from app.models.intent_config import IntentConfig
    configs = db.query(IntentConfig).all()
    
    for config in configs:
        if not config.keywords:
            continue
            
        # Check if any keyword matches the message
        # Using word boundary matching for better accuracy if possible, 
        # but simple 'in' check is what was previously used.
        if any(keyword.lower() in message for keyword in config.keywords):
            try:
                return IntentType(config.intent_key)
            except ValueError:
                logger.warning(f"Unknown intent_key in DB: {config.intent_key}")
                continue

    return IntentType.UNKNOWN
