# src/features/procurement_assistant/services/extraction_service.py
import json
from typing import Dict, Any, Tuple
from datetime import datetime

from ....core.ai_extractor import AIExtractor
from ..models.request_model import ProcurementRequest, RequestItem, RequestStatus
from ....common import get_logger, db

logger = get_logger(__name__)

class ExtractionService:
    """Service layer for handling procurement request extraction"""
    
    def __init__(self):
        self.ai_extractor = AIExtractor()
    
    def process_request(self, user_input: str, session_id: str = None) -> Tuple[Dict[str, Any], ProcurementRequest]:
        """
        Process user input and return structured data with confirmation message
        
        Args:
            user_input: Natural language request
            session_id: Optional session identifier
            
        Returns:
            Tuple of (response_data, request_object)
        """
        # Step 1: Extract structured data using AI
        extracted_data = self.ai_extractor.extract_procurement_request(user_input)
        
        # Step 2: Convert to ProcurementRequest model
        procurement_request = self._create_request_model(extracted_data, session_id)
        
        # Step 3: Generate confirmation message
        confirmation_message = self._generate_confirmation_message(procurement_request)
        
        # Step 4: Prepare response
        response_data = {
            "status": "success",
            "message": "Your request has been received. Please confirm the following items:",
            "confirmation": confirmation_message,
            "request_data": procurement_request.to_dict(),
            "next_steps": [
                "Type 'confirm' to proceed",
                "Type 'add [items]' to add more items",
                "Type 'modify' to change specifications"
            ]
        }
        
        # TODO: Save to database
        self._save_to_database(procurement_request)
        
        return response_data, procurement_request
    
    def _create_request_model(self, extracted_data: Dict[str, Any], session_id: str) -> ProcurementRequest:
        """Convert extracted data to ProcurementRequest model"""
        
        # Create items
        items = []
        for item_data in extracted_data.get('items', []):
            item = RequestItem(
                category=item_data.get('category', ''),
                brand=item_data.get('brand', ''),
                quantity=item_data.get('quantity', 0),
                model=item_data.get('model'),
                specifications=item_data.get('specifications')
            )
            items.append(item)
        
        # Create request
        request = ProcurementRequest(
            items=items,
            budget_total=extracted_data.get('budget_total'),
            budget_per_unit=extracted_data.get('budget_per_unit'),
            currency=extracted_data.get('currency', 'USD'),
            delivery_location=extracted_data.get('delivery_location'),
            delivery_date=extracted_data.get('delivery_date'),
            priority=extracted_data.get('priority', 'medium'),
            payment_terms=extracted_data.get('payment_terms'),
            special_instructions=extracted_data.get('special_instructions'),
            session_id=session_id
        )
        
        return request
    
    def _generate_confirmation_message(self, request: ProcurementRequest) -> str:
        """Generate a user-friendly confirmation message"""
        
        # Build items list
        items_text = []
        for item in request.items:
            items_text.append(f"  - {item.quantity} {item.brand} {item.category}")
        
        items_formatted = "\n".join(items_text)
        
        # Build budget text
        budget_text = ""
        if request.budget_total:
            budget_text = f"\nTotal Budget: {request.currency} {request.budget_total:,.2f}"
        elif request.budget_per_unit:
            budget_text = f"\nBudget per unit: {request.currency} {request.budget_per_unit:,.2f}"
        
        # Build delivery text
        delivery_text = ""
        if request.delivery_location:
            delivery_text = f"\nDelivery Location: {request.delivery_location}"
        if request.delivery_date:
            delivery_text += f"\nRequired Delivery Date: {request.delivery_date}"
        
        # Complete message
        message = f"""Your request has been received, please confirm the following items if correct:

{items_formatted}{budget_text}{delivery_text}

Can you confirm if this is final or you would like to add more?"""
        
        return message
    
    def _save_to_database(self, request: ProcurementRequest):
        """Save the request to database"""
        # TODO: Implement database saving
        logger.info(f"Request saved to database: {request.session_id}")