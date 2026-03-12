#!/usr/bin/env python3
"""
Quick test to verify visitor_uuid field is working in session creation
"""
import requests
import uuid
import json

# Test endpoint
URL = "https://api-test.gtdservice.com/chat/session/init"

def test_session_init():
    visitor_uuid = str(uuid.uuid4())
    print(f"Testing session init with visitor_uuid: {visitor_uuid}")
    
    payload = {"visitor_uuid": visitor_uuid}
    
    try:
        response = requests.post(URL, json=payload, timeout=10)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print("✅ SUCCESS - Session created successfully")
            print(f"Session ID: {data.get('session_id', 'N/A')}")
            print(f"Is Returning: {data.get('is_returning', 'N/A')}")
        else:
            print("❌ FAILED - Error response:")
            try:
                error_data = response.json()
                print(json.dumps(error_data, indent=2))
            except:
                print(response.text)
                
    except requests.exceptions.RequestException as e:
        print(f"❌ REQUEST FAILED: {e}")

if __name__ == "__main__":
    test_session_init()