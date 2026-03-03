# credential_loader.py
import requests
import os
import logging
import time
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
from dotenv import load_dotenv
import threading
from queue import Queue
import json

logger = logging.getLogger(__name__)

class AutoReloadCredentialLoader:
    """Credential loader with automatic failure detection and recovery"""
    
    def __init__(self, max_retries: int = 3, retry_delay: int = 5):
        load_dotenv()
        
        # Configuration
        self.base_url = os.getenv('IAM_MANAGEMENT_URL', 'http://localhost:5001')
        self.company_name = os.getenv('COMPANY_NAME', 'DELCA')
        
        # Retry configuration
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        # Cache
        self._credentials_cache = {}
        self._cache_expiry = {}
        self._failure_count = {}  # Track failures per company
        
        # Auto-reload thread
        self._reload_queue = Queue()
        self._reload_thread = None
        self._running = True
        
        # Statistics
        self.stats = {
            'total_requests': 0,
            'cache_hits': 0,
            'reloads_attempted': 0,
            'reloads_successful': 0,
            'reloads_failed': 0,
            'last_failure': None,
            'last_success': datetime.now()
        }
        
        # Start auto-reload thread
        self._start_reload_thread()
        
        logger.info(f"AutoReloadCredentialLoader initialized for company: {self.company_name}")
        
    def _start_reload_thread(self):
        """Start background thread for automatic credential reloading"""
        self._reload_thread = threading.Thread(
            target=self._reload_worker,
            daemon=True,
            name="CredentialReloadWorker"
        )
        self._reload_thread.start()
        logger.info("Auto-reload thread started")
    
    def _reload_worker(self):
        """Background worker that handles automatic credential reloads"""
        while self._running:
            try:
                # Check for items in reload queue
                if not self._reload_queue.empty():
                    company = self._reload_queue.get_nowait()
                    self._perform_auto_reload(company)
                
                # Sleep briefly to prevent CPU spinning
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Error in reload worker: {str(e)}")
                time.sleep(5)
    
    def _perform_auto_reload(self, company: str):
        """Perform automatic credential reload and update IAM system"""
        self.stats['reloads_attempted'] += 1
        
        try:
            logger.info(f"Auto-reloading credentials for {company}")
            
            # Clear cache and fetch fresh credentials
            self.clear_cache(company)
            credentials = self._fetch_credentials_from_iam(company)
            
            if credentials:
                self._cache_credentials(company, credentials)
                self.stats['reloads_successful'] += 1
                self.stats['last_success'] = datetime.now()
                
                # Test the new credentials
                if self._test_credentials(credentials):
                    logger.info(f"Auto-reload successful for {company}")
                    # Update IAM system with success
                    self._update_iam_test_status(company, 'success')
                else:
                    logger.error(f"Auto-reloaded credentials failed test for {company}")
                    self._update_iam_test_status(company, 'failed')
            else:
                self.stats['reloads_failed'] += 1
                logger.error(f"Auto-reload failed: Could not fetch credentials for {company}")
                self._update_iam_test_status(company, 'failed')
                
        except Exception as e:
            self.stats['reloads_failed'] += 1
            logger.error(f"Auto-reload error for {company}: {str(e)}")
            self._update_iam_test_status(company, 'failed')
    
    def _update_iam_test_status(self, company: str, status: str):
        """Update test_status in IAM system"""
        try:
            api_url = f"{self.base_url}/api/watson-keys/company/{company}/test-status"
            
            response = requests.post(
                api_url,
                json={'test_status': status},
                timeout=5
            )
            
            if response.status_code == 200:
                logger.debug(f"Updated IAM test_status for {company} to {status}")
            else:
                logger.warning(f"Failed to update IAM test_status: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Error updating IAM test_status: {str(e)}")
    
    def _test_credentials(self, credentials: Dict) -> bool:
        """Test if credentials work with IBM Watson"""
        try:
            # Simple test: Get IBM access token
            test_url = "https://iam.cloud.ibm.com/identity/token"
            
            response = requests.post(
                test_url,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey": credentials.get('api_key')
                },
                timeout=10
            )
            
            return response.status_code == 200
            
        except Exception as e:
            logger.error(f"Credential test failed: {str(e)}")
            return False
    
    def get_watson_credentials_with_retry(self, company_name: str = None) -> Optional[Dict]:
        """Get credentials with automatic retry on failure"""
        company = company_name or self.company_name
        self.stats['total_requests'] += 1
        
        # Check cache first
        if self._is_cached_valid(company):
            self.stats['cache_hits'] += 1
            cached = self._credentials_cache[company]
            
            # If cached credentials were marked as failed, trigger reload
            if cached.get('_test_status') == 'failed':
                logger.warning(f"Cached credentials for {company} are marked as failed, triggering reload")
                self.trigger_auto_reload(company)
            
            return cached
        
        # Fetch with retry logic
        for attempt in range(self.max_retries):
            try:
                credentials = self._fetch_credentials_from_iam(company)
                
                if credentials:
                    # Test the credentials
                    if self._test_credentials(credentials):
                        credentials['_test_status'] = 'success'
                        self._cache_credentials(company, credentials)
                        self._failure_count[company] = 0
                        return credentials
                    else:
                        credentials['_test_status'] = 'failed'
                        self._cache_credentials(company, credentials)
                        self._failure_count[company] = self._failure_count.get(company, 0) + 1
                        
                        # Trigger auto-reload if credentials fail
                        if self._failure_count[company] >= 2:
                            logger.warning(f"Credentials failed {self._failure_count[company]} times, triggering auto-reload")
                            self.trigger_auto_reload(company)
                        
                        if attempt < self.max_retries - 1:
                            time.sleep(self.retry_delay)
                            continue
                        else:
                            logger.error(f"All credential attempts failed for {company}")
                            return None
                        
            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed for {company}: {str(e)}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                    continue
        
        return None
    
    def _fetch_credentials_from_iam(self, company: str) -> Optional[Dict]:
        """Fetch credentials from IAM API"""
        try:
            api_url = f"{self.base_url}/api/watson-credentials/company/{company}"
            
            response = requests.get(api_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success') and 'data' in data:
                    return data['data']
            elif response.status_code == 404:
                logger.error(f"Company '{company}' not found in IAM system")
            else:
                logger.error(f"IAM API error: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Error fetching from IAM: {str(e)}")
        
        return None
    
    def trigger_auto_reload(self, company: str = None):
        """Trigger automatic credential reload"""
        company = company or self.company_name
        self._reload_queue.put(company)
        logger.info(f"Auto-reload triggered for {company}")
    
    def check_and_auto_reload(self, company: str = None) -> bool:
        """Check credentials and auto-reload if they're failing"""
        company = company or self.company_name
        
        # Get current credentials
        credentials = self._credentials_cache.get(company)
        
        if not credentials:
            return False
        
        # Check if credentials are marked as failed
        if credentials.get('_test_status') == 'failed':
            logger.info(f"Credentials for {company} are marked as failed, triggering auto-reload")
            self.trigger_auto_reload(company)
            return True
        
        # Test credentials
        if not self._test_credentials(credentials):
            logger.warning(f"Credential test failed for {company}, marking as failed and triggering reload")
            credentials['_test_status'] = 'failed'
            self._cache_credentials(company, credentials)
            self.trigger_auto_reload(company)
            return True
        
        return False
    
    def _cache_credentials(self, company: str, credentials: Dict):
        """Cache credentials with extended metadata"""
        credentials['_cached_at'] = datetime.now().isoformat()
        credentials['_cache_expiry'] = (datetime.now() + timedelta(seconds=300)).isoformat()
        self._credentials_cache[company] = credentials
    
    def _is_cached_valid(self, company: str) -> bool:
        """Check if cached credentials are valid"""
        if company not in self._credentials_cache:
            return False
        
        cached = self._credentials_cache[company]
        expiry_str = cached.get('_cache_expiry')
        
        if not expiry_str:
            return False
        
        try:
            expiry = datetime.fromisoformat(expiry_str.replace('Z', '+00:00'))
            return datetime.now() < expiry
        except:
            return False
    
    def clear_cache(self, company: str = None):
        """Clear credential cache"""
        if company:
            self._credentials_cache.pop(company, None)
        else:
            self._credentials_cache.clear()
    
    def get_stats(self) -> Dict:
        """Get loader statistics"""
        return {
            **self.stats,
            'cache_size': len(self._credentials_cache),
            'failure_counts': dict(self._failure_count),
            'queue_size': self._reload_queue.qsize(),
            'uptime': str(datetime.now() - self.stats.get('start_time', datetime.now()))
        }
    
    def shutdown(self):
        """Graceful shutdown"""
        self._running = False
        if self._reload_thread:
            self._reload_thread.join(timeout=5)