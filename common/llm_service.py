
import logging
from typing import Dict, Any, Optional, List
import time
from ..core.langchain_interface import LangChainInterface

logger = logging.getLogger(__name__)

class LLMService:
    def __init__(self, credential_loader=None):
        self.credential_loader = credential_loader
        self._llm_cache = {}  # Cache LLM instances by model name
        
    def get_llm(self, model_name: str, params: Dict[str, Any], 
                credentials: Optional[Dict[str, Any]] = None,
                project_id: Optional[str] = None) -> LangChainInterface:
        """Get or create LLM instance with auto-recovery support"""
        cache_key = f"{model_name}_{str(params)}"
        
        if cache_key not in self._llm_cache:
            # Use provided credentials or fetch from loader
            if credentials is None and self.credential_loader:
                fresh_creds = self.credential_loader.get_watson_credentials_with_retry()
                if fresh_creds:
                    credentials = {
                        "url": fresh_creds.get('ibm_cloud_url'), 
                        "apikey": fresh_creds.get('api_key')
                    }
                    project_id = fresh_creds.get('project_id')
            
            if not credentials:
                raise ValueError("No credentials available for LLM")
            
            # Note: Using model_name, not 'model' parameter
            self._llm_cache[cache_key] = LangChainInterface(
                model=model_name,  # This might be the issue - check your LangChainInterface
                credentials=credentials,
                params=params,
                project_id=project_id
            )
        
        return self._llm_cache[cache_key]
    
    def invoke_with_recovery(self, model_name: str, params: Dict[str, Any], 
                           prompt: str, max_retries: int = 2,
                           credentials: Optional[Dict[str, Any]] = None,
                           project_id: Optional[str] = None) -> str:
        """Invoke LLM with auto-recovery on auth errors"""
        for attempt in range(max_retries):
            try:
                llm = self.get_llm(model_name, params, credentials, project_id)
                
                response = llm.invoke(prompt)
                
                clean_response = response.encode('ascii', 'ignore').decode('ascii')
                logger.info(f"LLM Output - Model: {model_name}, Response: {clean_response}")
                
                return response
                
            except Exception as e:
                error_str = str(e).lower()
                is_auth_error = any(
                    keyword in error_str 
                    for keyword in ['auth', 'unauthorized', 'authentication', 'apikey', 'token', '401', '403']
                )
                
                if is_auth_error and attempt < max_retries - 1:
                    logger.warning(f"LLM auth error (attempt {attempt+1}) for model {model_name}")
                    
                    # Clear LLM cache for this model
                    cache_key = f"{model_name}_{str(params)}"
                    if cache_key in self._llm_cache:
                        del self._llm_cache[cache_key]
                    
                    # Trigger credential reload
                    if self.credential_loader:
                        self.credential_loader.trigger_auto_reload()
                        time.sleep(5)
                    
                    continue
                else:
                    raise
    
    def refresh_all_llms(self):
        """Refresh all cached LLM instances"""
        self._llm_cache.clear()
        logger.info("All LLM instances refreshed")

# Global instance
llm_service = None