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

def detect_intent(db: Session, message: str) -> str:
    """
    Detects user intent using dynamic configuration from the database.
    Returns the intent_key string.
    """
    if not message:
        return "UNKNOWN"

    message = message.lower().strip()

    # 1. HANDOFF (Highest Priority - Hardcoded safety)
    handoff_words = [
        "agent", "human", "representative", "call me", "talk to person", "intervene",
        "no", "skip", "not interested", "later", "not now", "no thanks", "stop", "cancel"
    ]
    # Use word boundary to avoid partial matches
    import re
    for word in handoff_words:
        if re.search(rf"\b{re.escape(word)}\b", message):
            logger.info(f"Handoff detected via word: {word}")
            return "HANDOFF"

    # 2. Dynamic DB-based Detection (PRIMARY)
    from app.models.intent_config import IntentConfig
    
    try:
        all_configs = db.query(IntentConfig).all()
        logger.info(f"Dynamic Intent Check: Found {len(all_configs)} configs in DB")
    except Exception as e:
        logger.error(f"Error querying IntentConfig: {e}")
        all_configs = []

    best_match = None
    longest_kw_len = 0

    for config in all_configs:
        keywords = config.keywords # List from JSON
        if not keywords: continue
        
        # Support both List and comma-separated string for keywords
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(",")]
            
        for kw in keywords:
            kw = kw.lower().strip()
            if not kw: continue
            
            # Check for substring match (prioritize longer phrases for specificity)
            if kw in message:
                logger.debug(f"Keyword match found: '{kw}' for intent '{config.intent_key}'")
                if len(kw) > longest_kw_len:
                    longest_kw_len = len(kw)
                    best_match = config.intent_key

    if best_match:
        logger.info(f"Best DB match: {best_match} (len={longest_kw_len})")
        return best_match

    # 3. Fallback to Hardcoded logic (Strictly for missing DB config)
    # Reordered to check specific intents BEFORE generic ones like IMPORT_EXPORT
    priority_fallbacks = [
        ("GREETING", ["hi", "hello", "hey", "hii", "greetings", "good morning"]),
        ("BUYER_SEARCH", ["buyer", "buyers", "find buyers", "who buys", "buyer list"]),
        ("SUPPLIER_SEARCH", ["supplier", "suppliers", "find suppliers", "who sells", "supplier list"]),
        ("HS_CODE_SEARCH", ["hs code", "hsn code", "tariff", "classification"]),
        ("COMPETITOR_ANALYSIS", ["competitor", "competition", "compete", "benchmark"]),
        ("SHIPMENT_RECORDS", ["records", "shipment details", "bill of lading", "manifest"]),
        ("COUNTRY_TRADE_ANALYSIS", ["country analysis", "trade by country", "global trade", "bilateral trade data"]),
        ("PRODUCT_MARKET_RESEARCH", ["market research", "demand", "product research"]),
        ("PRICING_INQUIRY", ["price", "cost", "pricing", "subscription", "fees", "how much"]),
        ("REQUEST_DEMO", ["book demo", "schedule demo", "request demo", "trial"]),
        ("LEAD_COLLECTION", ["contact me", "callback", "call back", "reach out"]),
        ("DEMO", ["demo", "show me", "tutorial"]),
        ("IMPORT_EXPORT", ["import", "export", "trade", "importing", "exporting"]), # Generic LAST
    ]

    for intent_key, keywords in priority_fallbacks:
        if any(kw in message for kw in keywords):
            return intent_key

    return "UNKNOWN"


