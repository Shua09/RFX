#!/usr/bin/env python3
"""
Comprehensive Test Script for RFQ Procurement with Supplier Matching
Tests the complete flow: RFQ creation -> Supplier Matching -> Email Sending

Run with: python test_supplier_matching.py
"""

import requests
import json
import time
import os
import sys
from pprint import pprint
from datetime import datetime

# Add the project root to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..', '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
    print(f"📁 Added project root to path: {project_root}")

# Also add the src directory to path
src_dir = os.path.join(project_root, 'src')
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

# Now we can import from src.common
try:
    from src.common.config import Config
    print("✅ Successfully imported Config")
except ImportError as e:
    print(f"❌ Failed to import Config: {e}")
    print("Using fallback configuration...")
    from dotenv import load_dotenv
    load_dotenv()
    
    class Config:
        APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5000")
        SMTP_HOST = os.getenv("SMTP_HOST")
        SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
        SMTP_EMAIL = os.getenv("SMTP_EMAIL")
        SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
        SENDER_NAME = os.getenv("SENDER_NAME", "Procurement Department")
        AUTO_MATCH_SUPPLIERS = os.getenv("AUTO_MATCH_SUPPLIERS", "true")
        EMAIL_TEST_MODE = os.getenv("EMAIL_TEST_MODE", "false")

# Configuration
BASE_URL = "http://localhost:5000/RFQ/api/procurement"
TEST_EMAIL = "zeus@delcavisiontech.com"  # Your email for testing
APP_BASE_URL = getattr(Config, 'APP_BASE_URL', 'http://localhost:5000')

# We'll use a session to maintain cookies, but also track session_id manually
session = requests.Session()
current_session_id = None

# Colors for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RED = '\033[91m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_header(text):
    """Print a formatted header"""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*80}")
    print(f" {text}")
    print(f"{'='*80}{Colors.END}\n")

def print_step(step_num, text):
    """Print a step indicator"""
    print(f"{Colors.BOLD}{Colors.BLUE}▶ Step {step_num}: {text}{Colors.END}")

def print_success(text):
    """Print success message"""
    print(f"{Colors.GREEN}✅ {text}{Colors.END}")

def print_info(text):
    """Print info message"""
    print(f"{Colors.YELLOW}ℹ️ {text}{Colors.END}")

def print_error(text):
    """Print error message"""
    print(f"{Colors.RED}❌ {text}{Colors.END}")

def print_warning(text):
    """Print warning message"""
    print(f"{Colors.MAGENTA}⚠️ {text}{Colors.END}")

def print_json(data, title=None):
    """Pretty print JSON data"""
    if title:
        print(f"\n{Colors.MAGENTA}{title}:{Colors.END}")
    print(json.dumps(data, indent=2, default=str))

def make_request(endpoint, method="POST", payload=None, expected_status=200):
    """Make an API request and return response"""
    global current_session_id
    url = f"{BASE_URL}{endpoint}"
    
    try:
        # Add session_id to payload if we have one
        if payload is None:
            payload = {}
        
        if current_session_id and method.upper() == "POST":
            payload['session_id'] = current_session_id
            print_info(f"Using session_id: {current_session_id}")
        
        print_info(f"Making {method} request to {url}")
        if payload and method.upper() == "POST":
            print_info(f"Payload: {json.dumps(payload, indent=2)}")
        
        if method.upper() == "GET":
            # For GET requests, add session_id as query parameter
            if current_session_id:
                url = f"{url}?session_id={current_session_id}"
            response = session.get(url)
        else:
            response = session.post(url, json=payload)
        
        if response.status_code != expected_status:
            print_error(f"Expected status {expected_status}, got {response.status_code}")
            print(f"Response: {response.text}")
            return None
        
        data = response.json()
        
        # Extract and store session_id from response if present
        if isinstance(data, dict) and data.get('session_id'):
            current_session_id = data['session_id']
            print_info(f"Updated session_id: {current_session_id}")
        
        return data
    except requests.exceptions.ConnectionError:
        print_error(f"Cannot connect to {url}. Make sure your Flask app is running!")
        print_info("Run your Flask app first with: python run.py")
        return None
    except Exception as e:
        print_error(f"Request failed: {str(e)}")
        return None

def test_initial_coconut_request():
    """Test initial procurement request for coconut products"""
    print_step(1, "Creating RFQ for Coconut Products")
    
    payload = {
        "message": "I need to buy 500kg of desiccated coconut, 200 liters of coconut oil, and 1000 pieces of coconut seedlings. Budget is 500,000 PHP. Delivery to Manila by end of month."
    }
    
    response = make_request("/chat", payload=payload)
    
    if response and response.get('status') == 'success':
        print_success("RFQ request created successfully")
        print_json(response.get('json_data', {}), "Extracted RFQ Data")
        
        # Verify items were extracted
        items = response.get('json_data', {}).get('items', [])
        print_info(f"Extracted {len(items)} items:")
        for item in items:
            brand = item.get('brand', '')
            category = item.get('category', '')
            quantity = item.get('quantity', 0)
            unit = item.get('unit', '')
            quantity_str = f"{quantity} {unit}".strip() if unit else str(quantity)
            print(f"   - {quantity_str} of {category} {brand}")
        
        return response
    else:
        print_error("Failed to create RFQ request")
        if response:
            print_json(response, "Error Response")
        return None

