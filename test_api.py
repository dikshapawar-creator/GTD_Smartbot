import urllib.request
import json
import urllib.parse
import urllib.error

BASE_URL = "http://127.0.0.1:8000"

def test_session_init():
    print("Testing /chat/session/init...")
    try:
        req = urllib.request.Request(f"{BASE_URL}/chat/session/init", method="POST")
        req.add_header('Content-Type', 'application/json')
        # We need an empty body for POST if not sending data, or at least length 0
        with urllib.request.urlopen(req, data=b"{}") as response:
            status_code = response.getcode()
            print(f"Status Code: {status_code}")
            response_body = response.read().decode('utf-8')
            print(f"Response: {response_body}")
            
            data = json.loads(response_body)
            if data.get("type") == "CTA" and data.get("cta_label") == "Book Demo":
                print("SUCCESS: Session Init (New) returned CTA.")
            else:
                print("FAILURE: Session Init (New) did NOT return expected CTA.")
            
            # Test Resumed Session
            print("Testing Resumed Session...")
            cookie_header = response.getheader('Set-Cookie')
            if cookie_header:
                req_resume = urllib.request.Request(f"{BASE_URL}/chat/session/init", method="POST")
                req_resume.add_header('Cookie', cookie_header)
                req_resume.add_header('Content-Type', 'application/json')
                with urllib.request.urlopen(req_resume, data=b"{}") as response_resume:
                    body_resume = response_resume.read().decode('utf-8')
                    data_resume = json.loads(body_resume)
                    if data_resume.get("type") == "CTA" and data_resume.get("cta_label") == "Book Demo":
                        print("SUCCESS: Session Init (Resumed) returned CTA.")
                    else:
                        print(f"FAILURE: Session Init (Resumed) returned: {data_resume}")
            else:
                print("WARNING: No Set-Cookie header received, cannot test resumption.")
            
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} - {e.reason}")
        print(e.read().decode('utf-8'))
    except Exception as e:
        print(f"Error: {e}")

def test_lead_submit():
    print("\nTesting /leads/submit...")
    payload = {
        "full_name": "Test User",
        "company_name": "Test Corp",
        "website": "https://test.com",
        "business_email": "test@test.com",
        "contact_number": "1234567890"
    }
    data = json.dumps(payload).encode('utf-8')
    
    try:
        req = urllib.request.Request(f"{BASE_URL}/leads/submit", data=data, method="POST")
        req.add_header('Content-Type', 'application/json')
        
        with urllib.request.urlopen(req) as response:
            status_code = response.getcode()
            print(f"Status Code: {status_code}")
            response_body = response.read().decode('utf-8')
            print(f"Response: {response_body}")
            
            data = json.loads(response_body)
            if status_code == 200 and data.get("success") == True:
                print("SUCCESS: Lead submitted successfully.")
            else:
                print("FAILURE: Lead submission failed.")
            
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} - {e.reason}")
        print(e.read().decode('utf-8'))
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_session_init()
    test_lead_submit()
