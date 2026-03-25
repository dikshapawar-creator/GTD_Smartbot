import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.db.session import engine, SessionLocal
from app.models.intent_config import IntentConfig
from sqlalchemy import text
import traceback

def fix_and_seed():
    print("1. Dropping unique index using AUTOCOMMIT connection...")
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("DROP INDEX IF EXISTS ix_intent_configs_intent_key ON intent_configs;"))
            print("Successfully executed DROP INDEX.")
    except Exception as e:
        print(f"Index drop exception (might be safe to ignore if already dropped): {e}")

    print("2. Reseeding intents for all tenants...")
    db = SessionLocal()
    try:
        tenants = db.execute(text("SELECT id FROM tenants")).fetchall()
        tenant_ids = [t[0] for t in tenants]
        
        # Ensure Tenant 1 is ALWAYS included (Source of Truth)
        if 1 not in tenant_ids:
            tenant_ids.insert(0, 1)

        THANK_YOU_MESSAGE = "Thank you. We will arrange a call for you shortly.\n\nYou can discuss all your questions with our team during the meeting.\n\nRegarding your data and requirements, our team will provide you with the appropriate solution."
        
        fallback_map = {
            "GREETING": "Welcome to GTD Service!\nAre you looking to import or export data?",
            "IMPORT_EXPORT": "We provide comprehensive data for both Import and Export. Which one country are you looking for?",
            "BUYER_SEARCH": "I can help you find verified international buyers for your product.\nTo get started, please share the product name or HS code you are interested in.",
            "SUPPLIER_SEARCH": "I can help you locate verified suppliers and exporters worldwide.\nPlease tell me the product or HS code you want to source.",
            "HS_CODE_SEARCH": "I can help you find HS Codes and tariff details for any product. What are you looking for?",
            "COMPETITOR_ANALYSIS": "Want to track what your competitors are shipping? We provide real-time competitor intelligence.",
            "SHIPMENT_RECORDS": "We provide detailed bill of lading and manifest data for 80+ countries. Want to see a sample?",
            "COUNTRY_TRADE_ANALYSIS": "We have in-depth trade reports for almost every country. Which region interests you?",
            "PRODUCT_MARKET_RESEARCH": "Get insights into global demand and supply trends for your products. Tell me the product name!",
            "PRICING_INQUIRY": "We have flexible plans for every business size. Please use the demo form below to discuss the best pricing for your needs.",
            "REQUEST_DEMO": THANK_YOU_MESSAGE,
            "LEAD_COLLECTION": THANK_YOU_MESSAGE,
            "SALES_DEMO": THANK_YOU_MESSAGE,
            "DEMO": THANK_YOU_MESSAGE,
            "HANDOFF": "I'll connect you with an expert. In the meantime, feel free to book a demo for a priority consultation.",
            "DATA_PROVIDER_DATASOURCE": "We collaborate with data providers who can supply import-export or customs trade data.\nIf you are interested in selling or partnership, please share your company details and type of data you can provide.",
            "API_ACCESS_REQUEST": "We offer API access for seamless integration of trade data into your system.\nPlease share your use case and technical requirements, and our team will assist you with API details and access.",
            "URGENT_SUPPORT": "We understand your request is urgent.\n\nFor immediate assistance, please contact us on WhatsApp: +91 8527376675",
            "FALLBACK_GENERIC": THANK_YOU_MESSAGE,
            "INACTIVITY_NUDGE": "We’ve received your message and will get back to you soon.\n\nFor more details, feel free to reach us anytime:\n💬- https://wa.me/918527376675\n📞 WhatsApp: +91 8527376675\n\nWe’ll be happy to assist you with complete support.\n\nWhatsApp Messenger: More than 2 billion people in over 180 countries use WhatsApp to stay in touch with friends and family, anytime and anywhere.",
            "WELCOME_QUESTION": "Welcome! Are you interested in Import or Export?",
            "TRADE_TYPE_QUESTION": "To provide you with the most accurate trade data for your region, please Book a Demo with our experts.",
            "COUNTRY_QUESTION": "Our database covers 80+ countries. Please use the form below to select your target market and get started.",
            "PRODUCT_QUESTION": "Great choice! To get detailed insights on this product, please Book a Demo with our experts."
        }
        
        keywords_map = {
            "GREETING": ["hi", "hello", "hey", "hii", "greetings", "good morning"],
            "BUYER_SEARCH": ["buyer", "buyers", "find buyers", "who buys", "buyer list", "import", "import data", "find imports"],
            "SUPPLIER_SEARCH": ["supplier", "suppliers", "find suppliers", "who sells", "supplier list", "export", "export data", "find exports"],
            "HS_CODE_SEARCH": ["hs code", "hsn code", "tariff", "classification"],
            "COMPETITOR_ANALYSIS": ["competitor", "competition", "compete", "benchmark"],
            "SHIPMENT_RECORDS": ["records", "shipment details", "bill of lading", "manifest"],
            "COUNTRY_TRADE_ANALYSIS": ["country analysis", "trade by country", "global trade", "bilateral trade data"],
            "PRODUCT_MARKET_RESEARCH": ["market research", "demand", "product research"],
            "PRICING_INQUIRY": ["price", "cost", "pricing", "subscription", "fees", "how much"],
            "REQUEST_DEMO": ["book demo", "schedule demo", "request demo", "trial"],
            "LEAD_COLLECTION": ["contact me", "callback", "call back", "reach out"],
            "DEMO": ["demo", "show me", "tutorial"],
            "IMPORT_EXPORT": ["importing", "exporting", "trade"],
            "HANDOFF": ["agent", "human", "representative", "call me", "talk to person"],
            "DATA_PROVIDER_DATASOURCE": ["data provider", "datasource"],
            "API_ACCESS_REQUEST": ["api", "developer access", "integration"]
        }
        
        for tid in tenant_ids:
            for intent_key, response_text in fallback_map.items():
                kw = keywords_map.get(intent_key, [])
                
                existing = db.query(IntentConfig).filter(
                    IntentConfig.tenant_id == tid,
                    IntentConfig.intent_key == intent_key
                ).first()
                
                if not existing:
                    new_ic = IntentConfig(
                        tenant_id=tid,
                        intent_key=intent_key,
                        keywords=kw,
                        response_text=response_text,
                        metadata_json=None
                    )
                    db.add(new_ic)
                else:
                    existing.keywords = kw
                    existing.response_text = response_text
        
        db.commit()
        print(f"Success: All intents have been seeded perfectly for tenants: {tenant_ids}")
        
    except Exception as e:
        db.rollback()
        print("Failed to seed:")
        traceback.print_exc()
        
    finally:
        db.close()

if __name__ == "__main__":
    fix_and_seed()