def test_add_more_items():
    """Test adding more coconut items"""
    print_step(2, "Adding More Coconut Items")
    
    payload = {
        "message": "add 300 pieces of coconut sugar and 150 bags of coco coir"
    }
    
    response = make_request("/chat", payload=payload)
    
    if response and response.get('status') == 'success':
        print_success("Add items request processed")
        print_info(f"State: {response.get('state')}")
        return response
    else:
        print_error("Failed to add items")
        return None

def test_modify_quantities():
    """Test modifying quantities"""
    print_step(3, "Modifying Quantities")
    
    payload = {
        "message": "change desiccated coconut to 750kg and coconut oil to 300 liters"
    }
    
    response = make_request("/chat", payload=payload)
    
    if response and response.get('status') == 'success':
        print_success("Modify request processed")
        
        if response.get('changes'):
            print_info(f"Changes made: {len(response['changes'])}")
            for change in response['changes']:
                print(f"   {change}")
        
        # Show updated items
        items = response.get('json_data', {}).get('items', [])
        print_info("Updated items:")
        for item in items:
            brand = item.get('brand', '')
            category = item.get('category', '')
            quantity = item.get('quantity', 0)
            unit = item.get('unit', '')
            quantity_str = f"{quantity} {unit}".strip() if unit else str(quantity)
            brand_str = f"{brand} " if brand else ""
            print(f"   - {quantity_str} {brand_str}{category}")
        
        return response
    else:
        print_error("Failed to modify items")
        return None

def test_get_context():
    """Get current conversation context"""
    print_step(4, "Checking Conversation Context")
    
    response = make_request("/context", method="GET")
    
    if response and response.get('status') == 'success':
        context = response.get('context', {})
        state = context.get('state')
        items = context.get('current_request', {}).get('items', [])
        
        print_success(f"Current state: {state}")
        print_info(f"Items in context: {len(items)}")
        
        total_qty = sum(item.get('quantity', 0) for item in items)
        print_info(f"Total quantity: {total_qty}")
        
        return response
    else:
        print_warning("Could not get context - this is normal if session was just created")
        return None

def test_confirm_rfq():
    """Confirm the RFQ - This should trigger supplier matching"""
    print_step(5, "Confirming RFQ (This will trigger supplier matching)")
    print_info(f"Supplier matching will look for suppliers with email: {TEST_EMAIL}")
    
    payload = {
        "message": "confirm"
    }
    
    response = make_request("/chat", payload=payload)
    
    if response and response.get('status') == 'success':
        rfq_id = response.get('rfq_id')
        print_success(f"RFQ confirmed! RFQ ID: {rfq_id}")
        
        # Check if supplier matching was triggered
        if response.get('supplier_matching'):
            matching = response['supplier_matching']
            print_success(f"Supplier matching completed! Found {matching.get('total_found', 0)} suppliers")
            
            if matching.get('matches'):
                print_info("Matched suppliers:")
                for match in matching['matches']:
                    email_indicator = "📧 (Your email)" if match.get('email') == TEST_EMAIL else ""
                    print(f"   - {match.get('company_name')} (Score: {match.get('match_score')}%) {email_indicator}")
        else:
            print_warning("Supplier matching was not triggered or returned no results")
        
        return response
    else:
        print_error("Failed to confirm RFQ")
        return None

def test_check_rfq_suppliers(rfq_id):
    """Check the suppliers matched to this RFQ"""
    print_step(6, f"Checking Suppliers for RFQ {rfq_id}")
    
    response = make_request(f"/rfq/{rfq_id}/suppliers", method="GET")
    
    if response and response.get('status') == 'success':
        suppliers = response.get('suppliers', [])
        print_success(f"Found {len(suppliers)} suppliers for RFQ {rfq_id}")
        
        your_email_found = False
        for supplier in suppliers:
            email_indicator = "📧 (YOUR EMAIL)" if supplier.get('email') == TEST_EMAIL else ""
            if supplier.get('email') == TEST_EMAIL:
                your_email_found = True
            
            print(f"\n   Company: {supplier.get('company_name')} {email_indicator}")
            print(f"   Match Score: {supplier.get('match_score')}%")
            print(f"   Status: {supplier.get('status')}")
            print(f"   Email Sent: {supplier.get('email_sent')}")
            
            if supplier.get('email') == TEST_EMAIL:
                print(f"   ✅ This email ({TEST_EMAIL}) received the RFQ notification")
        
        if not your_email_found and suppliers:
            print_warning(f"Your email {TEST_EMAIL} was not found in the matched suppliers")
        
        return response
    else:
        print_error(f"Failed to get suppliers for RFQ {rfq_id}")
        return None

