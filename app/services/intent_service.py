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
    UNKNOWN = "UNKNOWN"

def detect_intent(db: Session, message: str) -> IntentType:
    """
    Detects user intent using hardcoded keyword matching with strict priority:
    1. HANDOFF, 2. DEMO, 3. IMPORT_EXPORT, 4. GREETING
    """
    if not message:
        return IntentType.UNKNOWN

    message = message.lower().strip()

    # 1. HANDOFF (Priority 1)
    if any(word in message for word in [
        "agent", "human", "representative", "call me", 
        "no", "skip", "not interested", "later"
    ]):
        return IntentType.HANDOFF

    # 2. DEMO (Priority 2)
    if "demo" in message:
        return IntentType.DEMO

    # 3. IMPORT_EXPORT (Priority 3)
    if any(word in message for word in [
        "import", "export", "shipment", "supplier", "buyer", "trade", "data"
    ]):
        return IntentType.IMPORT_EXPORT

    # 4. GREETING (Priority 4)
    if any(word in message for word in ["hi", "hello", "hey", "hii", "helo", "hy"]):
        return IntentType.GREETING

    return IntentType.UNKNOWN
