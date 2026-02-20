"""Quick validation test for LeadSubmitRequest enterprise schema."""
from pydantic import ValidationError
from app.schemas.chatbot import LeadSubmitRequest

def test(label, should_fail, **kwargs):
    try:
        r = LeadSubmitRequest(**kwargs)
        if should_fail:
            print(f"FAIL: {label} — should have been rejected but parsed as: {r.contact_number}")
        else:
            print(f"PASS: {label} — parsed OK (phone={r.contact_number}, email={r.business_email})")
    except ValidationError as e:
        if should_fail:
            errs = "; ".join([f"{err['loc'][-1]}: {err['msg']}" for err in e.errors()])
            print(f"PASS: {label} — rejected ({errs})")
        else:
            print(f"FAIL: {label} — unexpected rejection: {e}")

# --- Valid submission ---
test("Valid B2B lead", False,
     full_name="John Doe", company_name="Acme Corp",
     business_email="john@acme.com", contact_number="+919876543210", hp_field="")

# --- Gmail blocked ---
test("Gmail blocked", True,
     full_name="John Doe", company_name="Acme",
     business_email="john@gmail.com", contact_number="+919876543210", hp_field="")

# --- Honeypot triggered ---
test("Honeypot bot", True,
     full_name="Bot", company_name="Spam",
     business_email="bot@enterprise.com", contact_number="+919876543210", hp_field="I am a bot")

# --- Bad phone ---
test("Invalid phone", True,
     full_name="John Doe", company_name="Acme",
     business_email="john@acme.com", contact_number="12345", hp_field="")

# --- Numeric name ---
test("Numeric name", True,
     full_name="12345", company_name="Acme",
     business_email="john@acme.com", contact_number="+919876543210", hp_field="")

# --- Name too short ---
test("Name too short", True,
     full_name="J", company_name="Acme",
     business_email="john@acme.com", contact_number="+919876543210", hp_field="")

print("\nAll tests complete.")
