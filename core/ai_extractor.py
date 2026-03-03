# src/core/ai_extractor.py
import json
import re
from typing import Dict, Any, Optional
from ..common import get_logger, llm_service
from ..features.procurement_assistant.utils.prompt_templates import EXTRACTION_SYSTEM_PROMPT
from ..features.procurement_assistant.utils.json_formatter import JSONFormatter

logger = get_logger(__name__)

class AIExtractor:
    """Handles AI-powered extraction using IBM Watson LLM with clean JSON output"""
    
    def __init__(self):
        self.model_name = "ibm/granite-3-8b-instruct"
        self.params = {
            "decoding_method": "greedy",
            "max_new_tokens": 800,
            "temperature": 0.1,
            "top_p": 0.9
        }
        self.formatter = JSONFormatter()
    
    def extract_procurement_request(self, user_input: str) -> Dict[str, Any]:
        """
        Extract structured procurement data using AI
        Returns clean JSON that matches the structure in prompt_templates.py
        """
        try:
            # Construct the full prompt with examples
            full_prompt = f"""{EXTRACTION_SYSTEM_PROMPT}

User: {user_input}

Remember: Return ONLY the JSON object, no other text."""

            if llm_service is None:
                logger.warning("LLM service not available")
                return self._get_empty_request()
            
            try:
                response = llm_service.invoke_with_recovery(
                    model_name=self.model_name,
                    params=self.params,
                    prompt=full_prompt,
                    max_retries=1
                )
                
                # Clean and parse the JSON
                json_data = self._clean_and_parse_json(response)
                
                # Validate the structure
                if self.formatter.validate_json_structure(json_data):
                    logger.info(f"Successfully extracted valid JSON with {len(json_data.get('items', []))} items")
                    return json_data
                else:
                    logger.warning("Extracted JSON had invalid structure")
                    return self._get_empty_request()
                
            except Exception as e:
                logger.error(f"LLM extraction failed: {str(e)}")
                return self._get_empty_request()
            
        except Exception as e:
            logger.error(f"Error in extraction: {str(e)}")
            return self._get_empty_request()
    
    def _clean_and_parse_json(self, text: str) -> Dict[str, Any]:
        """Clean and parse JSON from AI response - handles multiple objects"""
        # Remove markdown code blocks
        text = text.replace('```json', '').replace('```', '').strip()
        
        # Look for the first complete JSON object
        brace_count = 0
        start_idx = -1
        end_idx = -1
        
        for i, char in enumerate(text):
            if char == '{':
                if brace_count == 0:
                    start_idx = i
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0 and start_idx != -1:
                    end_idx = i + 1
                    break
        
        if start_idx != -1 and end_idx != -1:
            json_str = text[start_idx:end_idx]
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.error(f"JSON parse error: {e}")
                raise
        
        # If no JSON object found with brace counting, try regex
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            json_str = json_match.group()
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.error(f"JSON parse error: {e}")
                raise
        
        # If all fails, try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Direct JSON parse failed: {e}")
            raise
        
    def _get_empty_request(self) -> Dict[str, Any]:
        """Return an empty but valid request structure"""
        return {
            "items": [],
            "budget_total": None,
            "budget_per_unit": None,
            "currency": "USD",
            "delivery_location": None,
            "delivery_date": None,
            "priority": "medium",
            "payment_terms": None,
            "special_instructions": None
        }
    
    def extract_modification(self, original_request: Dict[str, Any], 
                        modification_message: str) -> Dict[str, Any]:
        """
        Specifically extract modifications from a message in the context of an existing request
        """
        try:
            from ..features.procurement_assistant.utils.prompt_templates import REQUEST_MERGE_PROMPT
            
            # Format the original request as JSON string
            original_json = json.dumps(original_request, indent=2)
            
            # Build the prompt
            prompt = REQUEST_MERGE_PROMPT.format(
                original_request=original_json,
                modification_message=modification_message
            )
            
            if llm_service is None:
                logger.warning("LLM service not available for modification")
                return original_request
            
            response = llm_service.invoke_with_recovery(
                model_name=self.model_name,
                params=self.params,
                prompt=prompt,
                max_retries=1
            )
            
            # Clean and parse the JSON
            modified_json = self._clean_and_parse_json(response)
            
            # Validate the structure
            if self.formatter.validate_json_structure(modified_json):
                logger.info(f"Successfully modified request with {len(modified_json.get('items', []))} items")
                return modified_json
            else:
                logger.warning("Modified JSON had invalid structure")
                return original_request
            
        except Exception as e:
            logger.error(f"Error in modification extraction: {str(e)}")
            return original_request