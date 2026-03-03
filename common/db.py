from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from .logging_config import get_logger
from .config import get_config
import urllib

_cfg = get_config()
logger = get_logger(__name__)

# Validate required environment variables
required_vars = ["DB_DRIVER", "DB_SERVER", "DB_DATABASE", "DB_USERNAME", "DB_PASSWORD"]
for var in required_vars:
    if getattr(_cfg, var) is None:
        raise ValueError(f"Environment variable '{var}' is not set")

# Build connection string (env-only, no hardcoded defaults)
params = urllib.parse.quote_plus(
    f"DRIVER={{{_cfg.DB_DRIVER}}};"
    f"SERVER={_cfg.DB_SERVER};"
    f"DATABASE={_cfg.DB_DATABASE};"
    f"UID={_cfg.DB_USERNAME};"
    f"PWD={_cfg.DB_PASSWORD};"
    f"Encrypt=yes;"
    f"TrustServerCertificate=yes;"
    f"Connection Timeout=10;"
)

DATABASE_URL = f"mssql+pyodbc:///?odbc_connect={params}"

# Create engine and session
engine = create_engine(DATABASE_URL, fast_executemany=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

def get_db():
    """Provide a SQLAlchemy session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def test_connection():
    """Test database connection for StartupValidator"""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        logger.info("Database Connection Successful")
    except Exception as e:
        logger.error(f"Database connection Failed: {e}")
        raise
