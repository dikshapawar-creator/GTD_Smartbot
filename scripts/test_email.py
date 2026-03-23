import sys
import os

# Add the parent directory to sys.path to import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.email_service import send_confirmation_email
from app.core.config import settings

def test_email():
    print(f"Testing email sending for {settings.SMTP_USER}...")
    
    # Replace with a real recipient email for testing if needed
    recipient = "dikshapawar271@gmail.com" # Using a placeholder, user can modify
    
    success = send_confirmation_email(
        recipient_email=recipient,
        name="Test User",
        product="Trade Intelligence Demo",
        country="India"
    )
    
    if success:
        print(f"✅ Test email sent successfully to {recipient}")
    else:
        print(f"❌ Failed to send test email. Check logs for details.")

if __name__ == "__main__":
    test_email()
