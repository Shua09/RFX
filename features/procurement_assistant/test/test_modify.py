# test_modify.py
import requests
import json

base_url = "http://localhost:5000/RFQ/api/procurement"

def test_modify():
    """Test the modify functionality specifically"""
    
    # Step 1: Create initial request
    print("\n1. Creating initial request...")
    payload = {"message": "I want 10 dell laptops, 10 acer laptops, budget 250k"}
    response = requests.post(f"{base_url}/chat", json=payload)
    data = response.json()
    print(f"✅ Initial request created with {len(data['json_data']['items'])} items")
    
    # Step 2: Modify the request
    print("\n2. Modifying request...")
    payload = {"message": "change dell laptops to 20"}
    response = requests.post(f"{base_url}/chat", json=payload)
    data = response.json()
    
    print(f"Status Code: {response.status_code}")
    print(f"Response:")
    print(f"  Message: {data['message'][:100]}...")
    
    # Check if Dell quantity changed
    if 'json_data' in data:
        for item in data['json_data']['items']:
            if item['brand'] == 'Dell':
                print(f"  ✅ Dell quantity is now: {item['quantity']}")
    
    # Step 3: Add another item
    print("\n3. Adding Samsung laptops...")
    payload = {"message": "add 15 samsung laptops"}
    response = requests.post(f"{base_url}/chat", json=payload)
    data = response.json()
    
    if 'json_data' in data:
        items = data['json_data']['items']
        print(f"  Total items now: {len(items)}")
        for item in items:
            print(f"    - {item['quantity']} {item['brand']} {item['category']}")

if __name__ == "__main__":
    test_modify()