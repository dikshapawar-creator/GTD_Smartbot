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
    1. HANDOFF (Highest Priority - Hardcoded safety)
    2. Specific Intents (BUYER_SEARCH, SUPPLIER_SEARCH, etc.)
    3. General Intents (IMPORT_EXPORT)
    4. Fallback to UNKNOWN
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

    # 2. Dynamic DB-based Detection with Priority Order
    from app.models.intent_config import IntentConfig
    
    # Define priority order - specific intents first, then general ones
    priority_order = [
        "GREETING", "REQUEST_DEMO", "LEAD_COLLECTION", "PRICING_INQUIRY",
        "BUYER_SEARCH", "SUPPLIER_SEARCH", "HS_CODE_SEARCH", 
        "COMPETITOR_ANALYSIS", "SHIPMENT_RECORDS", "COUNTRY_TRADE_ANALYSIS",
        "PRODUCT_MARKET_RESEARCH", "SALES_DEMO", "IMPORT_EXPORT"  # IMPORT_EXPORT last
    ]
    
    # First, check intents in priority order
    for intent_key in priority_order:
        config = db.query(IntentConfig).filter(IntentConfig.intent_key == intent_key).first()
        if config and config.keywords:
            if any(keyword.lower() in message for keyword in config.keywords):
                try:
                    return IntentType(config.intent_key)
                except ValueError:
                    logger.warning(f"Unknown intent_key in DB: {config.intent_key}")
                    continue
    
    # Then check any remaining intents not in priority list
    all_configs = db.query(IntentConfig).all()
    for config in all_configs:
        if config.intent_key not in priority_order and config.keywords:
            if any(keyword.lower() in message for keyword in config.keywords):
                try:
                    return IntentType(config.intent_key)
                except ValueError:
                    logger.warning(f"Unknown intent_key in DB: {config.intent_key}")
                    continue

    return IntentType.UNKNOWN
