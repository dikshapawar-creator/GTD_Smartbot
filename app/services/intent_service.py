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
    SALES_DEMO = "SALES_DEMO"
    DATA_PROVIDER_DATASOURCE = "DATA_PROVIDER_DATASOURCE"
    API_ACCESS_REQUEST = "API_ACCESS_REQUEST"
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
        "agent", "human", "representative", "call me", "talk to person", "intervene",
        "no", "skip", "not interested", "later", "not now", "no thanks", "stop", "cancel"
    ]):
        return IntentType.HANDOFF

    # 2. Dynamic DB-based Detection (PRIMARY)
    from app.models.intent_config import IntentConfig
    
    all_configs = db.query(IntentConfig).all()
    best_match = None
    longest_kw_len = 0

    for config in all_configs:
        keywords = config.keywords # List from JSON
        if not keywords: continue
        
        for kw in keywords:
            kw = kw.lower().strip()
            # Check for substring match (prioritize longer phrases for specificity)
            if kw in message:
                if len(kw) > longest_kw_len:
                    longest_kw_len = len(kw)
                    best_match = config.intent_key

    if best_match:
        try:
            return IntentType(best_match)
        except ValueError:
            return IntentType.UNKNOWN

    # 3. Fallback to Hardcoded logic (Strictly for missing DB config)
    # Reordered to check specific intents BEFORE generic ones like IMPORT_EXPORT
    priority_fallbacks = [
        (IntentType.GREETING, ["hi", "hello", "hey", "hii", "greetings", "good morning"]),
        (IntentType.BUYER_SEARCH, ["buyer", "buyers", "find buyers", "who buys", "buyer list"]),
        (IntentType.SUPPLIER_SEARCH, ["supplier", "suppliers", "find suppliers", "who sells", "supplier list"]),
        (IntentType.HS_CODE_SEARCH, ["hs code", "hsn code", "tariff", "classification"]),
        (IntentType.COMPETITOR_ANALYSIS, ["competitor", "competition", "compete", "benchmark"]),
        (IntentType.SHIPMENT_RECORDS, ["records", "shipment details", "bill of lading", "manifest"]),
        (IntentType.COUNTRY_TRADE_ANALYSIS, ["country analysis", "trade by country", "global trade"]),
        (IntentType.PRODUCT_MARKET_RESEARCH, ["market research", "demand", "product research"]),
        (IntentType.PRICING_INQUIRY, ["price", "cost", "pricing", "subscription", "fees", "how much"]),
        (IntentType.REQUEST_DEMO, ["book demo", "schedule demo", "request demo", "trial"]),
        (IntentType.LEAD_COLLECTION, ["contact me", "callback", "call back", "reach out"]),
        (IntentType.DEMO, ["demo", "show me", "tutorial"]),
        (IntentType.IMPORT_EXPORT, ["import", "export", "trade", "importing", "exporting"]), # Generic LAST
    ]

    for intent, keywords in priority_fallbacks:
        if any(kw in message for kw in keywords):
            return intent

    return IntentType.UNKNOWN


