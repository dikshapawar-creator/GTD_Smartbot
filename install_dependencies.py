#!/usr/bin/env python3
"""
Installation script for Live Chat dependencies
"""
import subprocess
import sys
import os

def install_requirements():
    """Install required packages."""
    print("🚀 Installing Live Chat dependencies...")
    
    try:
        # Install requirements
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "-r", "requirements.txt"
        ])
        print("✅ Dependencies installed successfully!")
        
        # Test imports
        print("🧪 Testing imports...")
            
        try:
            from app.models.chat_session import ChatSession
            from app.models.chat_message import ChatMessage
            print("✅ Models imported successfully")
        except ImportError as e:
            print(f"❌ Model import failed: {e}")
            return False
            
        try:
            from app.services.session_service import SessionService
            from app.services.live_chat_socket import LiveChatSocketManager
            print("✅ Services imported successfully")
        except ImportError as e:
            print(f"❌ Service import failed: {e}")
            return False
            
        print("\n🎉 All dependencies installed and tested successfully!")
        print("\nNext steps:")
        print("1. Run database migration: alembic upgrade head")
        print("2. Start the server: uvicorn app.main:app --reload")
        print("3. Navigate to /crm/dashboard/live-chat in your frontend")
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install dependencies: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

if __name__ == "__main__":
    if not os.path.exists("requirements.txt"):
        print("❌ requirements.txt not found. Make sure you're in the Backend_bot directory.")
        sys.exit(1)
        
    success = install_requirements()
    sys.exit(0 if success else 1)