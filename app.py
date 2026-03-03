from flask import Flask, redirect
from flask_session import Session #REMOVE IN PROD
from .common import Config, setup_logging, get_logger, StartupValidator
from flask_cors import CORS
import os

def create_app():
    #Setup Logs
    logger = setup_logging()
    app_logger = get_logger(__name__)
    
    #Get the base directory
    base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    template_dir = os.path.join(base_dir, 'templates')
    static_dir = os.path.join(base_dir, 'static')
    
    #Create the Flask app
    app = Flask(
        __name__,
        template_folder=template_dir,
        static_folder=static_dir
    )
    
    #Load Config
    app.config.from_object(Config)
    
    # Initialize Flask-Session - REMOVE IN PROD
    Session(app)
    
    #Cors
    CORS(app)
    
    #Blueprints
    from .core import register_blueprints
    register_blueprints(app)
    
    #Startup Validation
    validator = StartupValidator(app)
    results = validator.validate_configuration()
    
    # If any check fails, you can decide to raise or just log
    if not all(results.values()):
        app_logger.error("Startup validation failed! Exiting...")

    return app