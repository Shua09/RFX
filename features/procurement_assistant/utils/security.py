# src/features/procurement_assistant/utils/security.py
import secrets
import string
import hashlib
import hmac
import base64
from datetime import datetime, timedelta
from ....common.config import get_config

_cfg = get_config()

class AccessCodeGenerator:
    """Generate and validate secure access codes and passcodes"""
    
    @staticmethod
    def generate_access_code() -> str:
        """
        Generate a secure random access code for URL
        Format: 3 parts with hyphens for readability
        Example: X7K9-4M2P-8R5V
        """
        groups = []
        chars = string.ascii_uppercase + string.digits
        
        for _ in range(3):
            group = ''.join(secrets.choice(chars) for _ in range(4))
            groups.append(group)
        
        return '-'.join(groups)
    
    @staticmethod
    def generate_passcode() -> str:
        """
        Generate a secure random passcode (shorter, easier to type)
        Format: 2 parts with hyphen (8 characters total)
        Example: 4M2P-8R5V
        """
        groups = []
        chars = string.ascii_uppercase + string.digits
        
        for _ in range(2):
            group = ''.join(secrets.choice(chars) for _ in range(4))
            groups.append(group)
        
        return '-'.join(groups)
    
    @staticmethod
    def generate_numeric_passcode(length: int = 6) -> str:
        """
        Alternative: Generate numeric passcode (easier for phone users)
        Example: 482759
        """
        return ''.join(secrets.choice(string.digits) for _ in range(length))
    
    @staticmethod
    def encrypt_access_code(raw_code: str) -> str:
        """
        Generate an encrypted version of the access code for URL
        """
        # Create a signature using HMAC
        secret_key = _cfg.SECRET_KEY.encode('utf-8')
        message = raw_code.encode('utf-8')
        
        # Create HMAC signature
        signature = hmac.new(secret_key, message, hashlib.sha256).hexdigest()[:16]
        
        # Combine data with signature
        encrypted = f"{raw_code}.{signature}"
        
        # URL-safe base64 encoding
        return base64.urlsafe_b64encode(encrypted.encode()).decode()
    
    @staticmethod
    def decrypt_access_code(encrypted_code: str) -> tuple:
        """
        Validate and decrypt the access code
        Returns (is_valid, original_code)
        """
        try:
            # Decode from base64
            decoded = base64.urlsafe_b64decode(encrypted_code.encode()).decode()
            
            # Split into data and signature
            if '.' not in decoded:
                return False, None
            
            data, signature = decoded.rsplit('.', 1)
            
            # Recreate signature
            secret_key = _cfg.SECRET_KEY.encode('utf-8')
            expected = hmac.new(secret_key, data.encode(), hashlib.sha256).hexdigest()[:16]
            
            # Compare signatures (constant time comparison)
            if hmac.compare_digest(signature, expected):
                return True, data
            
            return False, None
            
        except Exception:
            return False, None
    
    @staticmethod
    def verify_passcode(stored_passcode: str, provided_passcode: str) -> bool:
        """
        Verify if provided passcode matches stored passcode
        Uses constant-time comparison to prevent timing attacks
        """
        if not stored_passcode or not provided_passcode:
            return False
        
        # Normalize (remove hyphens and convert to uppercase for case-insensitive)
        stored = stored_passcode.replace('-', '').upper()
        provided = provided_passcode.replace('-', '').upper()
        
        # Constant time comparison
        return hmac.compare_digest(stored.encode(), provided.encode())
    
    @staticmethod
    def validate_encrypted_code(encrypted_code: str) -> tuple:
        """
        Alias for decrypt_access_code for backward compatibility
        """
        return AccessCodeGenerator.decrypt_access_code(encrypted_code)