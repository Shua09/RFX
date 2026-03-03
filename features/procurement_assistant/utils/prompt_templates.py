
EXTRACTION_SYSTEM_PROMPT = """You are an AI assistant specialized in extracting procurement information from natural language requests.

Extract the information and return it as a structured JSON following these examples:

EXAMPLE 1 - Basic laptop request:
User: "I want to buy 10 dell laptops, 10 acer laptops, budget 250k"
Output:
{
  "items": [
    {"category": "Laptops", "brand": "Dell", "quantity": 10},
    {"category": "Laptops", "brand": "Acer", "quantity": 10}
  ],
  "budget_total": 250000,
  "currency": "USD",
  "priority": "medium"
}

EXAMPLE 2 - Request with specifications:
User: "Need 5 dell xps laptops with 16GB RAM and 512GB SSD, deliver to Manila by Friday"
Output:
{
  "items": [
    {
      "category": "Laptops", 
      "brand": "Dell", 
      "quantity": 5,
      "specifications": {
        "model": "XPS",
        "ram": "16GB",
        "storage": "512GB SSD"
      }
    }
  ],
  "delivery_location": "Manila",
  "delivery_date": "Friday",
  "priority": "high"
}

EXAMPLE 3 - Multiple items with budget per unit:
User: "Buy 50 office chairs at $100 each, and 20 desks at $250 each. Total budget $10,000"
Output:
{
  "items": [
    {"category": "Office Chairs", "quantity": 50, "budget_per_unit": 100},
    {"category": "Desks", "quantity": 20, "budget_per_unit": 250}
  ],
  "budget_total": 10000,
  "currency": "USD"
}

EXAMPLE 4 - Complex request with payment terms:
User: "Purchase 3 server racks for $5000 total, net 30 payment, deliver to data center"
Output:
{
  "items": [
    {"category": "Server Racks", "quantity": 3, "budget_per_unit": 1666.67}
  ],
  "budget_total": 5000,
  "currency": "USD",
  "delivery_location": "data center",
  "payment_terms": "net 30"
}

Now extract the following user request and return ONLY the JSON in the same format:"""

# Prompt for detecting user intent
INTENT_DETECTION_PROMPT = """You are analyzing a procurement conversation. Determine the user's intent based on their message and the current context.

Current conversation state: {state}
Current request summary: {request_summary}

User message: "{message}"

Classify the intent as one of these categories:

- confirm: User wants to confirm/approve the current request
  Examples: "yes", "confirm", "that's correct", "proceed", "looks good", "confirm the request"

- cancel: User wants to cancel/abort the entire request
  Examples: "cancel", "stop", "forget it", "never mind", "abort", "scrap this"

- add: User wants to add new items to the request
  Examples: "add 10 more laptops", "also include 5 monitors", "I need additional 20 chairs", "plus 3 printers"
  
- remove: User wants to remove existing items
  Examples: "remove the acer laptops", "delete the monitors", "take out the dell items", "don't include the chairs"
  
- modify_quantity: User wants to change quantities of existing items
  Examples: "change dell to 15", "make the monitors 20 instead", "update laptop quantity to 25", "double the chairs"
  
- modify_price: User wants to change prices or budget
  Examples: "make them 50000 each", "price should be 1000 per unit", "budget is 300k total", "cost per item is 750"
  
- modify_specs: User wants to change specifications
  Examples: "need 16GB RAM instead", "change to SSD storage", "make them XPS models", "with i7 processor"
  
- modify_general: User wants to make unspecified changes
  Examples: "modify the request", "make some changes", "update the items", "I want to change something"
  
- unknown: Cannot determine intent clearly

Consider the context - if the user mentions specific items that exist in the current request, it's likely a modification.
If they mention new items not in the current request, it's likely an addition.

Return ONLY the intent category name (e.g., "add", "modify_quantity", "confirm", etc.)"""

# Prompt for merging requests with examples
REQUEST_MERGE_PROMPT = """You are an AI assistant that helps merge procurement requests. You have the current request and a user's modification message.

Your task: Update the current request based on the user's message.

CURRENT REQUEST:
{original_request}

USER MESSAGE: "{modification_message}"

Follow these rules:
1. Preserve all fields from the current request unless explicitly changed
2. For quantity changes, update the specific item quantities
3. For price changes, update unit_price or budget_total as appropriate
4. For additions, add new items to the items array
5. For removals, remove the specified items
6. For specification changes, update the specifications of matching items

EXAMPLES:

Example 1 - Quantity change:
Current: {{"items": [{{"category": "Laptops", "brand": "Dell", "quantity": 10}}]}}
User: "change dell to 15"
Output: {{"items": [{{"category": "Laptops", "brand": "Dell", "quantity": 15}}]}}

Example 2 - Price change:
Current: {{"items": [{{"category": "Laptops", "brand": "Dell", "quantity": 10, "unit_price": 50000}}]}}
User: "make them 55000 each"
Output: {{"items": [{{"category": "Laptops", "brand": "Dell", "quantity": 10, "unit_price": 55000}}]}}

Example 3 - Add items:
Current: {{"items": [{{"category": "Laptops", "brand": "Dell", "quantity": 10}}]}}
User: "add 5 monitors"
Output: {{"items": [{{"category": "Laptops", "brand": "Dell", "quantity": 10}}, {{"category": "Monitors", "quantity": 5}}]}}

Example 4 - Remove items:
Current: {{"items": [{{"category": "Laptops", "brand": "Dell", "quantity": 10}}, {{"category": "Laptops", "brand": "Acer", "quantity": 5}}]}}
User: "remove acer"
Output: {{"items": [{{"category": "Laptops", "brand": "Dell", "quantity": 10}}]}}

Example 5 - Mixed changes:
Current: {{"items": [{{"category": "Laptops", "brand": "Dell", "quantity": 10, "unit_price": 50000}}], "budget_total": 500000}}
User: "change dell to 15 and make them 45000 each, also add 10 chairs at 2000 each"
Output: {{
  "items": [
    {{"category": "Laptops", "brand": "Dell", "quantity": 15, "unit_price": 45000}},
    {{"category": "Chairs", "quantity": 10, "unit_price": 2000}}
  ],
  "budget_total": 500000
}}

Now process the user's message and return ONLY the updated JSON object:"""

# Confirmation message template - Python will fill this
CONFIRMATION_TEMPLATE = """Your request has been received. Please confirm the following items:

{items_list}
{budget_text}
{delivery_text}
{payment_text}
{priority_text}

Would you like to:
1. ✅ Confirm and proceed (type "confirm")
2. ➕ Add more items (type "add [items]")
3. ✏️ Modify existing items (type "modify [changes]")
4. ❌ Cancel request (type "cancel")"""