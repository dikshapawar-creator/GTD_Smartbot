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

# ⚡ GLOBAL CACHE for IntentConfig (session_id -> data)
import time
intent_cache = {} # {tenant_id: {"data": configs, "expiry": timestamp}}
CACHE_TTL = 60 # 1 minute (reduced from 5m for better responsiveness)

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
        if re.search(rf"\b{re.escape(word)}\b", message, re.IGNORECASE):
            logger.info(f"Handoff detected via word: {word}")
            return "HANDOFF"

    # 1.5 GREETING (Safety fallback for basic interactions)
    greeting_words = ["hi", "hii", "hello", "hey", "hola", "greetings", "good morning", "good evening", "good afternoon"]
    for word in greeting_words:
        if re.search(rf"\b{re.escape(word)}\b", message, re.IGNORECASE):
            logger.debug(f"Greeting detected via word: {word}")
            return "GREETING"

    # 2. Dynamic DB-based Detection (PRIMARY)
    from app.models.intent_config import IntentConfig
    
    def fetch_best_match(target_id: int) -> tuple:
        try:
            # ⚡ Check Cache First
            now = time.time()
            if target_id in intent_cache and intent_cache[target_id]["expiry"] > now:
                configs = intent_cache[target_id]["data"]
            else:
                try:
                    configs = db.query(IntentConfig).filter(
                        IntentConfig.tenant_id == target_id,
                        IntentConfig.is_active == True
                    ).all()
                except Exception as db_error:
                    logger.error(f"Database error querying IntentConfig for tenant {target_id}: {db_error}")
                    return None, 0
                    
                intent_cache[target_id] = {"data": configs, "expiry": now + CACHE_TTL}
                logger.debug(f"Intent cache refreshed for tenant {target_id}")

            match = None
            max_len = 0
            import json
            for config in configs:
                try:
                    keywords = config.keywords
                    if not keywords: continue
                    
                    # Parse keywords from string (now that we store as TEXT, not JSON)
                    if isinstance(keywords, str):
                        keywords_str = keywords.strip()
                        
                        # Skip empty strings
                        if not keywords_str:
                            continue
                        
                        # Handle UTF-16 encoded strings with null bytes
                        if '\x00' in keywords_str:
                            try:
                                # Try to decode from UTF-16
                                keywords_str = keywords_str.encode('latin1').decode('utf-16le').rstrip('\x00')
                            except:
                                # Fallback: just remove null bytes
                                keywords_str = keywords_str.replace('\x00', '')
                        
                        # Try to parse as JSON first
                        if keywords_str.startswith("[") and keywords_str.endswith("]"):
                            try:
                                keywords = json.loads(keywords_str)
                            except json.JSONDecodeError as e:
                                logger.warning(f"Invalid JSON for intent {config.intent_key} tenant {target_id}: {e}")
                                # Try to parse as comma-separated values inside brackets
                                inner = keywords_str.strip("[]")
                                keywords = [k.strip().strip('"').strip("'") for k in inner.split(",") if k.strip()]
                        else:
                            # Treat as comma-separated string
                            keywords = [k.strip().strip('"').strip("'") for k in keywords_str.split(",") if k.strip()]
                    
                    if not isinstance(keywords, list):
                        continue

                    for kw in keywords:
                        kw = kw.lower().strip().strip('"').strip("'")
                        if not kw: continue
                        
                        # ⚡ Use word boundary matching for more accurate detection
                        # This prevents "buy" matching "building"
                        pattern = rf"\b{re.escape(kw)}\b"
                        if re.search(pattern, message, re.IGNORECASE) and len(kw) > max_len:
                            max_len = len(kw)
                            match = config.intent_key
                            logger.debug(f"Matched keyword '{kw}' for intent '{match}'")
                except Exception as e:
                    logger.warning(f"Error processing keywords for intent {config.intent_key}: {e}")
                    continue
                    
            return match, max_len
        except Exception as e:
            logger.error(f"Error querying IntentConfig for tenant {target_id}: {e}")
            return None, 0

    # Dynamic detection via the active tenant's patterns
    best_match, longest_kw_len = fetch_best_match(tenant_id)

    if best_match:
        logger.debug(f"Best intent match: {best_match} (len={longest_kw_len})")
        return best_match

    return "UNKNOWN"


