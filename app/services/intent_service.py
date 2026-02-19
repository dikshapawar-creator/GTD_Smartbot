"""
IntentService — Detects user intent using dynamic SQL-based configurations.
"""
import re
import logging
from enum import Enum
from sqlalchemy.orm import Session
from app.models.intent_config import IntentConfig

logger = logging.getLogger(__name__)

class IntentType(Enum):
    GREETING = "GREETING"
    SALES_DEMO = "SALES_DEMO"
    TRADE_FLOW = "TRADE_FLOW"
    UNKNOWN = "UNKNOWN"

def detect_intent(db: Session, message: str) -> IntentType:
    """
    Detects the intent by querying the intent_configs table.
    Allows for dynamic keyword management without code changes.
    """
    if not message:
        return IntentType.UNKNOWN

    clean_msg = message.lower().strip()

    # Load all configs from DB
    configs = db.query(IntentConfig).all()
    
    for cfg in configs:
        keywords = cfg.keywords if isinstance(cfg.keywords, list) else []
        if not keywords:
            continue
            
        # Create regex pattern with word boundaries
        pattern = r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b"
        
        # Special case for repetitive characters in short keywords (e.g., hi, hey)
        if cfg.intent_key == "GREETING":
             if re.search(pattern, clean_msg) or re.search(r"\b(hi+|hello+|hey+)\b", clean_msg):
                logger.info({"event": "intent_detected", "intent": cfg.intent_key})
                return IntentType[cfg.intent_key]
        else:
            if re.search(pattern, clean_msg):
                logger.info({"event": "intent_detected", "intent": cfg.intent_key})
                return IntentType[cfg.intent_key]

    return IntentType.TRADE_FLOW
