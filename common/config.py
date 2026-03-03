import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    DB_SERVER = os.getenv("DB_SERVER")
    DB_DATABASE = os.getenv("DB_DATABASE")
    DB_USERNAME = os.getenv("DB_USERNAME")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server")
    
    #Langchain/ IBM WATSONX
    IBM_API_KEY = os.getenv("IBM_API_KEY")
    IBM_CLOUD_URL = os.getenv("IBM_CLOUD_URL")
    IBM_PROJECT_ID = os.getenv("IBM_PROJECT_ID")
    IBM_MODEL = os.getenv("IBM_MODEL", "ibm/granite-3-8b-instruct")
    IBM_EMBEDDING_MODEL = os.getenv("IBM_EMBEDDING_MODEL", "ibm/slate-125m-english-rtrvr")
    
    #SECRET KEY
    BASE_ROUTE = os.getenv("BASE_ROUTE")
    SECRET_KEY = os.getenv("SECRET_KEY")
    
    SESSION_TYPE = 'filesystem'
    SESSION_FILE_DIR = './flask_session'
    SESSION_PERMANENT = False
    SESSION_USE_SIGNER = True
    SESSION_KEY_PREFIX = 'hr_assistant'
    
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = False  # Set to True in production (HTTPS)
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 1800  # 30 minutes
    
    # Email Configuration for Supplier Matching
    SMTP_HOST = os.getenv("SMTP_HOST")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
    SMTP_EMAIL = os.getenv("SMTP_EMAIL")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
    SENDER_NAME = os.getenv("SENDER_NAME", "Procurement Department")
    APP_BASE_URL = os.getenv("APP_BASE_URL", "https://yourdomain.com")

    # Supplier Matching Configuration
    AUTO_MATCH_SUPPLIERS = os.getenv("AUTO_MATCH_SUPPLIERS", "true")
    EMAIL_TEST_MODE = os.getenv("EMAIL_TEST_MODE", "true")
    
def get_config():
    return Config