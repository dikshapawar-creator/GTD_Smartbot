import requests
import json

def test_submit():
    url = "http://127.0.0.1:8000/leads/submit"
    payload = {
        "full_name": "Antigravity Test",
        "company_name": "GTT Support",
        "business_email": "test@gtt-service.com",
        "contact_number": "123",
        "hp_field": ""
    }
    
    print(f"Sending request to {url}...")
    try:
        response = requests.post(
            url, 
            json=payload,
            headers={"Origin": "http://192.168.1.58:3000"} # Test CORS with network IP
        )
        print(f"Status Code: {response.status_code}")
        print("Headers:")
        print(json.dumps(dict(response.headers), indent=2))
        print("Response Body:")
        print(response.text)
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_submit()
