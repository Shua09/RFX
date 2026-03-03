from .logging_config import get_logger
from .config import get_config
import urllib
import pyodbc

_cfg = get_config()
logger = get_logger(__name__)

def get_db_connection():
    try:
        conn_str = (
            f"DRIVER={{{_cfg.DB_DRIVER}}};"
            f"SERVER={_cfg.DB_SERVER};"
            f"DATABASE={_cfg.DB_DATABASE};"
            f"UID={_cfg.DB_USERNAME};"
            f"PWD={_cfg.DB_PASSWORD};"
        )
        return pyodbc.connect(conn_str)
    except Exception as e:
        logger.error(f"Database Connection failed:{e}")
        raise