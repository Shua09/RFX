# src/core/conversation_manager.py
from typing import Dict, Any, Optional
from datetime import datetime
import json
import re

from ..common import get_logger, llm_service
from ..features.procurement_assistant.models.conversation_model import (
    ConversationContext, ConversationState, UserIntent
)
from ..features.procurement_assistant.utils.prompt_templates import (
    INTENT_DETECTION_PROMPT, REQUEST_MERGE_PROMPT, CONFIRMATION_TEMPLATE
)

logger = get_logger(__name__)

class ConversationManager:
    """Manages conversation state and intent detection"""
    
    def __init__(self):
        self.sessions: Dict[str, ConversationContext] = {}
        # Use the suggested model
        self.model_name = "ibm/granite-3-8b-instruct"
        self.params = {
            "decoding_method": "greedy",
            "min_new_tokens": 1,
            "max_new_tokens": 4000,
        }
    
    def get_or_create_context(self, session_id: str) -> ConversationContext:
        """Get existing context or create new one"""
        if session_id not in self.sessions:
            self.sessions[session_id] = ConversationContext(session_id=session_id)
        return self.sessions[session_id]

    def detect_intent(self, message: str, context: ConversationContext) -> UserIntent:
        """Detect user intent using LLM - Enhanced for natural language modifications"""
        try:
            # Quick check for simple confirm/cancel first
            message_lower = message.lower().strip()
            
            # Fast path for simple confirmations
            if message_lower in ['confirm', 'yes', 'correct', 'proceed', 'that\'s right', 'looks good']:
                return UserIntent.CONFIRM
            
            # Fast path for simple cancellations
            if message_lower in ['cancel', 'stop', 'quit', 'abort', 'forget it', 'never mind']:
                return UserIntent.CANCEL
            
            # If we're in AWAITING_CONFIRMATION state and message has substance, it's likely a modification
            if context.state == ConversationState.AWAITING_CONFIRMATION and len(message.split()) > 2:
                # Check if it contains modification indicators
                if self._contains_modification_indicators(message):
                    # Let the AI determine the specific intent
                    return self._detect_intent_with_ai(message, context)
            
            # For other cases, use AI
            return self._detect_intent_with_ai(message, context)
            
        except Exception as e:
            logger.error(f"Intent detection failed: {str(e)}")
            return self._keyword_intent_fallback(message)
    
    def _contains_modification_indicators(self, message: str) -> bool:
        """Check if message contains indicators of modification intent"""
        message_lower = message.lower()
        
        # Patterns that suggest modification
        patterns = [
            r'\d+\s+(laptops|monitors|chairs|items|units|pc|pcs)',
            r'(add|include|plus|additional)',
            r'(change|modify|update|edit)',
            r'(remove|delete|take\s+out|drop)',
            r'(price|cost|budget|each|per)',
            r'(to|from|instead of|replace)',
            r'\d+\s*(php|pesos|\$|usd)',
            r'(make|set|change)\s+(it|them|the)'
        ]
        
        for pattern in patterns:
            if re.search(pattern, message_lower):
                return True
        return False
    
    def _detect_intent_with_ai(self, message: str, context: ConversationContext) -> UserIntent:
        """Use AI to detect intent with enhanced prompts"""
        try:
            # Create a summary of the current request for context
            request_summary = "No current request"
            if context.current_request and context.current_request.get('items'):
                items = context.current_request['items']
                item_descriptions = []
                for item in items[:3]:  # Summarize first 3 items
                    brand = item.get('brand', '')
                    category = item.get('category', '')
                    qty = item.get('quantity', 0)
                    if brand:
                        item_descriptions.append(f"{qty} {brand} {category}")
                    else:
                        item_descriptions.append(f"{qty} {category}")
                
                if len(items) > 3:
                    item_descriptions.append(f"... and {len(items)-3} more")
                
                request_summary = ", ".join(item_descriptions)
            
            # Enhanced intent detection prompt
            prompt = f"""You are analyzing a procurement conversation. Determine the user's intent based on their message and the current context.

Current conversation state: {context.state.value if context.state else "INITIAL"}
Current request summary: {request_summary}

User message: "{message}"

Classify the intent as one of these categories:

- confirm: User wants to confirm/approve the current request
  Examples: "yes", "confirm", "that's correct", "proceed", "looks good", "confirm the request"

- cancel: User wants to cancel/abort the entire request
  Examples: "cancel", "stop", "forget it", "never mind", "abort", "scrap this"

- add: User wants to add new items to the request
  Examples: "add 10 more laptops", "also include 5 monitors", "I need additional 20 chairs", "plus 3 printers", "I want to add more items 20 Monitors"
  
- remove: User wants to remove existing items
  Examples: "remove the acer laptops", "delete the monitors", "take out the dell items", "don't include the chairs"
  
- modify: User wants to change quantities, prices, or specifications
  Examples: "change dell to 15", "make the monitors 20 instead", "update laptop quantity to 25", 
           "make the 20 Monitors to be 10 at a price of 50,000 PHP each", "double the chairs", 
           "change price to 50000 each", "make them 55000"

- unknown: Cannot determine intent clearly

Consider the context - if the user mentions specific items that exist in the current request, it's likely a modification.
If they mention new items not in the current request, it's likely an addition.

Return ONLY the intent category name (e.g., "confirm", "add", "modify", etc.)."""
            
            if llm_service is None:
                return self._keyword_intent_fallback(message)
            
            try:
                response = llm_service.invoke_with_recovery(
                    model_name=self.model_name,
                    params=self.params,
                    prompt=prompt,
                    max_retries=1
                )
                
                # Clean the response
                response = response.strip().lower()
                
                # Remove common prefixes
                prefixes = ['intent:', 'answer:', 'the intent is:', 'the intent word is:', 'result:']
                for prefix in prefixes:
                    if prefix in response:
                        parts = response.split(prefix, 1)
                        if len(parts) > 1:
                            response = parts[1].strip()
                
                # Remove any bracketed explanations
                response = re.sub(r'\[.*?\]', '', response)
                
                # Take just the first word
                words = response.split()
                intent_word = words[0].strip('.,!?') if words else ""
                
                logger.info(f"AI intent detection: {intent_word}")
                
                # Map to UserIntent
                intent_mapping = {
                    'confirm': UserIntent.CONFIRM,
                    'cancel': UserIntent.CANCEL,
                    'add': UserIntent.ADD,
                    'remove': UserIntent.REMOVE,
                    'modify': UserIntent.MODIFY
                }
                
                for key, intent in intent_mapping.items():
                    if key in intent_word:
                        return intent
                
                # Check for variations
                if any(word in intent_word for word in ['confirm', 'yes', 'correct', 'proceed']):
                    return UserIntent.CONFIRM
                elif any(word in intent_word for word in ['add', 'include', 'plus', 'additional']):
                    return UserIntent.ADD
                elif any(word in intent_word for word in ['remove', 'delete', 'drop']):
                    return UserIntent.REMOVE
                elif any(word in intent_word for word in ['change', 'modify', 'update', 'edit']):
                    return UserIntent.MODIFY
                elif any(word in intent_word for word in ['cancel', 'stop', 'abort']):
                    return UserIntent.CANCEL
                    
            except Exception as e:
                logger.error(f"LLM intent detection failed: {str(e)}")
            
            return self._keyword_intent_fallback(message)
            
        except Exception as e:
            logger.error(f"Intent detection with AI failed: {str(e)}")
            return self._keyword_intent_fallback(message)
    
    def _keyword_intent_fallback(self, message: str) -> UserIntent:
        """Simple keyword-based intent detection"""
        message_lower = message.lower()
        
        # Check for confirm
        if any(word in message_lower for word in ['confirm', 'yes', 'correct', 'proceed', "that's right", 'looks good']):
            return UserIntent.CONFIRM
        
        # Check for cancel
        if any(word in message_lower for word in ['cancel', 'stop', 'forget', 'abort', 'never mind']):
            return UserIntent.CANCEL
        
        # Check for add
        if any(word in message_lower for word in ['add', 'include', 'plus', 'another', 'additional', 'more']):
            return UserIntent.ADD
        
        # Check for remove
        if any(word in message_lower for word in ['remove', 'delete', 'take out', 'drop']):
            return UserIntent.REMOVE
        
        # Check for modify (including numbers which often indicate changes)
        modify_keywords = ['change', 'modify', 'update', 'instead', 'replace', 'to', 'from']
        has_number = bool(re.search(r'\d+', message))
        
        if any(word in message_lower for word in modify_keywords) or has_number:
            return UserIntent.MODIFY
        
        return UserIntent.UNKNOWN

    def merge_requests(self, original_request: Dict[str, Any], 
                  modification_message: str) -> Dict[str, Any]:
        """Merge original request with modifications using LLM - Enhanced for natural language"""
        try:
            # Create a more explicit prompt with clear examples for natural language
            prompt = f"""You are helping to merge an existing procurement request with new modifications.

IMPORTANT: You MUST preserve ALL existing items unless explicitly modified or removed.
IMPORTANT: Return ONLY valid JSON without any comments, arrows, or explanatory text.

EXAMPLES OF NATURAL LANGUAGE MODIFICATIONS:

Example 1 - Change quantity:
Original request: {{"items": [{{"category": "Laptops", "brand": "Dell", "quantity": 10}}]}}
User says: "I want to make the 20 Monitors to be 10"
Output: {{"items": [{{"category": "Laptops", "brand": "Dell", "quantity": 10}}]}}

Example 2 - Change quantity and add price:
Original request: {{"items": [{{"category": "Monitors", "quantity": 20}}]}}
User says: "make the 20 Monitors to be 10 at a price of 50,000 PHP each"
Output: {{"items": [{{"category": "Monitors", "quantity": 10, "unit_price": 50000, "currency": "PHP"}}]}}

Example 3 - Add items:
Original request: {{"items": [{{"category": "Laptops", "brand": "Dell", "quantity": 10}}]}}
User says: "I want to add more items 20 Monitors"
Output: {{"items": [{{"category": "Laptops", "brand": "Dell", "quantity": 10}}, {{"category": "Monitors", "quantity": 20}}]}}

Example 4 - Complex change:
Original request: {{"items": [{{"category": "Monitors", "quantity": 20, "unit_price": 30000}}]}}
User says: "change to 15 monitors at 35000 each"
Output: {{"items": [{{"category": "Monitors", "quantity": 15, "unit_price": 35000}}]}}

NOW MERGE THIS REQUEST:

Original request:
{json.dumps(original_request, indent=2)}

User's modification message:
"{modification_message}"

CRITICAL RULES:
1. PRESERVE ALL EXISTING ITEMS unless explicitly modified or removed
2. For quantity changes, update the specific item quantities
3. For price changes, add or update unit_price field
4. For additions, add new items to the items array
5. For removals, remove the specified items
6. Return ONLY valid JSON - no comments, no arrows, no explanations

Output ONLY the updated JSON object:"""

            if llm_service is None:
                logger.warning("LLM service not available, returning original request")
                return original_request
            
            try:
                response = llm_service.invoke_with_recovery(
                    model_name=self.model_name,
                    params=self.params,
                    prompt=prompt,
                    max_retries=2
                )
                
                # Clean the response before logging (remove Unicode characters)
                clean_response = response.encode('ascii', 'ignore').decode('ascii')
                logger.info(f"Raw merge response: {clean_response[:200]}...")
                
                # Clean the response before parsing
                cleaned_response = self._clean_llm_response(response)
                
                # Try to parse the cleaned response
                merged = self._robust_json_parse(cleaned_response)
                
                if merged and merged.get('items'):
                    # Verify that we have all items
                    original_items = {f"{item.get('brand', '')}_{item.get('category', '')}" 
                                    for item in original_request.get('items', [])}
                    merged_items = {f"{item.get('brand', '')}_{item.get('category', '')}" 
                                for item in merged.get('items', [])}
                    
                    # Check if we lost any items unintentionally
                    lost_items = original_items - merged_items
                    if lost_items and not self._is_removal_message(modification_message):
                        logger.warning(f"Lost items without remove command: {lost_items}")
                        # Fall back to manual merge
                        return self._manual_merge(original_request, modification_message)
                    
                    # Preserve all metadata from original
                    for key in original_request:
                        if key not in merged and key != 'items':
                            merged[key] = original_request[key]
                    
                    logger.info(f"Successfully merged requests with {len(merged['items'])} items")
                    return merged
                else:
                    logger.warning("Merge returned invalid structure, using manual merge")
                    return self._manual_merge(original_request, modification_message)
                
            except Exception as e:
                logger.error(f"LLM merge failed: {str(e)}")
                return self._manual_merge(original_request, modification_message)
            
        except Exception as e:
            logger.error(f"Request merging failed: {str(e)}")
            return self._manual_merge(original_request, modification_message)
    
    def _is_removal_message(self, message: str) -> bool:
        """Check if message indicates removal intent"""
        message_lower = message.lower()
        removal_words = ['remove', 'delete', 'take out', 'drop']
        return any(word in message_lower for word in removal_words)
    
    def _clean_llm_response(self, response: str) -> str:
        """Clean LLM response by removing comments, arrows, and non-JSON content"""
        # Remove markdown code blocks
        response = response.replace('```json', '').replace('```', '')
        
        # Remove lines that look like comments (contain ←, //, etc.)
        lines = response.split('\n')
        cleaned_lines = []
        for line in lines:
            # Skip lines with arrows or comments
            if '←' in line or '//' in line or '#' in line:
                continue
            # Remove trailing comments
            if '//' in line:
                line = line[:line.index('//')]
            if '#' in line:
                line = line[:line.index('#')]
            cleaned_lines.append(line)
        
        cleaned_response = '\n'.join(cleaned_lines)
        
        # Remove any remaining Unicode characters
        cleaned_response = cleaned_response.encode('ascii', 'ignore').decode('ascii')
        
        return cleaned_response

    def _manual_merge(self, original: Dict[str, Any], message: str) -> Dict[str, Any]:
        """Enhanced manual merge that handles natural language better"""
        import copy
        import re
        
        result = copy.deepcopy(original)
        message_lower = message.lower()
        
        # Handle "make X to be Y" pattern
        make_pattern = r'make\s+the\s+(\d+)\s+(\w+)\s+to\s+be\s+(\d+)'
        make_match = re.search(make_pattern, message_lower)
        if make_match:
            old_qty = int(make_match.group(1))
            category = make_match.group(2).capitalize()
            new_qty = int(make_match.group(3))
            
            for item in result.get('items', []):
                if item.get('category', '').lower() == category.lower():
                    old_val = item['quantity']
                    item['quantity'] = new_qty
                    logger.info(f"Manual merge: Changed {category} from {old_val} to {new_qty}")
                    break
        
        # Handle price changes
        price_pattern = r'at\s+a\s+price\s+of\s+(\d+(?:,\d+)?)\s*(php|pesos|\$|usd)?'
        price_match = re.search(price_pattern, message_lower)
        if price_match:
            price = int(price_match.group(1).replace(',', ''))
            currency = price_match.group(2) or 'PHP'
            
            # Apply price to the last modified item or all items
            for item in result.get('items', []):
                item['unit_price'] = price
                item['currency'] = currency.upper()
                logger.info(f"Manual merge: Set price to {price} {currency} for {item.get('category')}")
        
        # Handle quantity changes
        change_match = re.search(r'change\s+(\w+)\s+to\s+(\d+)', message_lower)
        if change_match:
            brand_to_change = change_match.group(1).capitalize()
            new_quantity = int(change_match.group(2))
            
            for item in result.get('items', []):
                if item.get('brand', '').lower() == brand_to_change.lower():
                    old_qty = item['quantity']
                    item['quantity'] = new_quantity
                    logger.info(f"Manual merge: Changed {brand_to_change} from {old_qty} to {new_quantity}")
                    break
        
        # Handle adding items
        add_match = re.search(r'add\s+(\d+)\s+(\w+)(?:\s+(\w+))?', message_lower)
        if add_match:
            quantity = int(add_match.group(1))
            category = add_match.group(2).capitalize()
            brand = add_match.group(3).capitalize() if add_match.group(3) else None
            
            new_item = {
                "category": category,
                "quantity": quantity
            }
            if brand:
                new_item["brand"] = brand
            
            # Check if item already exists
            exists = False
            for item in result.get('items', []):
                if item.get('category', '').lower() == category.lower():
                    if brand and item.get('brand', '').lower() == brand.lower():
                        item['quantity'] += quantity
                        exists = True
                        logger.info(f"Manual merge: Added {quantity} to existing {brand} {category}")
                        break
                    elif not brand and not item.get('brand'):
                        item['quantity'] += quantity
                        exists = True
                        logger.info(f"Manual merge: Added {quantity} to existing {category}")
                        break
            
            if not exists:
                result['items'].append(new_item)
                logger.info(f"Manual merge: Added new item: {quantity} {category}")
        
        # Handle remove items
        remove_match = re.search(r'remove\s+(\w+)', message_lower)
        if remove_match:
            brand_to_remove = remove_match.group(1).capitalize()
            original_count = len(result.get('items', []))
            result['items'] = [item for item in result.get('items', []) 
                            if item.get('brand', '').lower() != brand_to_remove.lower()]
            removed_count = original_count - len(result['items'])
            if removed_count > 0:
                logger.info(f"Manual merge: Removed {removed_count} item(s) with brand {brand_to_remove}")
        
        return result

    def _robust_json_parse(self, text: str) -> Dict[str, Any]:
        """Robust JSON parsing for merge responses"""
        # Remove markdown code blocks
        text = text.replace('```json', '').replace('```', '').strip()
        
        # Try to find the first complete JSON object
        brace_count = 0
        start_idx = -1
        end_idx = -1
        
        for i, char in enumerate(text):
            if char == '{':
                if brace_count == 0:
                    start_idx = i
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0 and start_idx != -1:
                    end_idx = i + 1
                    break
        
        if start_idx != -1 and end_idx != -1:
            json_str = text[start_idx:end_idx]
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass
        
        # Fallback to regex
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        
        return {}

    def format_confirmation_message(self, request_data: Dict[str, Any]) -> str:
        """Format confirmation message from request data"""
        if not request_data or not request_data.get('items'):
            return "No items to confirm."
        
        items = request_data.get('items', [])
        
        items_text = []
        for item in items:
            brand = item.get('brand', 'Unknown')
            category = item.get('category', 'Item')
            quantity = item.get('quantity', 0)
            
            # Add price if available
            price_info = ""
            if item.get('unit_price'):
                currency = item.get('currency', 'PHP')
                price = item['unit_price']
                price_info = f" at {currency} {price:,.2f} each"
            
            items_text.append(f"  - {quantity} {brand} {category}{price_info}")
        
        items_formatted = "\n".join(items_text)
        
        budget_text = ""
        if request_data.get('budget_total'):
            currency = request_data.get('currency', 'USD')
            budget_total = request_data['budget_total']
            budget_text = f"\nTotal Budget: {currency} {budget_total:,.2f}"
        
        delivery_text = ""
        if request_data.get('delivery_location'):
            delivery_text = f"\nDelivery Location: {request_data['delivery_location']}"
        if request_data.get('delivery_date'):
            delivery_text += f"\nRequired Delivery Date: {request_data['delivery_date']}"
        
        return CONFIRMATION_TEMPLATE.format(
            items_list=items_formatted,
            budget_text=budget_text,
            delivery_text=delivery_text
        )
        
    def update_context(self, session_id: str, **kwargs):
        """Update conversation context"""
        context = self.get_or_create_context(session_id)
        context.update(**kwargs)
        return context