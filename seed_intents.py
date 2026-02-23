"""
Seed script — Populates initial intent configurations for the GTT Smartbot.
"""
from app.db.session import SessionLocal
from app.models.intent_config import IntentConfig

def seed_intents():
    db = SessionLocal()
    try:
        # 1. Greeting Config
        greeting = db.query(IntentConfig).filter(IntentConfig.intent_key == "GREETING").first()
        if not greeting:
            greeting = IntentConfig(
                intent_key="GREETING",
                keywords=["hi", "hello", "hey", "hii", "heey", "hola", "good morning", "good afternoon", "good evening"],
                response_text="Welcome to GTD Service!\nAre you looking to import or export data?\nI’m here to assist you — please let me know how I can help.",
                metadata_json={"cta_label": "Book Demo", "action": "OPEN_LEAD_FORM"}
            )
            db.add(greeting)
        else:
            greeting.response_text = "Welcome to GTD Service!\nAre you looking to import or export data?\nI’m here to assist you — please let me know how I can help."
            greeting.metadata_json = {"cta_label": "Book Demo", "action": "OPEN_LEAD_FORM"}


        # 2. Sales/Demo Config
        sales = db.query(IntentConfig).filter(IntentConfig.intent_key == "SALES_DEMO").first()
        if not sales:
            sales = IntentConfig(
                intent_key="SALES_DEMO",
                keywords=["demo", "book demo", "more details", "pricing", "plans", "import data", "talk to sales", "interested", "contact", "get started", "business inquiry"],
                response_text="I’d be grateful to help you with that. Please book a demo so we can guide you properly.",
                metadata_json={"cta_label": "Book Demo", "action": "OPEN_LEAD_FORM"}
            )
            db.add(sales)

        db.commit()
        print("Intent configurations seeded successfully.")
    except Exception as e:
        print(f"Seeding failed: {str(e)}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_intents()
