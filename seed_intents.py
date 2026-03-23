"""
Seed script — Populates initial intent configurations for the GTT Smartbot.
Includes 10 specialized Import-Export Trade Data Chatbot Intent Framework.
"""
from app.db.session import SessionLocal
from app.models.intent_config import IntentConfig

def upsert_intent(db, intent_key, keywords, response_text, metadata=None):
    intent = db.query(IntentConfig).filter(IntentConfig.intent_key == intent_key).first()
    if not intent:
        intent = IntentConfig(
            intent_key=intent_key,
            keywords=keywords,
            response_text=response_text,
            metadata_json=metadata
        )
        db.add(intent)
    else:
        intent.keywords = keywords
        intent.response_text = response_text
        if metadata:
            intent.metadata_json = metadata
    return intent

def seed_intents():
    db = SessionLocal()
    try:
        # 0. Core Greeting
        upsert_intent(db, "GREETING", 
            ["hi", "hello", "hey", "hii", "heey", "hola", "good morning", "good afternoon", "good evening"],
            "Welcome to GTD Service!\nAre you looking to import or export data?\nI’m here to assist you — please let me know how I can help.",
            {"cta_label": "Book Demo", "action": "OPEN_LEAD_FORM"}
        )

        # 1. Buyer Search Intent
        upsert_intent(db, "BUYER_SEARCH", 
            ["find buyers", "international buyers", "import buyers", "global buyers list", "verified buyers", "product buyers", "buyers for my product", "overseas buyers", "buyer database", "bulk buyers", "distributor buyers", "wholesale buyers"],
            "I can help you find verified international buyers for your product.\nTo get started, please share the product name or HS code you are interested in."
        )

        # 2. Supplier / Exporter Search
        upsert_intent(db, "SUPPLIER_SEARCH", 
            ["find suppliers", "find exporters", "supplier database", "global suppliers", "product suppliers", "exporter list", "manufacturer exporters", "supplier companies", "exporter database", "international suppliers"],
            "I can help you locate verified suppliers and exporters worldwide.\nPlease tell me the product or HS code you would like to search."
        )

        # 3. HS Code Search
        upsert_intent(db, "HS_CODE_SEARCH", 
            ["find hs code", "hs code for product", "harmonized code", "product hs code", "tariff code search", "customs hs code", "hs classification", "find tariff code"],
            "I can help you identify the correct HS code for your product.\nPlease provide the product name or description."
        )

        # 4. Competitor Analysis
        upsert_intent(db, "COMPETITOR_ANALYSIS", 
            ["competitor export data", "competitor import data", "track competitors shipments", "competitor trade analysis", "competitor export shipments", "analyze competitor trade", "competitor buyers list"],
            "I can help you analyze your competitors’ shipment activity, buyers, and markets.\nPlease share the competitor company name you would like to analyze."
        )

        # 5. Shipment Records
        upsert_intent(db, "SHIPMENT_RECORDS", 
            ["shipment records", "track shipments", "trade shipment data", "container shipment data", "customs shipment records", "shipment history", "international shipment records"],
            "I can help you search international shipment records and customs trade data.\nPlease provide the product, company name, or country you would like to search."
        )

        # 6. Country Trade Analysis
        upsert_intent(db, "COUNTRY_TRADE_ANALYSIS", 
            ["country trade data", "trade between countries", "country import export statistics", "bilateral trade data", "country trade analysis", "country export statistics", "country import statistics"],
            "I can help you analyze trade statistics between countries, including imports, exports, and shipment trends.\nPlease specify the countries and products you are interested in."
        )

        # 7. Product Market Research
        upsert_intent(db, "PRODUCT_MARKET_RESEARCH", 
            ["product demand worldwide", "market demand analysis", "global product demand", "export opportunity", "product market research", "trade opportunity analysis"],
            "I can help you analyze global demand and trade opportunities for your product.\nPlease share the product name or HS code."
        )

        # 8. Pricing Inquiry
        upsert_intent(db, "PRICING_INQUIRY", 
            ["trade data price", "trade database pricing", "subscription cost", "how much trade data cost", "import export database price", "pricing for trade intelligence"],
            "I'd be happy to share our pricing plans for accessing global trade data and analytics.\nPlease provide your business email so our team can send the pricing details."
        )

        # 9. Demo Request
        upsert_intent(db, "REQUEST_DEMO", 
            ["request demo", "book demo", "see trade data platform demo", "schedule demo", "product demo", "live demo trade database"],
            """Thank you. We will arrange a call for you shortly.

You can discuss all your questions with our team during the meeting.

Regarding your data and requirements, our team will provide you with the appropriate solution.""",
            {"cta_label": "Schedule Demo", "action": "OPEN_LEAD_FORM"}
        )

        # 10. Lead Collection
        upsert_intent(db, "LEAD_COLLECTION", 
            ["contact sales", "talk to sales", "business inquiry", "enterprise plan", "company trade solution", "corporate trade data access"],
            """Thank you. We will arrange a call for you shortly.

You can discuss all your questions with our team during the meeting.

Regarding your data and requirements, our team will provide you with the appropriate solution."""
        )

        # 11. Specialized Demo Intents
        upsert_intent(db, "SALES_DEMO", ["sales demo", "expert talk", "consultation"], 
            """Thank you. We will arrange a call for you shortly.

You can discuss all your questions with our team during the meeting.

Regarding your data and requirements, our team will provide you with the appropriate solution."""
        )
        upsert_intent(db, "DEMO", ["demo", "show me", "walkthrough"], 
            """Thank you. We will arrange a call for you shortly.

You can discuss all your questions with our team during the meeting.

Regarding your data and requirements, our team will provide you with the appropriate solution."""
        )

        # 12. Data Provider Partnership
        upsert_intent(db, "DATA_PROVIDER_DATASOURCE", 
            ["sell data", "data provider", "provide trade data", "data partnership", "data vendor", "contribute data", "customs data provider", "data supplier"],
            "We collaborate with data providers who can supply import-export or customs trade data.\nIf you are interested in selling or साझेदारी, please share your company details and type of data you can provide."
        )

        # 13. API Access Request
        upsert_intent(db, "API_ACCESS_REQUEST", 
            ["API access", "trade data API", "developer API", "integrate API", "data API", "API documentation", "API pricing"],
            "We offer API access for seamless integration of trade data into your system.\nPlease share your use case and technical requirements, and our team will assist you with API details and access."
        )

        db.commit()
        print("Intent configurations seeded successfully.")
    except Exception as e:
        print(f"Seeding failed: {str(e)}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_intents()
