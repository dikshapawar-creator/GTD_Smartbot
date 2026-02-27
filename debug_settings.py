from app.core.config import settings
import os

print(f"CWD: {os.getcwd()}")
print(f".env exists: {os.path.exists('.env')}")
try:
    print(f"ADMIN_SETUP_TOKEN: {settings.ADMIN_SETUP_TOKEN}")
    print("Settings loaded successfully!")
except Exception as e:
    print(f"Error loading settings: {e}")
