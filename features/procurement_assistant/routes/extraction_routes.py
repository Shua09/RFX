# src/features/procurement_assistant/routes/extraction_routes.py
from flask import Blueprint, request, jsonify, session
from ..services.extraction_service import ExtractionService
from ....common import get_logger
import os

logger = get_logger(__name__)

# Create blueprint
extraction_bp = Blueprint('extraction', __name__,)

# Initialize service
extraction_service = ExtractionService()

@extraction_bp.route('/extract', methods=['POST'])
def extract_request():
    """
    API endpoint to process natural language procurement requests
    
    Expected JSON payload:
    {
        "message": "Hi, I want to buy 10 dell laptops, 10 acer laptops, 10 MSI laptops. Budget: 250k"
    }
    
    Returns:
    {
        "status": "success",
        "message": "Your request has been received...",
        "confirmation": "Your request has been received...",
        "request_data": {...},
        "next_steps": [...]
    }
    """
    try:
        # Get JSON data from request
        data = request.get_json()
        
        if not data or 'message' not in data:
            return jsonify({
                "status": "error",
                "message": "No message provided"
            }), 400
        
        user_message = data['message']
        
        # Get or create session ID
        if 'session_id' not in session:
            session['session_id'] = f"proc_{os.urandom(8).hex()}"
        session_id = session['session_id']
        
        # Process the request
        response_data, procurement_request = extraction_service.process_request(
            user_input=user_message,
            session_id=session_id
        )
        
        # Store in session for later steps
        session['current_request'] = procurement_request.to_dict()
        
        return jsonify(response_data), 200
        
    except Exception as e:
        logger.error(f"Error processing extraction request: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "An error occurred while processing your request",
            "error": str(e)
        }), 500

@extraction_bp.route('/confirm', methods=['POST'])
def confirm_request():
    """
    API endpoint to confirm the extracted request
    
    Expected JSON payload:
    {
        "action": "confirm" | "add" | "modify",
        "additional_items": "15 Samsung Laptops" (if action is "add")
    }
    """
    try:
        data = request.get_json()
        action = data.get('action', '')
        
        if action == 'confirm':
            # TODO: Move to finalization
            return jsonify({
                "status": "success",
                "message": "Request confirmed. Generating RFQ...",
                "next_step": "/api/procurement/finalize"
            }), 200
            
        elif action == 'add':
            additional_items = data.get('additional_items', '')
            # Process additional items
            # This will call the extraction service again with the additional items
            
            return jsonify({
                "status": "success",
                "message": "Processing additional items...",
                "additional_items": additional_items
            }), 200
            
        else:
            return jsonify({
                "status": "error",
                "message": "Invalid action"
            }), 400
            
    except Exception as e:
        logger.error(f"Error in confirmation: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "An error occurred"
        }), 500