def test_reset_conversation():
    """Reset the conversation"""
    print_step(0, "Resetting Conversation")
    
    global current_session_id
    current_session_id = None  # Clear the session ID
    
    response = make_request("/reset", payload={})
    
    if response and response.get('status') == 'success':
        print_success("Conversation reset")
        return response
    else:
        print_warning("Failed to reset conversation - continuing anyway")
        return None

def check_database_entries(rfq_id):
    """Check database entries for the RFQ"""
    print_step(7, "Checking Database Entries")
    
    # Get suppliers for this RFQ
    response = make_request(f"/rfq/{rfq_id}/suppliers", method="GET")
    
    if response and response.get('status') == 'success':
        suppliers = response.get('suppliers', [])
        
        print_info(f"Found {len(suppliers)} entries in rfq_suppliers table")
        
        for supplier in suppliers:
            if supplier.get('email') == TEST_EMAIL:
                print(f"\n{Colors.BOLD}{Colors.GREEN}✅ YOUR EMAIL FOUND IN DATABASE{Colors.END}")
                print(f"   mapping_id: {supplier.get('mapping_id')}")
                print(f"   match_score: {supplier.get('match_score')}")
                print(f"   status: {supplier.get('status')}")
                print(f"   email_sent: {supplier.get('email_sent')}")
                print(f"   created_at: {supplier.get('created_at')}")
                
                # Return the mapping_id for possible resend
                return supplier.get('mapping_id')
    
    return None

def test_complete_flow():
    """Test the complete RFQ flow with supplier matching"""
    print_header("🚀 COMPLETE RFQ SUPPLIER MATCHING TEST")
    print_info(f"Test Email: {TEST_EMAIL}")
    print_info(f"Base URL: {APP_BASE_URL}")
    print_info(f"API Endpoint: {BASE_URL}")
    
    # Reset to start fresh
    test_reset_conversation()
    time.sleep(1)
    
    # Step 1: Create RFQ
    result1 = test_initial_coconut_request()
    if not result1:
        print_error("Failed at step 1 - cannot continue")
        return False
    time.sleep(1)
    
    # Step 2: Add more items
    result2 = test_add_more_items()
    time.sleep(1)
    
    # Step 3: Modify quantities
    result3 = test_modify_quantities()
    time.sleep(1)
    
    # Step 4: Try to get context (optional)
    test_get_context()
    time.sleep(1)
    
    # Step 5: Confirm RFQ (triggers supplier matching)
    result5 = test_confirm_rfq()
    if not result5:
        print_error("Failed at step 5 - confirmation failed")
        return False
    
    rfq_id = result5.get('rfq_id')
    time.sleep(2)  # Wait for supplier matching to complete
    
    # Step 6: Check suppliers for this RFQ
    result6 = test_check_rfq_suppliers(rfq_id)
    
    # Step 7: Check database entries
    if result6 and result6.get('suppliers'):
        check_database_entries(rfq_id)
    
    # Summary
    print_header("📊 TEST SUMMARY")
    print_success(f"RFQ ID: {rfq_id}")
    print_success(f"Test Email: {TEST_EMAIL}")
    
    if result6 and result6.get('suppliers'):
        your_email_suppliers = [s for s in result6['suppliers'] if s.get('email') == TEST_EMAIL]
        if your_email_suppliers:
            print_success(f"✅ Your email ({TEST_EMAIL}) was found in matched suppliers!")
            for s in your_email_suppliers:
                print(f"   - {s.get('company_name')} (Score: {s.get('match_score')}%)")
                print(f"     Status: {s.get('status')}, Email Sent: {s.get('email_sent')}")
        else:
            print_warning(f"Your email ({TEST_EMAIL}) was NOT found in matched suppliers")
    else:
        print_warning("No suppliers were matched for this RFQ")
    
    return True

if __name__ == "__main__":
    print(f"{Colors.BOLD}{Colors.MAGENTA}")
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║     RFQ SUPPLIER MATCHING COMPREHENSIVE TEST SCRIPT         ║")
    print("║           Testing with email: zeus@delcavisiontech.com      ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print(f"{Colors.END}")
    
    # Check if Flask app is running
    try:
        response = requests.get("http://localhost:5000/", timeout=2)
        print_success("Flask app is running!")
    except:
        print_error("Cannot connect to Flask app. Make sure it's running!")
        print_info("Start your Flask app with: python run.py")
        print_info("Then run this test script again.")
        sys.exit(1)
    
    # Run the complete flow test
    test_complete_flow()