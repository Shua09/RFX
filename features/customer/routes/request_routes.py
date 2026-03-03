from flask import Blueprint, request, render_template, jsonify, session as flask_session
from ....common import get_logger
import os

logger = get_logger(__name__)

# Create blueprint without url_prefix
customer_request = Blueprint('customer', __name__)

@customer_request.route('/', methods=['GET'])
def index():
    """Index endpoint for customer request"""
    return render_template('request.html')