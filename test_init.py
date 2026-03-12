import requests
import uuid

URL = "http://127.0.0.1:8000/chat/session/init"

def test_init():
    visitor_uuid = str(uuid.uuid4())
    print(f"Testing session init with visitor_uuid: {visitor_uuid}")
    
    try:
        response = requests.post(URL, json={"visitor_uuid": visitor_uuid})
        print(f"Status Code: {response.status_code}")
        print(f"Response JSON: {response.json()}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_init()
