import os
import logging
from logging.handlers import RotatingFileHandler

def setup_logging():
    """
    Setup the logging configuration
    """
    #Logs directory
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        
    #Main application logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    logger.handlers.clear()
    
    #Format
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    #File handler
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'app.log'),
        maxBytes=1024 * 1024 * 5,
        backupCount=10
    )
    file_handler.setFormatter(formatter)
    
    #Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    #Log to /logs/app.log
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    #Log Startup
    logger.info("Logging Configuration Initialized")
    
    return logger

def get_logger(name):
    return logging.getLogger(name)
    
    
    