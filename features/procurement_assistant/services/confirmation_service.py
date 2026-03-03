# src/features/procurement_assistant/services/confirmation_service.py
from typing import Dict, Any
from ....common import get_logger
from ....core.conversation_manager import ConversationManager
from ....core.ai_extractor import AIExtractor
from ..models.conversation_model import ConversationState, UserIntent, ConversationContext
from ..utils.json_formatter import JSONFormatter
from ..database.rfq_db_operations import RFQDatabaseOperations
import copy
from .supplier_matching_service import SupplierMatchingService

logger = get_logger(__name__)

class ConfirmationService:
    """Handles the confirmation flow logic with clean JSON formatting"""
    
    def __init__(self):
        self.conversation_manager = ConversationManager()
        self.extractor = AIExtractor()
        self.formatter = JSONFormatter()
        self.db = RFQDatabaseOperations()
    
    def process_message(self, session_id: str, message: str) -> Dict[str, Any]:
        """Process user message in the confirmation flow"""
        
        context = self.conversation_manager.get_or_create_context(session_id)
        context.update(last_message=message)
        
        intent = self.conversation_manager.detect_intent(message, context)
        context.update(last_intent=intent)
        
        logger.info(f"Session {session_id}: State={context.state.value}, Intent={intent.value}")
        
        if context.state == ConversationState.INITIAL:
            return self._handle_initial_message(context, message)
        elif context.state == ConversationState.AWAITING_CONFIRMATION:
            return self._handle_confirmation_response(context, intent, message)
        elif context.state == ConversationState.MODIFYING:
            return self._handle_modification(context, intent, message)
        else:
            return {
                "status": "error",
                "message": "Unexpected conversation state"
            }
    
    def _handle_initial_message(self, context: ConversationContext, 
                               message: str) -> Dict[str, Any]:
        """Handle initial message - extract using AI"""
        
        # Use AI to extract structured JSON
        json_data = self.extractor.extract_procurement_request(message)
        
        if not json_data or not json_data.get('items'):
            return {
                "status": "error",
                "message": "I couldn't understand your request. Please specify items with quantities and brands (e.g., '10 dell laptops')."
            }
        
        # Update context with the JSON data
        context.update(
            current_request=json_data,
            state=ConversationState.AWAITING_CONFIRMATION
        )
        
        # Format a nice confirmation message using the JSON
        confirmation_message = self.formatter.format_confirmation(json_data)
        
        # Also create a summary for quick display
        display_summary = self.formatter.extract_for_display(json_data)
        
        return {
            "status": "success",
            "message": confirmation_message,
            "json_data": json_data,  # Return the clean JSON
            "display_summary": display_summary,
            "state": context.state.value
        }
    
    def _handle_confirmation_response(self, context: ConversationContext,
                                intent: UserIntent, message: str) -> Dict[str, Any]:
        """Handle response during confirmation state - now processes modifications directly"""
        
        # Check if this is a confirmation
        if intent == UserIntent.CONFIRM:
            return self._process_confirmation(context)
        
        # Check if this is a cancellation
        elif intent == UserIntent.CANCEL:
            context.update(state=ConversationState.INITIAL, current_request=None)
            return {
                "status": "success",
                "message": "❌ Request cancelled. How can I help you with a new request?",
                "json_data": None,
                "display_summary": None,
                "state": context.state.value
            }
        
        # Any other intent (ADD, REMOVE, MODIFY, etc.) - process as modification
        elif intent in [UserIntent.ADD, UserIntent.REMOVE, UserIntent.MODIFY]:
            # Process the modification directly
            return self._handle_modification(context, intent, message)
        
        # If intent is unknown but message seems substantive, try as modification
        else:
            # Check if message contains modification indicators
            if self._likely_modification_message(message):
                return self._handle_modification(context, UserIntent.MODIFY, message)
            
            # Otherwise, show options
            return {
                "status": "success",
                "message": "I didn't understand. Please confirm, cancel, or tell me what you'd like to change.\n\n" +
                        "Examples:\n" +
                        "- 'confirm' to proceed\n" +
                        "- 'add 10 monitors' to add items\n" +
                        "- 'change dell to 15' to modify quantities\n" +
                        "- 'remove acer' to remove items\n" +
                        "- 'cancel' to cancel",
                "json_data": context.current_request,
                "display_summary": self.formatter.extract_for_display(context.current_request) if context.current_request else None,
                "state": context.state.value
            }
            
    def _likely_modification_message(self, message: str) -> bool:
        """Check if a message is likely a modification request"""
        message_lower = message.lower()
        
        # Common modification patterns
        patterns = [
            # Quantity patterns
            r'\d+\s+(laptops|monitors|chairs|items|units)',
            r'(add|change|remove|delete)\s+',
            r'(more|less|instead|update|modify)',
            r'price|cost|budget|each|per',
            r'to\s+\d+',  # "to 15"
            r'from\s+\d+\s+to\s+\d+',  # "from 10 to 15"
            r'make\s+(it|them|the)'
        ]
        
        import re
        for pattern in patterns:
            if re.search(pattern, message_lower):
                return True
        
        return False

    def _process_confirmation(self, context: ConversationContext) -> Dict[str, Any]:
        """Process confirmation and save to database"""
        # Get the JSON data
        json_data = context.current_request or {}
        
        required_date = json_data.get('required_date')
        delivery_deadline = json_data.get('delivery_deadline')
        
        with RFQDatabaseOperations() as db:
            save_result = db.create_rfq(
                session_id=context.session_id,
                rfq_data=json_data,
                user_id=None,
                department=None,
                required_date=required_date,
                delivery_deadline=delivery_deadline
            )
        
        if save_result['status'] == 'success':
            rfq_id = save_result['rfq_id']
            message_text = f"✅ Great! Your request has been confirmed. RFQ #{save_result['rfq_id']} has been generated."
            
            # Trigger supplier matching
            matching_result = self._trigger_supplier_matching(rfq_id)
            
            if matching_result["status"] == "success":
                if matching_result.get("suppliers_found", 0) > 0:
                    if matching_result.get("test_mode"):
                        message_text += f" 📧 Found {matching_result['suppliers_found']} matching suppliers (test mode)."
                    else:
                        message_text += f" 📧 {matching_result['emails_sent']} supplier(s) have been notified."
                else:
                    message_text += " ⚠️ No matching suppliers found for this RFQ."
            
            json_data['rfq_id'] = rfq_id
        else:
            message_text = "✅ Great! Your request has been confirmed. (Note: There was an issue saving to database)"
            logger.error(f"Database save failed: {save_result['message']}")
        
        context.update(state=ConversationState.CONFIRMED)
        
        return {
            "status": "success",
            "message": message_text,
            "json_data": json_data,
            "rfq_id": save_result.get('rfq_id'),
            "display_summary": self.formatter.extract_for_display(json_data),
            "next_step": "generate_rfq",
            "state": context.state.value
        }
    
            
    def _trigger_supplier_matching(self, rfq_id: str) -> Dict[str, Any]:
        """Trigger supplier matching for an RFQ"""
        try:
            with SupplierMatchingService() as matcher:
                if not matcher.auto_match_suppliers:
                    return {"status": "skipped", "reason": "auto_match_disabled"}
                
                # Find matching suppliers
                match_result = matcher.find_matching_suppliers(rfq_id)
                
                if match_result["status"] != "success":
                    return {"status": "error", "message": match_result.get("message")}
                
                supplier_count = match_result["total_suppliers_found"]
                
                if supplier_count == 0:
                    return {"status": "success", "suppliers_found": 0, "emails_sent": 0}
                
                # Send emails if not in test mode
                if matcher.email_test_mode:
                    logger.info(f"Test mode: Found {supplier_count} suppliers for RFQ {rfq_id}")
                    return {"status": "success", "suppliers_found": supplier_count, "emails_sent": 0, "test_mode": True}
                else:
                    email_result = matcher.send_rfq_emails(rfq_id)
                    emails_sent = email_result.get("emails_sent", 0) if email_result["status"] == "success" else 0
                    return {
                        "status": "success", 
                        "suppliers_found": supplier_count, 
                        "emails_sent": emails_sent
                    }
                    
        except Exception as e:
            logger.error(f"Error in supplier matching: {str(e)}")
            return {"status": "error", "message": str(e)}

    def _handle_modification(self, context: ConversationContext,
                            intent: UserIntent, message: str) -> Dict[str, Any]:
        """Handle modification messages using AI merge"""
        
        logger.info(f"Processing modification: '{message}' with intent {intent.value}")
        
        # Store original items for comparison
        original_request = copy.deepcopy(context.current_request) if context.current_request else {"items": []}
        original_items = copy.deepcopy(original_request.get('items', []))
        
        # Save current request to history
        if context.current_request:
            context.add_to_history(context.current_request)
        
        # Use AI to merge the requests
        if context.current_request:
            merged_json = self.conversation_manager.merge_requests(
                original_request=context.current_request,
                modification_message=message
            )
        else:
            merged_json = self.extractor.extract_procurement_request(message)
        
        # If merge failed, ensure we have a valid structure
        if not merged_json:
            merged_json = {"items": []}
        
        # Ensure items list exists
        if 'items' not in merged_json:
            merged_json['items'] = []
        
        # If we lost items but didn't ask to remove them, restore from original
        if original_items and len(merged_json['items']) < len(original_items):
            if 'remove' not in message.lower() and 'delete' not in message.lower():
                logger.warning("Items lost without remove command, restoring from original")
                merged_json['items'] = original_items
        
        # Preserve metadata from original request
        if original_request:
            for key in ['budget_total', 'currency', 'priority', 'delivery_location', 'delivery_date']:
                if key in original_request and key not in merged_json:
                    merged_json[key] = original_request[key]
        
        # Calculate what changed - FIXED VERSION that handles missing brand
        changes = []
        if original_items and merged_json.get('items'):
            # Check for added or modified items
            for new_item in merged_json['items']:
                found = False
                for old_item in original_items:
                    # Compare items safely - brand might be missing
                    new_brand = new_item.get('brand', '')
                    old_brand = old_item.get('brand', '')
                    new_category = new_item.get('category', '')
                    old_category = old_item.get('category', '')
                    
                    # Match by category primarily, and brand if available
                    if new_category.lower() == old_category.lower():
                        # Same category - check if brand matches (if both have brands)
                        if new_brand and old_brand:
                            if new_brand.lower() == old_brand.lower():
                                # Check if quantity changed
                                if new_item.get('quantity') != old_item.get('quantity'):
                                    changes.append(f"📊 {new_category}: {old_item.get('quantity')} → {new_item.get('quantity')}")
                                found = True
                                break
                        else:
                            # No brands to compare, just category match
                            if new_item.get('quantity') != old_item.get('quantity'):
                                changes.append(f"📊 {new_category}: {old_item.get('quantity')} → {new_item.get('quantity')}")
                            found = True
                            break
                
                if not found:
                    # This is a new item
                    quantity = new_item.get('quantity', 0)
                    unit = new_item.get('unit', '')
                    quantity_str = f"{quantity} {unit}".strip() if unit else str(quantity)
                    brand = new_item.get('brand', '')
                    category = new_item.get('category', '')
                    
                    if brand:
                        changes.append(f"➕ Added {quantity_str} {brand} {category}")
                    else:
                        changes.append(f"➕ Added {quantity_str} of {category}")
            
            # Check for removed items
            for old_item in original_items:
                found = False
                for new_item in merged_json['items']:
                    old_category = old_item.get('category', '').lower()
                    new_category = new_item.get('category', '').lower()
                    old_brand = old_item.get('brand', '').lower()
                    new_brand = new_item.get('brand', '').lower()
                    
                    if old_category == new_category:
                        if old_brand and new_brand:
                            if old_brand == new_brand:
                                found = True
                                break
                        else:
                            # No brands to compare
                            found = True
                            break
                
                if not found:
                    brand = old_item.get('brand', '')
                    category = old_item.get('category', '')
                    if brand:
                        changes.append(f"➖ Removed {brand} {category}")
                    else:
                        changes.append(f"➖ Removed {category}")
        
        # Update context with new request
        context.update(
            current_request=merged_json,
            state=ConversationState.AWAITING_CONFIRMATION
        )
        
        # Format the new confirmation message
        if merged_json and merged_json.get('items'):
            confirmation = self.formatter.format_confirmation(merged_json)
            
            # Add change summary
            if changes:
                change_summary = "\n".join(changes[:3])  # Show first 3 changes
                if len(changes) > 3:
                    change_summary += f"\n... and {len(changes) - 3} more changes"
                message_text = f"✅ Request updated with {len(changes)} change(s):\n{change_summary}\n\n{confirmation}"
            else:
                message_text = f"✅ Request updated.\n\n{confirmation}"
        else:
            message_text = "I couldn't process your modification. Please try again with a clearer instruction."
        
        # Create display summary
        display_summary = self.formatter.extract_for_display(merged_json) if merged_json else None
        
        return {
            "status": "success",
            "message": message_text,
            "json_data": merged_json,  # Always return the updated JSON
            "changes": changes,
            "display_summary": display_summary,
            "state": context.state.value
        }