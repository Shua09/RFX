# src/features/procurement_assistant/utils/json_formatter.py
import json
from typing import Dict, Any
from ....common import get_logger

logger = get_logger(__name__)

class JSONFormatter:
    """Formats AI-generated JSON into user-friendly messages"""
    
    @staticmethod
    def format_confirmation(json_data: Dict[str, Any]) -> str:
        """
        Convert AI-generated JSON into a nice confirmation message
        This uses the same CONFIRMATION_TEMPLATE structure but fills it with parsed data
        """
        items = json_data.get('items', [])
        
        # Build items list with nice formatting
        items_text = []
        for i, item in enumerate(items, 1):
            brand = item.get('brand', '')
            category = item.get('category', '')
            quantity = item.get('quantity', 0)
            unit = item.get('unit', '')
            
            # Format quantity with unit if present
            quantity_str = f"{quantity} {unit}".strip() if unit else str(quantity)
            
            # Add specifications if present
            specs = item.get('specifications', {})
            specs_text = ""
            if specs:
                if isinstance(specs, dict):
                    specs_list = [f"{k}: {v}" for k, v in specs.items()]
                    specs_text = f" ({', '.join(specs_list)})"
                elif isinstance(specs, str):
                    specs_text = f" ({specs})"
            
            # Build item line - brand is optional
            if brand:
                items_text.append(f"  {i}. {quantity_str} x {brand} {category}{specs_text}")
            else:
                items_text.append(f"  {i}. {quantity_str} of {category}{specs_text}")
        
        items_formatted = "\n".join(items_text) if items_text else "  No items specified"
        
        # Format budget
        budget_text = ""
        if json_data.get('budget_total'):
            currency = json_data.get('currency', 'USD')
            budget = json_data['budget_total']
            budget_text = f"\n💰 Total Budget: {currency} {budget:,.2f}"
        elif json_data.get('budget_per_unit'):
            currency = json_data.get('currency', 'USD')
            per_unit = json_data['budget_per_unit']
            budget_text = f"\n💰 Budget per unit: {currency} {per_unit:,.2f}"
        
        # Format delivery
        delivery_text = ""
        if json_data.get('delivery_location'):
            delivery_text = f"\n📍 Delivery to: {json_data['delivery_location']}"
        if json_data.get('delivery_date'):
            delivery_text += f"\n📅 Deliver by: {json_data['delivery_date']}"
        
        # Format payment terms
        payment_text = ""
        if json_data.get('payment_terms'):
            payment_text = f"\n💳 Payment terms: {json_data['payment_terms']}"
        
        # Format priority
        priority_text = ""
        if json_data.get('priority') and json_data['priority'] != 'medium':
            priority_emojis = {'high': '🔴', 'urgent': '🔥', 'low': '🟢'}
            emoji = priority_emojis.get(json_data['priority'], '⚪')
            priority_text = f"\n{emoji} Priority: {json_data['priority'].upper()}"
        
        # Build the complete message
        return f"""Your request has been received. Please confirm the following items:

{items_formatted}{budget_text}{delivery_text}{payment_text}{priority_text}

Would you like to:
1. ✅ Confirm and proceed (type "confirm")
2. ➕ Add more items (type "add [items]")
3. ✏️ Modify existing items (type "modify [changes]")
4. ❌ Cancel request (type "cancel")"""
    
    @staticmethod
    def format_summary(json_data: Dict[str, Any]) -> str:
        """Format a quick summary of the request"""
        items = json_data.get('items', [])
        total_items = sum(item.get('quantity', 0) for item in items)
        unique_items = len(items)
        
        summary = f"📦 {total_items} total items across {unique_items} product types"
        
        if json_data.get('budget_total'):
            summary += f" | 💰 Budget: {json_data.get('currency', 'USD')} {json_data['budget_total']:,.2f}"
        
        return summary
    
    @staticmethod
    def validate_json_structure(json_data: Dict[str, Any]) -> bool:
        """
        Validate that the JSON has the expected structure
        Now more flexible - brand is optional
        """
        # Check if json_data is None or not a dict
        if not json_data or not isinstance(json_data, dict):
            logger.warning("JSON data is None or not a dictionary")
            return False
        
        # Check for items field (required)
        if 'items' not in json_data:
            logger.warning("Missing required field: items")
            return False
        
        # Check items is a list
        if not isinstance(json_data['items'], list):
            logger.warning("Items should be a list")
            return False
        
        # If no items, that's valid (empty request)
        if len(json_data['items']) == 0:
            logger.info("Empty items list - valid but no products")
            return True
        
        # Validate each item
        for idx, item in enumerate(json_data['items']):
            # Check required fields for each item
            if 'category' not in item:
                logger.warning(f"Item {idx+1} missing required field: category")
                return False
            
            if 'quantity' not in item:
                logger.warning(f"Item {idx+1} missing required field: quantity")
                return False
            
            # Brand is now OPTIONAL - no longer required
            # We just log a debug message if it's missing
            if 'brand' not in item:
                logger.debug(f"Item {idx+1} has no brand specified - this is acceptable")
            
            # Unit is optional
            if 'unit' in item:
                logger.debug(f"Item {idx+1} has unit: {item['unit']}")
        
        # All checks passed
        logger.info(f"JSON validation successful - {len(json_data['items'])} items found")
        return True
    
    @staticmethod
    def extract_for_display(json_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract a simplified version for display in templates"""
        items = json_data.get('items', [])
        total_items = sum(item.get('quantity', 0) for item in items)
        
        return {
            'summary': JSONFormatter.format_summary(json_data),
            'total_items': total_items,
            'total_value': json_data.get('budget_total'),
            'currency': json_data.get('currency', 'USD'),
            'item_count': len(items),
            'has_delivery': bool(json_data.get('delivery_location') or json_data.get('delivery_date')),
            'has_payment': bool(json_data.get('payment_terms'))
        }