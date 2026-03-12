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
        "import", "export", "shipment", "supplier", "buyer", "trade", "data",
        "show import data", "show export data", "get trade data", "find import shipments", 
        "find export shipments", "find buyers", "find suppliers", "find importers",
        "find exporters", "search trade data", "search shipment records", "search buyer database",
        "search supplier database", "shipment search", "trade data search", "trade shipment lookup",
        "exporter lookup", "importer lookup", "supplier lookup", "buyer lookup india",
        "india import data", "india export data", "usa import data", "usa export data",
        "china trade data", "country trade statistics", "country import shipments",
        "country export shipments", "country shipment data", "global country trade data",
        "trade between countries", "bilateral trade data", "country buyers list",
        "country suppliers list", "country exporters", "country importers",
        "country shipment records", "country trade database", "country shipment analysis",
        "country trade insights", "buyer data", "buyer list", "global buyers", "import buyers",
        "international buyers", "verified buyers", "buyer database", "buyer contact details",
        "product buyers list", "buyer companies", "buyer leads", "importer buyers", "wholesale buyers",
        "distributor buyers", "bulk buyers", "overseas buyers", "active buyers", "potential buyers",
        "top buyers", "buyer shipment history", "import export data", "international trade data",
        "global trade data", "customs trade data", "trade statistics", "trade database",
        "global shipment data", "import export statistics", "market trade data", "trade records",
        "trade shipment records", "import export database", "shipment records", "trade analytics",
        "shipment analytics", "trade insights", "trade intelligence", "international shipment data",
        "import shipment data", "import statistics", "country import data", "product import data",
        "import customs data", "import shipment records", "importer data", "importer list",
        "importer details", "import company list", "import shipment history", "import trade database",
        "monthly import data", "yearly import data", "latest import data", "historical import data",
        "live import shipments", "import container data", "import shipment details",
        "export shipment data", "export statistics", "country export data", "product export data",
        "export customs data", "export shipment records", "exporter data", "exporter list",
        "exporter details", "export company list", "export shipment history", "export trade database",
        "monthly export data", "yearly export data", "latest export data", "historical export data",
        "live export shipments", "export container data", "export shipment details"
    ]):
        return IntentType.IMPORT_EXPORT

    # 4. GREETING (Priority 4)
    if any(word in message for word in ["hi", "hello", "hey", "hii", "helo", "hy"]):
        return IntentType.GREETING

    return IntentType.UNKNOWN
