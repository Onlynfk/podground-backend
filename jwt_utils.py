import os
import jwt
import requests
import json
from typing import Optional, Dict
from datetime import datetime, timezone
import logging
from cryptography.hazmat.primitives import serialization

logger = logging.getLogger(__name__)

class SupabaseJWTVerifier:
    def __init__(self):
        self.supabase_url = os.getenv("SUPABASE_URL")
        self._jwks_cache = None
        self._jwks_cache_time = None
        self._cache_ttl = 3600  # 1 hour cache
        
    def _get_jwks_url(self) -> str:
        """Get JWKS URL for the Supabase project"""
        if not self.supabase_url:
            raise ValueError("SUPABASE_URL is required")
        return f"{self.supabase_url}/auth/v1/jwks"
    
    def _fetch_jwks(self) -> Optional[Dict]:
        """Fetch JWT signing keys from Supabase"""
        current_time = datetime.now(timezone.utc).timestamp()
        
        # Return cached JWKS if still valid
        if (self._jwks_cache and self._jwks_cache_time and 
            current_time - self._jwks_cache_time < self._cache_ttl):
            return self._jwks_cache
        
        try:
            jwks_url = self._get_jwks_url()
            
            # Add anon key header for Supabase JWKS access
            headers = {}
            anon_key = os.getenv("SUPABASE_ANON_KEY")
            if anon_key:
                headers["apikey"] = anon_key
            
            response = requests.get(jwks_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                jwks_data = response.json()
                self._jwks_cache = jwks_data
                self._jwks_cache_time = current_time
                logger.info("Successfully fetched JWKS from Supabase")
                return jwks_data
            else:
                logger.error(f"Failed to fetch JWKS: HTTP {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching JWKS: {str(e)}")
            return None
    
    def _get_public_key_from_jwks(self, kid: str) -> Optional[str]:
        """Get public key from JWKS for the given key ID"""
        jwks = self._fetch_jwks()
        if not jwks:
            return None
        
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                try:
                    # Convert JWK to PEM format
                    from jwt.algorithms import RSAAlgorithm
                    public_key = RSAAlgorithm.from_jwk(json.dumps(key))
                    pem = public_key.public_key().public_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PublicFormat.SubjectPublicKeyInfo
                    )
                    return pem.decode('utf-8')
                except Exception as e:
                    logger.error(f"Error converting JWK to PEM: {str(e)}")
                    return None
        
        logger.warning(f"Key ID {kid} not found in JWKS")
        return None
    
    
    def verify_token(self, token: str) -> Optional[Dict]:
        """Verify a Supabase JWT token (supports both HS256 and RS256)"""
        if not token:
            return None
            
        try:
            # Get token header to determine algorithm
            unverified_header = jwt.get_unverified_header(token)
            algorithm = unverified_header.get("alg", "").upper()
            
            payload = None
            
            # Handle HMAC tokens (HS256) - use JWT secret
            if algorithm == "HS256":
                jwt_secret = os.getenv("JWT_SECRET_KEY")
                if not jwt_secret:
                    logger.warning("JWT_SECRET_KEY not found for HS256 token verification")
                    return None
                
                payload = jwt.decode(
                    token,
                    jwt_secret,
                    algorithms=["HS256"],
                    options={"verify_exp": True, "verify_aud": False}
                )
                
                logger.debug("Token successfully verified with JWT_SECRET_KEY")
            
            # Handle RSA tokens (RS256) - use JWKS
            elif algorithm == "RS256":
                kid = unverified_header.get("kid")
                if not kid:
                    logger.warning("Token header missing 'kid' field")
                    return None
                
                # Get public key for this key ID
                public_key = self._get_public_key_from_jwks(kid)
                if not public_key:
                    logger.warning(f"No public key found for kid: {kid}")
                    return None
                
                payload = jwt.decode(
                    token,
                    public_key,
                    algorithms=["RS256"],
                    options={"verify_exp": True, "verify_aud": False}
                )
                
                logger.debug("Token successfully verified with JWT Signing Keys")
            
            else:
                logger.warning(f"Unsupported token algorithm: {algorithm}")
                return None
            
            # Verify issuer (for both methods)
            if self.supabase_url and payload:
                expected_iss = f"{self.supabase_url}/auth/v1"
                if payload.get("iss") != expected_iss:
                    logger.warning(f"Invalid issuer: {payload.get('iss')} != {expected_iss}")
                    return None
            
            return payload
            
        except jwt.ExpiredSignatureError:
            logger.warning("Token has expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Token verification error: {str(e)}")
            return None
    
    
    def extract_user_id(self, token: str) -> Optional[str]:
        """Extract user ID from a verified token"""
        payload = self.verify_token(token)
        if payload:
            # Supabase puts user ID in 'sub' claim
            return payload.get("sub")
        return None
    
    def extract_user_email(self, token: str) -> Optional[str]:
        """Extract user email from a verified token"""
        payload = self.verify_token(token)
        if payload:
            return payload.get("email")
        return None
    
    def is_token_valid(self, token: str) -> bool:
        """Check if token is valid without returning payload"""
        return self.verify_token(token) is not None


# Global instance
jwt_verifier = SupabaseJWTVerifier()


def verify_supabase_token(token: str) -> Optional[Dict]:
    """Convenience function to verify a Supabase JWT token"""
    return jwt_verifier.verify_token(token)


def get_user_id_from_token(token: str) -> Optional[str]:
    """Convenience function to extract user ID from token"""
    return jwt_verifier.extract_user_id(token)


def get_user_email_from_token(token: str) -> Optional[str]:
    """Convenience function to extract user email from token"""
    return jwt_verifier.extract_user_email(token)