from ..common import get_logger
from flask import redirect

logger = get_logger(__name__)

def register_blueprints(app):
    """
    Register all blueprints
    """
    
    base_route = app.config.get(
        'BASE_ROUTE',
    )
    
    #Procurement Watson-Assistant API
    from ..features.procurement_assistant.routes.extraction_routes import extraction_bp
    from ..features.procurement_assistant.routes.confirmation_routes import confirmation_bp
    app.register_blueprint(extraction_bp, url_prefix=f"{base_route}/api/procurement")
    app.register_blueprint(confirmation_bp, url_prefix=f"{base_route}/api/procurement")
    
    #Supplier
    from ..features.supplier_portal.routes.supplier_routes import supplier_bp
    app.register_blueprint(supplier_bp, url_prefix=f"{base_route}/supplier")
    
    #Admin
    from ..features.admin_portal.routes.admin_routes import admin_bp
    from ..features.admin_portal.routes.award_routes import award_bp
    app.register_blueprint(award_bp, url_prefix=f"{base_route}/admin")
    app.register_blueprint(admin_bp, url_prefix=f"{base_route}/admin")
    
    #Customer
    from ..features.customer.routes.request_routes import customer_request
    from ..features.customer.routes.customer_award_routes import customer_award_bp
    app.register_blueprint(customer_request, url_prefix=f"{base_route}/customer")
    app.register_blueprint(customer_award_bp, url_prefix=f"{base_route}/customer")
    
    #HR_Assistant blueprint
    # from ..features.hr_assistant.routes import hr_upload_bp, hr_database_bp
    # app.register_blueprint(hr_upload_bp, url_prefix=f"{base_route}/hr")
    # app.register_blueprint(hr_database_bp, url_prefix=f"{base_route}/hr")
    
    # from ..features.user_assistant.routes import user_assistant_bp
    # app.register_blueprint(user_assistant_bp, url_prefix=f"{base_route}/askInno")
        
    #Default route to redirect to portal
    @app.route("/")
    def redirect_to_default():
        return redirect(f"{base_route}/admin")
    
    logger.info(f"All blueprints are registered successfully")