# src/features/customer/routes/customer_award_routes.py

from flask import Blueprint, request, jsonify
from ....common.logging_config import get_logger
from ..services.customer_award_service import CustomerAwardService

logger = get_logger(__name__)

customer_award_bp = Blueprint('customer_award', __name__)

@customer_award_bp.route('/api/customer/proposal/<int:proposal_id>', methods=['GET'])
def get_proposal(proposal_id):
    """Get proposal details for customer confirmation"""
    token = request.args.get('token')
    
    if not token:
        return jsonify({"status": "error", "message": "Access token required"}), 400
    
    with CustomerAwardService() as service:
        result = service.get_proposal_for_confirmation(proposal_id, token)
        return jsonify(result)

@customer_award_bp.route('/api/customer/proposal/<int:proposal_id>/confirm', methods=['POST'])
def confirm_proposal(proposal_id):
    """Customer confirms the proposal"""
    data = request.get_json()
    token = data.get('token')
    notes = data.get('notes')
    
    if not token:
        return jsonify({"status": "error", "message": "Access token required"}), 400
    
    with CustomerAwardService() as service:
        result = service.confirm_proposal(proposal_id, token, notes)
        return jsonify(result)

@customer_award_bp.route('/api/customer/proposal/<int:proposal_id>/status', methods=['GET'])
def get_proposal_status(proposal_id):
    """Get proposal status"""
    token = request.args.get('token')
    
    if not token:
        return jsonify({"status": "error", "message": "Access token required"}), 400
    
    with CustomerAwardService() as service:
        result = service.get_proposal_status(proposal_id, token)
        return jsonify(result)