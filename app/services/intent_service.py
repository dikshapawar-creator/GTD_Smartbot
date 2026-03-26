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

def detect_intent(db: Session, message: str, tenant_id: int) -> str:
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
    
    def fetch_best_match(target_id: int) -> tuple:
        try:
            configs = db.query(IntentConfig).filter(
                IntentConfig.tenant_id == target_id,
                IntentConfig.is_active == True
            ).all()
            match = None
            max_len = 0
            import json
            for config in configs:
                keywords = config.keywords
                if not keywords: continue
                
                # Robust parsing: handle JSON-list strings OR comma-separated strings
                if isinstance(keywords, str):
                    keywords_str = keywords.strip()
                    if keywords_str.startswith("[") and keywords_str.endswith("]"):
                        try:
                            keywords = json.loads(keywords_str)
                        except:
                            keywords = [k.strip() for k in keywords_str.split(",")]
                    else:
                        keywords = [k.strip() for k in keywords_str.split(",")]
                
                if not isinstance(keywords, list):
                    continue

                for kw in keywords:
                    kw = kw.lower().strip()
                    if kw and kw in message and len(kw) > max_len:
                        max_len = len(kw)
                        match = config.intent_key
            return match, max_len
        except Exception as e:
            logger.error(f"Error querying IntentConfig for tenant {target_id}: {e}")
            return None, 0

    # Dynamic detection via the active tenant's patterns
    best_match, longest_kw_len = fetch_best_match(tenant_id)

    if best_match:
        logger.info(f"Best DB match: {best_match} (len={longest_kw_len})")
        return best_match

    return "UNKNOWN"


