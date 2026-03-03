import logging
from typing import Dict, List, Tuple
from .db import test_connection

logger = logging.getLogger(__name__)

class StartupValidator:
    """Handle Startup Validations and health checks"""
    
    def __init__(self, app):
        self.app = app
        self.checks: List[Tuple[str, callable]] = []
        
        #DB Connection
        self.add_check("Database Connection", test_connection)
        
    def add_check(self, name: str, check_function: callable):
        self.checks.append((name, check_function))
        
    def validate_configuration(self) -> Dict[str, bool]:
        """Validate all configurations"""
        results = {}
        
        logger.info("Starting the Application Startup Validation...")
        logger.info(f"Base Route: {self.app.config.get('BASE_ROUTE', '/NOAH_AI')}")
        logger.info("Unicode support: Enabled")
        
        for name, check_function in self.checks:
            try:
                check_function()
                results[name] = True
                logger.info(f"[PASS] {name}")
            except Exception as e:
                results[name] = False
                logger.error(f"[FAIL] {name}: {e}")
                
        return results

            
        