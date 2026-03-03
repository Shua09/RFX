# src/features/supplier_portal/routes/supplier_routes.py

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, current_app
from ....common.logging_config import get_logger
from ....common.db_pyodbc import get_db_connection
from ...procurement_assistant.services.supplier_matching_service import SupplierMatchingService
from ..services.bid_submission_service import BidSubmissionService
import json
from datetime import datetime

logger = get_logger(__name__)

# Create blueprint
supplier_bp = Blueprint('supplier', __name__)

@supplier_bp.route('/<encrypted_code>')
def supplier_access(encrypted_code):
    """
    First entry point - validates encrypted code and shows passcode form
    """
    try:
        with SupplierMatchingService() as sms:
            # Validate the encrypted access code (first factor)
            validation_result = sms.validate_supplier_access(encrypted_code)
            
            if validation_result['status'] == 'error':
                return render_template('supplier_portal/error.html', 
                                     error=validation_result['message']), 400
            
            # Store basic info in session (but not fully authenticated yet)
            session['mapping_id'] = validation_result['mapping_id']
            session['supplier_id'] = validation_result['supplier_id']
            session['rfq_id'] = validation_result['rfq_id']
            session['encrypted_code'] = encrypted_code
            session['authenticated'] = False  # Not fully authenticated yet
            
            # Check if already submitted
            if validation_result.get('has_submitted', False):
                return render_template('supplier_portal/already_submitted.html',
                                     company_name=validation_result.get('company_name'),
                                     submitted_at=validation_result.get('submitted_at'))
            
            # Show passcode entry form
            return render_template('supplier_portal/enter_passcode.html',
                                 company_name=validation_result.get('company_name'),
                                 rfq_id=validation_result.get('rfq_id'),
                                 encrypted_code=encrypted_code)
    
    except Exception as e:
        logger.error(f"Error in supplier access: {str(e)}")
        return render_template('supplier_portal/error.html', 
                             error="An error occurred accessing the portal"), 500

@supplier_bp.route('/validate-passcode', methods=['POST'])
def validate_passcode():
    """
    Validate the passcode (second factor) and show the bid form
    """
    try:
        data = request.get_json()
        passcode = data.get('passcode')
        mapping_id = session.get('mapping_id')
        
        if not mapping_id or not passcode:
            return jsonify({'valid': False, 'error': 'Missing required data'}), 400
        
        with SupplierMatchingService() as sms:
            # Validate passcode
            is_valid = sms.validate_passcode_for_mapping(mapping_id, passcode)
            
            if is_valid:
                # Mark session as fully authenticated
                session['authenticated'] = True
                session['passcode_validated'] = True
                
                return jsonify({
                    'valid': True,
                    'redirect_url': url_for('supplier.show_bid_form')
                })
            else:
                return jsonify({'valid': False, 'error': 'Invalid passcode'}), 401
    
    except Exception as e:
        logger.error(f"Error validating passcode: {str(e)}")
        return jsonify({'valid': False, 'error': str(e)}), 500

@supplier_bp.route('/bid-form')
def show_bid_form():
    """
    Show the bid form after successful passcode validation
    """
    # Check if fully authenticated
    if not session.get('authenticated') or not session.get('passcode_validated'):
        return redirect(url_for('supplier.supplier_access', 
                              encrypted_code=session.get('encrypted_code', '')))
    
    try:
        mapping_id = session.get('mapping_id')
        
        with BidSubmissionService() as bss:
            # Get RFQ details for the form
            rfq_details = bss.get_rfq_details_for_supplier(mapping_id)
            
            if rfq_details['status'] == 'error':
                return render_template('supplier_portal/error.html', 
                                     error=rfq_details['message']), 400
            
            # Render the bid form with the RFQ data
            return render_template('supplier_portal/bid_form.html',  # Your existing bid_form.html
                                 rfq_data=rfq_details,
                                 encrypted_code=session.get('encrypted_code'),
                                 company_name=rfq_details.get('supplier_info', {}).get('company_name'))
    
    except Exception as e:
        logger.error(f"Error showing bid form: {str(e)}")
        return render_template('supplier_portal/error.html', 
                             error="An error occurred loading the form"), 500

@supplier_bp.route('/api/rfq-details', methods=['GET'])
def get_rfq_details():
    """
    API endpoint to get RFQ details for the supplier (used by bid form)
    """
    # Check authentication
    if not session.get('authenticated') or not session.get('passcode_validated'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        mapping_id = session.get('mapping_id')
        if not mapping_id:
            return jsonify({'error': 'No active session'}), 401
        
        with BidSubmissionService() as bss:
            details = bss.get_rfq_details_for_supplier(mapping_id)
            
            if details['status'] == 'error':
                return jsonify({'error': details['message']}), 400
                
            return jsonify(details)
    
    except Exception as e:
        logger.error(f"Error getting RFQ details: {str(e)}")
        return jsonify({'error': str(e)}), 500

@supplier_bp.route('/api/submit-bid', methods=['POST'])
def submit_bid():
    """
    API endpoint to submit the bid/quote
    """
    # Check authentication
    if not session.get('authenticated') or not session.get('passcode_validated'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        mapping_id = session.get('mapping_id')
        supplier_id = session.get('supplier_id')
        rfq_id = session.get('rfq_id')
        
        if not all([mapping_id, supplier_id, rfq_id]):
            return jsonify({'error': 'No active session'}), 401
        
        # Get raw data first for debugging
        raw_data = request.get_data(as_text=True)
        logger.info(f"Raw request data: {raw_data}")
        
        # Parse JSON
        data = request.get_json()
        logger.info(f"Parsed JSON data type: {type(data)}")
        logger.info(f"Parsed JSON data: {json.dumps(data, indent=2) if data else 'None'}")
        
        with BidSubmissionService() as bss:
            result = bss.submit_bid(
                mapping_id=mapping_id,
                supplier_id=supplier_id,
                rfq_id=rfq_id,
                bid_data=data  # Pass the parsed data directly
            )
            
            if result['status'] == 'success':
                # Clear authentication after successful submission
                session['authenticated'] = False
                session['submitted'] = True
                
                return jsonify({
                    'success': True,
                    'message': 'Bid submitted successfully',
                    'redirect_url': url_for('supplier.bid_confirmation')
                })
            else:
                return jsonify({'error': result['message']}), 400
    
    except Exception as e:
        logger.error(f"Error submitting bid: {str(e)}")
        return jsonify({'error': str(e)}), 500

@supplier_bp.route('/confirmation')
def bid_confirmation():
    """
    Show bid confirmation page after successful submission
    """
    if not session.get('submitted'):
        return redirect(url_for('supplier.supplier_access', 
                              encrypted_code=session.get('encrypted_code', '')))
    
    try:
        mapping_id = session.get('mapping_id')
        
        with BidSubmissionService() as bss:
            confirmation = bss.get_submission_confirmation(mapping_id)
            
            if confirmation['status'] == 'error':
                return render_template('supplier_portal/error.html', 
                                     error=confirmation['message']), 400
            
            return render_template('supplier_portal/bid_confirmation.html',
                                 confirmation=confirmation)
    
    except Exception as e:
        logger.error(f"Error showing confirmation: {str(e)}")
        return render_template('supplier_portal/error.html', 
                             error="An error occurred"), 500

@supplier_bp.route('/logout')
def logout():
    """
    Clear session and logout
    """
    session.clear()
    return redirect(url_for('main.index'))  # Adjust to your home page route