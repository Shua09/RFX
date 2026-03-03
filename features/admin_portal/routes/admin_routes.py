# src/features/admin_portal/routes/admin_routes.py

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from ..services.admin_service import AdminService
from ....common.logging_config import get_logger
from ..services.ai_bid_evaluation_service import AIBidEvaluationService

logger = get_logger(__name__)
admin_bp = Blueprint('admin', __name__,)

# Simple admin authentication (you should implement proper auth)
ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'admin123'  # Change this in production

@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Admin login page"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin.dashboard'))
        else:
            return render_template('admin_portal/login.html', error="Invalid credentials")
    
    return render_template('admin_portal/login.html')

@admin_bp.route('/logout')
def logout():
    """Admin logout"""
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin.login'))

def admin_required(f):
    """Decorator to require admin login"""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin.login'))
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/')
@admin_required
def dashboard():
    """Admin dashboard home"""
    return render_template('admin_portal/dashboard.html')

@admin_bp.route('/api/dashboard/stats')
@admin_required
def api_dashboard_stats():
    """API endpoint for dashboard statistics"""
    with AdminService() as service:
        result = service.get_dashboard_stats()
        return jsonify(result)

@admin_bp.route('/rfqs')
@admin_required
def rfq_list():
    """List all RFQs"""
    status_filter = request.args.get('status', 'ALL')
    return render_template('admin_portal/rfq_list.html', current_filter=status_filter)

@admin_bp.route('/api/rfqs')
@admin_required
def api_rfq_list():
    """API endpoint for RFQ list"""
    status_filter = request.args.get('status', 'ALL')
    with AdminService() as service:
        result = service.get_all_rfqs(status_filter if status_filter != 'ALL' else None)
        return jsonify(result)

@admin_bp.route('/rfq/<rfq_id>')
@admin_required
def rfq_detail(rfq_id):
    """RFQ detail page"""
    return render_template('admin_portal/rfq_detail.html', rfq_id=rfq_id)

@admin_bp.route('/api/rfq/<rfq_id>')
@admin_required
def api_rfq_detail(rfq_id):
    """API endpoint for RFQ details"""
    with AdminService() as service:
        result = service.get_rfq_details(rfq_id)
        return jsonify(result)

@admin_bp.route('/api/rfq/<rfq_id>/status', methods=['POST'])
@admin_required
def api_update_rfq_status(rfq_id):
    """API endpoint to update RFQ status"""
    data = request.get_json()
    status = data.get('status')
    
    with AdminService() as service:
        result = service.update_rfq_status(rfq_id, status)
        return jsonify(result)

@admin_bp.route('/bid/<int:mapping_id>')
@admin_required
def bid_detail(mapping_id):
    """Bid detail page"""
    return render_template('admin_portal/bid_detail.html', mapping_id=mapping_id)

@admin_bp.route('/api/bid/<int:mapping_id>')
@admin_required
def api_bid_detail(mapping_id):
    """API endpoint for bid details"""
    with AdminService() as service:
        result = service.get_bid_details(mapping_id)
        return jsonify(result)

@admin_bp.route('/api/bid/<int:mapping_id>/award', methods=['POST'])
@admin_required
def api_award_bid(mapping_id):
    """API endpoint to award a bid"""
    with AdminService() as service:
        result = service.award_bid(mapping_id)
        return jsonify(result)
    
@admin_bp.route('/api/bid/<int:mapping_id>/evaluate', methods=['POST'])
@admin_required
def api_evaluate_bid(mapping_id):
    """API endpoint to evaluate a bid using AI"""
    with AIBidEvaluationService() as service:
        result = service.evaluate_bid(mapping_id)
        return jsonify(result)

@admin_bp.route('/api/rfq/<rfq_id>/compare-bids')
@admin_required
def api_compare_bids(rfq_id):
    """API endpoint to compare all bids for an RFQ"""
    with AIBidEvaluationService() as service:
        result = service.compare_bids(rfq_id)
        return jsonify(result)

@admin_bp.route('/api/bid/<int:mapping_id>/evaluation-report')
@admin_required
def api_evaluation_report(mapping_id):
    """API endpoint to get evaluation report"""
    with AIBidEvaluationService() as service:
        result = service.get_evaluation_report(mapping_id)
        return jsonify(result)

@admin_bp.route('/rfq/<rfq_id>/evaluation')
@admin_required
def rfq_evaluation(rfq_id):
    """RFQ evaluation page with bid comparison"""
    return render_template('admin_portal/rfq_evaluation.html', rfq_id=rfq_id)

@admin_bp.route('/bids')
@admin_required
def bids_list():
    """List all RFQs for bid management"""
    return render_template('admin_portal/bid_list.html')

@admin_bp.route('/api/rfq/<rfq_id>/ai-summary', methods=['GET'])
@admin_required
def api_rfq_ai_summary(rfq_id):
    """API endpoint to get AI-generated summary for RFQ bids"""
    try:
        with AIBidEvaluationService() as service:
            # Get the comparison data first
            comparison = service.compare_bids(rfq_id)
            
            if comparison['status'] != 'success':
                return jsonify({
                    "status": "error", 
                    "message": comparison.get('message', 'Failed to get bid data')
                })
            
            # Generate AI summary for all bids
            summary = service.generate_rfq_ai_summary(rfq_id, comparison.get('ranked_bids', []))
            return jsonify(summary)
            
    except Exception as e:
        logger.error(f"Error generating AI summary: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        })
        
