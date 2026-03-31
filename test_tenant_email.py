import os
import sys
import argparse
from dotenv import load_dotenv

# Add parent directory to path to allow importing app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load env vars
load_dotenv()

from app.services.email_service import send_confirmation_email

def main():
    parser = argparse.ArgumentParser(description='Test Tenant SMTP Configuration')
    parser.add_argument('--tenant_id', type=int, required=True, help='ID of the tenant to test')
    parser.add_argument('--email', type=str, required=True, help='Recipient email address')
    parser.add_argument('--name', type=str, default='Test User', help='Name of the recipient')
    
    args = parser.parse_args()
    
    print(f"--- Email Test Triggered ---")
    print(f"Tenant ID: {args.tenant_id}")
    print(f"Recipient: {args.email}")
    print(f"Name: {args.name}")
    print(f"----------------------------")
    
    success = send_confirmation_email(
        recipient_email=args.email,
        name=args.name,
        product="SMTP Test Drive",
        country="Local Environment",
        tenant_id=args.tenant_id
    )
    
    if success:
        print("\n✅ SUCCESS: Test email sent successfully!")
        print("Please check the recipient's inbox (including Spam folder).")
    else:
        print("\n❌ FAILED: Failed to send test email.")
        print("Check backend logs for detailed SMTP error messages.")

if __name__ == "__main__":
    main()
