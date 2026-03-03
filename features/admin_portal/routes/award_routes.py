from flask import Blueprint, request, jsonify, render_template
from ....common.logging_config import get_logger
from ..services.award_management_service import AwardManagementService
from ..services.admin_service import AdminService
from datetime import datetime

logger = get_logger(__name__)
award_bp = Blueprint('award', __name__)

@award_bp.route('/award/<rfq_id>', methods=['GET'])
def award_page(rfq_id):
    """
    Render the award selection page for a specific RFQ
    """
    try:
        # You can pass the RFQ ID to the template
        return render_template('admin_portal/awarding_of_bidding.html', rfq_id=rfq_id)
    except Exception as e:
        logger.error(f"Error rendering award page: {str(e)}")
        return render_template('admin_portal/error.html', error="Page not found"), 404

@award_bp.route('/api/award/selection-data/<rfq_id>', methods=['GET'])
def get_award_selection_data(rfq_id):
    """Get data for per-product award selection UI with checkboxes and quantity inputs"""
    with AwardManagementService() as service:
        result = service.get_award_selection_data(rfq_id)
        return jsonify(result)


@award_bp.route('/api/award/validate-selections', methods=['POST'])
def validate_award_selections():
    """Validate admin's award selections before creating proposal"""
    data = request.get_json()
    
    required_fields = ['rfq_id', 'selections']
    for field in required_fields:
        if field not in data:
            return jsonify({"status": "error", "message": f"Missing field: {field}"}), 400
    
    with AwardManagementService() as service:
        result = service.validate_award_selection(data['rfq_id'], data['selections'])
        return jsonify(result)


@award_bp.route('/api/award/create-from-selections', methods=['POST'])
def create_proposal_from_selections():
    """Create award proposal from user selections"""
    data = request.get_json()
    
    required_fields = ['rfq_id', 'selections', 'customer_email']
    for field in required_fields:
        if field not in data:
            return jsonify({"status": "error", "message": f"Missing field: {field}"}), 400
    
    with AwardManagementService() as service:
        result = service.create_award_proposal_from_selections(
            rfq_id=data['rfq_id'],
            selections=data['selections'],
            customer_email=data['customer_email'],
            notes=data.get('notes')
        )
        
        if result['status'] == 'success':
            # Send email to customer
            with AdminService() as admin_service:
                email_sent = send_proposal_email(
                    admin_service=admin_service,
                    proposal_id=result['proposal_id'],
                    customer_email=data['customer_email'],
                    rfq_id=data['rfq_id'],
                    access_token=result['access_token'],
                    expires_at=result['expires_at']
                )
                result['email_sent'] = email_sent
        
        return jsonify(result)


def send_proposal_email(admin_service, proposal_id, customer_email, rfq_id, access_token, expires_at):
    """Helper function to send proposal email to customer"""
    try:
        subject = f"Action Required: Award Proposal for RFQ {rfq_id} Ready for Review"
        
        # Create confirmation link
        base_url = getattr(admin_service, 'base_url', 'https://yourdomain.com')
        confirmation_link = f"{base_url}/customer/confirm-award/{proposal_id}?token={access_token}"
        
        # Format expires_at for display
        if isinstance(expires_at, str):
            try:
                expires_at_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                expires_at_formatted = expires_at_dt.strftime("%B %d, %Y at %I:%M %p")
            except:
                expires_at_formatted = expires_at
        else:
            expires_at_formatted = expires_at.strftime("%B %d, %Y at %I:%M %p") if hasattr(expires_at, 'strftime') else str(expires_at)
        
        # HTML Email Body
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                .container {{ font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; }}
                .header {{ background: linear-gradient(135deg, #2563eb, #1e40af); color: white; padding: 30px 20px; text-align: center; }}
                .content {{ padding: 30px 20px; background-color: #f9f9f9; }}
                .button {{ display: inline-block; padding: 12px 24px; background-color: #2563eb; color: white; 
                        text-decoration: none; border-radius: 5px; font-weight: bold; margin: 20px 0; }}
                .info-box {{ background-color: white; padding: 20px; border-radius: 10px; margin: 20px 0; 
                          border-left: 4px solid #2563eb; }}
                .warning {{ background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; }}
                .footer {{ background-color: #e9e9e9; padding: 20px; text-align: center; font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>📋 RFQ Award Proposal</h1>
                    <h2>Ready for Your Review</h2>
                </div>
                
                <div class="content">
                    <p>Dear Customer,</p>
                    
                    <p>We have evaluated all bids for your RFQ <strong>{rfq_id}</strong> and have prepared 
                    an award proposal for your review and confirmation.</p>
                    
                    <div class="info-box">
                        <h3>📊 Proposal Summary</h3>
                        <table style="width:100%;">
                            <tr>
                                <td><strong>RFQ ID:</strong></td>
                                <td>{rfq_id}</td>
                            </tr>
                            <tr>
                                <td><strong>Proposal ID:</strong></td>
                                <td>{proposal_id}</td>
                            </tr>
                        </table>
                    </div>
                    
                    <div class="warning">
                        <strong>⚠️ Important:</strong> This proposal will expire on 
                        <strong>{expires_at_formatted}</strong>. Please review and confirm before the expiration date.
                    </div>
                    
                    <p>Click the button below to review the detailed award proposal and confirm your approval:</p>
                    
                    <p style="text-align: center;">
                        <a href="{confirmation_link}" class="button">Review & Confirm Award</a>
                    </p>
                    
                    <p>Once you confirm, we will proceed with finalizing the awards and notify the 
                    successful suppliers.</p>
                    
                    <p>If you have any questions or need to discuss the proposal, please contact our 
                    procurement team.</p>
                </div>
                
                <div class="footer">
                    <p>This is an automated message from the Procurement System.</p>
                    <p>&copy; {datetime.now().year} Procurement Department. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Plain Text Email Body
        text_body = f"""
        RFQ AWARD PROPOSAL - ACTION REQUIRED
        
        Dear Customer,
        
        We have evaluated all bids for your RFQ {rfq_id} and have prepared an award proposal for your review.
        
        SUMMARY:
        - RFQ ID: {rfq_id}
        - Proposal ID: {proposal_id}
        
        Please review and confirm at: {confirmation_link}
        
        This proposal will expire on {expires_at_formatted}.
        
        Once confirmed, we will proceed with finalizing the awards.
        
        This is an automated message from the Procurement System.
        """
        
        # Send email using AdminService's email method
        return admin_service.send_email(
            to_email=customer_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body
        )
        
    except Exception as e:
        logger.error(f"Failed to send proposal email: {str(e)}")
        return False


# Optional: Add a route to get pending proposals
@award_bp.route('/api/award/proposals', methods=['GET'])
def get_pending_proposals():
    """Get all pending proposals"""
    rfq_id = request.args.get('rfq_id')
    
    with AwardManagementService() as service:
        result = service.get_pending_proposals(rfq_id)
        return jsonify(result)


# Optional: Add a route to cancel a proposal
@award_bp.route('/api/award/proposal/<int:proposal_id>/cancel', methods=['POST'])
def cancel_proposal(proposal_id):
    """Cancel a pending proposal"""
    with AwardManagementService() as service:
        result = service.cancel_proposal(proposal_id)
        return jsonify(result)