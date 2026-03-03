# src/features/procurement_assistant/routes/confirmation_routes.py
from flask import Blueprint, request, jsonify, session as flask_session
from ..services.confirmation_service import ConfirmationService
from ..services.supplier_matching_service import SupplierMatchingService
from ....common import get_logger
from ..database.rfq_db_operations import RFQDatabaseOperations
import os

logger = get_logger(__name__)

# Create blueprint without url_prefix
confirmation_bp = Blueprint('confirmation', __name__)

# Initialize service
confirmation_service = ConfirmationService()

@confirmation_bp.route('/chat', methods=['POST'])
def chat():
    """Main chat endpoint"""
    try:
        data = request.get_json()
        
        if not data or 'message' not in data:
            return jsonify({
                "status": "error",
                "message": "No message provided"
            }), 400
        
        user_message = data['message']
        
        # Get session_id from request body (not from Flask session)
        session_id = data.get('session_id')
        
        if not session_id:
            # Create new session if this is first interaction
            session_id = f"proc_{os.urandom(8).hex()}"
        
        # Process the message
        response = confirmation_service.process_message(
            session_id=session_id,
            message=user_message
        )
        
        # Return session_id so client can store it
        response['session_id'] = session_id
        
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"Error in chat endpoint: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "An error occurred while processing your request"
        }), 500

@confirmation_bp.route('/context', methods=['GET'])
def get_context():
    """Get current conversation context"""
    try:
        # Get session_id from query parameter
        session_id = request.args.get('session_id')
        
        if not session_id:
            return jsonify({
                "status": "error",
                "message": "No session_id provided"
            }), 400
        
        context = confirmation_service.conversation_manager.get_or_create_context(session_id)
        
        return jsonify({
            "status": "success",
            "context": context.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting context: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@confirmation_bp.route('/reset', methods=['POST'])
def reset_conversation():
    """Reset the current conversation"""
    try:
        data = request.get_json() or {}
        session_id = data.get('session_id')
        
        if session_id and session_id in confirmation_service.conversation_manager.sessions:
            del confirmation_service.conversation_manager.sessions[session_id]
        
        return jsonify({
            "status": "success",
            "message": "Conversation reset. You can start a new request."
        }), 200
        
    except Exception as e:
        logger.error(f"Error resetting conversation: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@confirmation_bp.route('/rfq/<rfq_id>', methods=['GET'])
def get_rfq(rfq_id):
    """Get RFQ details by ID"""
    try:
        with RFQDatabaseOperations() as db:
            result = db.get_rfq_by_id(rfq_id)
        
        if result['status'] == 'success':
            return jsonify(result), 200
        else:
            return jsonify(result), 404
            
    except Exception as e:
        logger.error(f"Error getting RFQ: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@confirmation_bp.route('/session/<session_id>/rfqs', methods=['GET'])
def get_session_rfqs(session_id):
    """Get all RFQs for a session"""
    try:
        with RFQDatabaseOperations() as db:
            result = db.get_rfqs_by_session(session_id)
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error getting session RFQs: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

# Add these new endpoints for supplier matching
@confirmation_bp.route('/rfq/<rfq_id>/suppliers', methods=['GET'])
def get_rfq_suppliers(rfq_id):
    """Get supplier matching results for an RFQ"""
    try:
        with SupplierMatchingService() as matcher:
            matcher.cursor.execute("""
                SELECT rs.mapping_id, rs.supplier_id, s.company_name, 
                       rs.match_score, rs.status, rs.email_sent,
                       rs.access_code, rs.passcode, rs.created_at,
                       s.email
                FROM [RFQ].[rfq_suppliers] rs
                JOIN [RFQ].[suppliers] s ON rs.supplier_id = s.supplier_id
                WHERE rs.rfq_id = ?
                ORDER BY rs.match_score DESC
            """, (rfq_id,))
            
            rows = matcher.cursor.fetchall()
            
            suppliers = []
            for row in rows:
                suppliers.append({
                    "mapping_id": row[0],
                    "supplier_id": row[1],
                    "company_name": row[2],
                    "match_score": float(row[3]) if row[3] else 0,
                    "status": row[4],
                    "email_sent": bool(row[5]),
                    "email": row[9],
                    "created_at": row[8].isoformat() if row[8] else None
                })
            
            return jsonify({
                "status": "success",
                "rfq_id": rfq_id,
                "total_suppliers": len(suppliers),
                "suppliers": suppliers
            }), 200
            
    except Exception as e:
        logger.error(f"Error getting RFQ suppliers: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@confirmation_bp.route('/rfq/<rfq_id>/match-suppliers', methods=['POST'])
def match_suppliers_for_rfq(rfq_id):
    """Manually trigger supplier matching for an RFQ"""
    try:
        data = request.get_json() or {}
        test_mode = data.get('test_mode', True)
        base_url = data.get('base_url', os.getenv("APP_BASE_URL", "http://localhost:5000"))
        
        with SupplierMatchingService() as matcher:
            matching_result = matcher.find_matching_suppliers(rfq_id)
            
            if matching_result['status'] != 'success':
                return jsonify(matching_result), 400
            
            email_result = matcher.send_rfq_emails(
                rfq_id=rfq_id,
                test_mode=test_mode,
                base_url=base_url
            )
            
            return jsonify({
                "status": "success",
                "matching": matching_result,
                "email_sending": email_result
            }), 200
            
    except Exception as e:
        logger.error(f"Error matching suppliers for RFQ: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@confirmation_bp.route('/supplier/<int:mapping_id>/resend-email', methods=['POST'])
def resend_supplier_email(mapping_id):
    """Resend RFQ email to a specific supplier"""
    try:
        data = request.get_json() or {}
        base_url = data.get('base_url', os.getenv("APP_BASE_URL", "http://localhost:5000"))
        
        with SupplierMatchingService() as matcher:
            result = matcher.resend_rfq_email(mapping_id, base_url)
            
            return jsonify(result), 200 if result['status'] == 'success' else 400
            
    except Exception as e:
        logger.error(f"Error resending email: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500