import os
import requests
import uuid
import base64
import logging
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger(__name__)

class CustomerIOClient:
    def __init__(self):
        self.api_key = os.getenv("CUSTOMERIO_API_KEY")
        self.base_url = os.getenv("CUSTOMERIO_BASE_URL")
        self.region = os.getenv("CUSTOMERIO_REGION", "US")
        
        # Set base URL - prioritize env var, fallback to region-based URL
        if not self.base_url:
            if self.region.upper() == "EU":
                self.base_url = "https://cdp-eu.customer.io/v1"
            else:
                self.base_url = "https://cdp.customer.io/v1"
        
        # Transactional API URL (App API Key endpoints)
        if self.region.upper() == "EU":
            self.transactional_url = "https://api-eu.customer.io/v1"
        else:
            self.transactional_url = "https://api.customer.io/v1"
        
        # Check if credentials are configured
        self.client = bool(self.api_key and self.base_url)
    
    def get_current_segment_id(self) -> str:
        """Get the appropriate segment ID based on current environment"""
        environment = os.getenv("ENVIRONMENT", "dev").lower()
        
        if environment == "prod":
            segment_id = os.getenv("CUSTOMERIO_PROD_SEGMENT_ID")
        else:
            segment_id = os.getenv("CUSTOMERIO_DEV_SEGMENT_ID")
        
        return segment_id
    
    def add_microgrant_contact(self, email: str, first_name: str = "", last_name: str = "") -> Dict[str, Any]:
        """Add a microgrant contact to Customer.io using Pipelines API"""
        if not self.client:
            return {"success": False, "error": "Customer.io API credentials not configured"}
        
        try:
            # Generate auto-generated userId (GUID without dashes)
            user_id = str(uuid.uuid4()).replace('-', '')
            
            # Create basic auth (API key as username, no password)
            auth_string = f"{self.api_key}:"
            encoded_auth = base64.b64encode(auth_string.encode()).decode()
            
            headers = {
                "Authorization": f"Basic {encoded_auth}",
                "Content-Type": "application/json"
            }
            
            # Build name field - combine first and last name
            name = ""
            if first_name and last_name:
                name = f"{first_name} {last_name}"
            elif first_name:
                name = first_name
            elif last_name:
                name = last_name
            
            # Get current environment
            environment = os.getenv("ENVIRONMENT", "dev")
            
            # Step 1: Identify the user with correct format
            identify_payload = {
                "userId": user_id,
                "traits": {
                    "email": email,
                    "microgrant_waitlist_signup": environment
                }
            }
            
            # Add name if provided
            if name:
                identify_payload["traits"]["name"] = name
            
            logger.info(f"Customer.io Pipelines: Identifying microgrant user {user_id} ({email}) with traits: {identify_payload['traits']}")
            
            # Send identify request
            identify_response = requests.post(
                f"{self.base_url}/identify",
                json=identify_payload,
                headers=headers,
                timeout=10
            )
            
            if not identify_response.ok:
                logger.error(f"Customer.io microgrant identify failed: {identify_response.status_code} - {identify_response.text}")
                return {"success": False, "error": f"Failed to identify user: {identify_response.status_code}"}
            
            # Step 2: Track the microgrant waitlist signup event
            track_payload = {
                "userId": user_id,
                "event": "microgrant_waitlist_signup",
                "properties": {
                    "source": "microgrant_waitlist_api",
                    "email": email,
                    "microgrant_waitlist_signup": environment
                }
            }
            
            logger.info(f"Customer.io Pipelines: Tracking event 'microgrant_waitlist_signup' for {user_id} ({email})")
            
            # Send track request
            track_response = requests.post(
                f"{self.base_url}/track",
                json=track_payload,
                headers=headers,
                timeout=10
            )
            
            if not track_response.ok:
                logger.error(f"Customer.io microgrant track failed: {track_response.status_code} - {track_response.text}")
                return {"success": False, "error": f"Failed to track event: {track_response.status_code}"}
            
            logger.info(f"Customer.io Pipelines: Successfully processed microgrant user {user_id} ({email})")
            
            # Get current environment segment ID
            segment_id = self.get_current_segment_id()
            if segment_id:
                logger.info(f"Customer.io: Microgrant contact will be automatically added to {environment} segment (ID: {segment_id})")
                return {"success": True, "message": f"Microgrant contact added to Customer.io ({environment} environment, auto-segmentation enabled)"}
            else:
                logger.warning(f"Customer.io: No segment ID configured for {environment} environment")
                return {"success": True, "message": f"Microgrant contact added to Customer.io ({environment} environment, no segment configured)"}
            
        except Exception as e:
            # Log the full error for debugging
            logger.error(f"Customer.io Pipelines microgrant error: {type(e).__name__}: {str(e)}", exc_info=True)
            return {"success": False, "error": f"Customer.io error: {str(e)}"}
    
    def add_contact(self, email: str, first_name: str = "", last_name: str = "", variant: str = "A") -> Dict[str, Any]:
        """Add a contact to Customer.io using Pipelines API with correct format"""
        if not self.client:
            return {"success": False, "error": "Customer.io API credentials not configured"}
        
        try:
            # Generate auto-generated userId (GUID without dashes)
            user_id = str(uuid.uuid4()).replace('-', '')
            
            # Create basic auth (API key as username, no password)
            auth_string = f"{self.api_key}:"
            encoded_auth = base64.b64encode(auth_string.encode()).decode()
            
            headers = {
                "Authorization": f"Basic {encoded_auth}",
                "Content-Type": "application/json"
            }
            
            # Build name field - combine first and last name
            name = ""
            if first_name and last_name:
                name = f"{first_name} {last_name}"
            elif first_name:
                name = first_name
            elif last_name:
                name = last_name
            
            # Get current environment
            environment = os.getenv("ENVIRONMENT", "dev")
            
            # Step 1: Identify the user with correct format
            identify_payload = {
                "userId": user_id,
                "traits": {
                    "email": email,
                    "variant": variant,
                    "waitlist_signup": environment
                }
            }
            
            # Add name if provided
            if name:
                identify_payload["traits"]["name"] = name
            
            logger.info(f"Customer.io Pipelines: Identifying user {user_id} ({email}) with traits: {identify_payload['traits']}")
            
            # Send identify request
            identify_response = requests.post(
                f"{self.base_url}/identify",
                json=identify_payload,
                headers=headers,
                timeout=10
            )
            
            if not identify_response.ok:
                logger.error(f"Customer.io identify failed: {identify_response.status_code} - {identify_response.text}")
                return {"success": False, "error": f"Failed to identify user: {identify_response.status_code}"}
            
            # Step 2: Track the waitlist signup event
            track_payload = {
                "userId": user_id,
                "event": "waitlist_signup",
                "properties": {
                    "variant": variant,
                    "source": "waitlist_api",
                    "email": email,
                    "waitlist_signup": environment
                }
            }
            
            logger.info(f"Customer.io Pipelines: Tracking event 'waitlist_signup' for {user_id} ({email})")
            
            # Send track request
            track_response = requests.post(
                f"{self.base_url}/track",
                json=track_payload,
                headers=headers,
                timeout=10
            )
            
            if not track_response.ok:
                logger.error(f"Customer.io track failed: {track_response.status_code} - {track_response.text}")
                return {"success": False, "error": f"Failed to track event: {track_response.status_code}"}
            
            logger.info(f"Customer.io Pipelines: Successfully processed {user_id} ({email})")
            
            # Get current environment segment ID
            segment_id = self.get_current_segment_id()
            if segment_id:
                logger.info(f"Customer.io: Contact will be automatically added to {environment} segment (ID: {segment_id})")
                return {"success": True, "message": f"Contact added to Customer.io ({environment} environment, auto-segmentation enabled)"}
            else:
                logger.warning(f"Customer.io: No segment ID configured for {environment} environment")
                return {"success": True, "message": f"Contact added to Customer.io ({environment} environment, no segment configured)"}
            
        except Exception as e:
            # Log the full error for debugging
            logger.error(f"Customer.io Pipelines error: {type(e).__name__}: {str(e)}", exc_info=True)
            return {"success": False, "error": f"Customer.io error: {str(e)}"}
    

    def mark_signup_confirmed(self, email: str, name: str = "") -> Dict[str, Any]:
        """Mark signup as confirmed in Customer.io by updating user attributes"""
        if not self.client:
            return {"success": False, "error": "Customer.io API credentials not configured"}
        
        try:
            # Generate user ID for this email (could be improved by using actual user ID)
            user_id = str(uuid.uuid4()).replace('-', '')
            environment = os.getenv("ENVIRONMENT", "dev").lower()
            
            # Create basic auth (API key as username, no password)
            auth_string = f"{self.api_key}:"
            encoded_auth = base64.b64encode(auth_string.encode()).decode()
            
            headers = {
                "Authorization": f"Basic {encoded_auth}",
                "Content-Type": "application/json"
            }
            
            # Update user attributes to mark signup as confirmed
            identify_payload = {
                "userId": user_id,
                "traits": {
                    "email": email,
                    "signup_confirmed": True,
                    "signup_confirmed_env": environment
                }
            }
            
            # Add name if provided
            if name:
                identify_payload["traits"]["name"] = name
            
            logger.info(f"Customer.io: Marking signup confirmed for {email} in {environment} environment")
            
            # Send identify request to update user attributes
            identify_response = requests.post(
                f"{self.base_url}/identify",
                json=identify_payload,
                headers=headers,
                timeout=10
            )
            
            if not identify_response.ok:
                logger.error(f"Customer.io signup confirmation update failed: {identify_response.status_code} - {identify_response.text}")
                return {"success": False, "error": f"Failed to update signup confirmation: {identify_response.status_code}"}
            
            logger.info(f"Customer.io: Successfully marked signup confirmed for {email}")
            
            return {
                "success": True,
                "message": f"Signup confirmation updated for {email}"
            }
            
        except Exception as e:
            logger.error(f"Customer.io signup confirmation update error: {type(e).__name__}: {str(e)}", exc_info=True)
            return {"success": False, "error": f"Customer.io update error: {str(e)}"}
    
    def send_transactional_email(self, message_id: str, email: str, message_data: Dict = None) -> Dict[str, Any]:
        """Send transactional email using Customer.io Transactional API"""
        if not self.client:
            return {"success": False, "error": "Customer.io API credentials not configured"}
        
        try:
            # Use Bearer token authentication for App API Key
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            # Transactional email payload
            payload = {
                "to": email,
                "transactional_message_id": message_id,
                "identifiers": {
                    "email": email
                },
                "message_data": message_data or {}
            }
            
            logger.info(f"Customer.io: Sending transactional email '{message_id}' to {email}")
            logger.info(f"Customer.io: Full payload: {payload}")
            
            # Send transactional email request
            response = requests.post(
                f"{self.transactional_url}/send/email",
                json=payload,
                headers=headers,
                timeout=10
            )
            
            if response.ok:
                logger.info(f"Customer.io: Successfully sent '{message_id}' to {email}")
                return {"success": True, "message": f"Transactional email '{message_id}' sent to {email}"}
            else:
                logger.error(f"Customer.io transactional email failed: {response.status_code} - {response.text}")
                return {"success": False, "error": f"Failed to send transactional email: {response.status_code}"}
            
        except Exception as e:
            logger.error(f"Customer.io transactional email error: {type(e).__name__}: {str(e)}", exc_info=True)
            return {"success": False, "error": f"Transactional email error: {str(e)}"}
    
    def add_to_segment(self, email: str, segment_name: str, user_data: Dict = None) -> Dict[str, Any]:
        """Add user to a Customer.io segment"""
        if not self.client:
            return {"success": False, "error": "Customer.io API credentials not configured"}
        
        try:
            # Generate user ID for this email
            user_id = str(uuid.uuid4()).replace('-', '')
            environment = os.getenv("ENVIRONMENT", "dev").lower()
            
            # Create basic auth (API key as username, no password)
            auth_string = f"{self.api_key}:"
            encoded_auth = base64.b64encode(auth_string.encode()).decode()
            
            headers = {
                "Authorization": f"Basic {encoded_auth}",
                "Content-Type": "application/json"
            }
            
            # Identify user with segment flag
            identify_payload = {
                "userId": user_id,
                "traits": {
                    "email": email,
                    f"segment_{segment_name}": True,
                    f"added_to_{segment_name}_at": datetime.now().isoformat(),
                    "environment": environment,
                    **(user_data or {})
                }
            }
            
            logger.info(f"Customer.io: Adding {email} to segment '{segment_name}'")
            
            # Send identify request with segment flag
            response = requests.post(
                f"{self.base_url}/identify",
                json=identify_payload,
                headers=headers,
                timeout=10
            )
            
            if response.ok:
                logger.info(f"Customer.io: Successfully added {email} to segment '{segment_name}'")
                return {"success": True, "message": f"Added {email} to segment '{segment_name}'"}
            else:
                logger.error(f"Customer.io segment addition failed: {response.status_code} - {response.text}")
                return {"success": False, "error": f"Failed to add to segment: {response.status_code}"}
            
        except Exception as e:
            logger.error(f"Customer.io segment addition error: {type(e).__name__}: {str(e)}", exc_info=True)
            return {"success": False, "error": f"Segment addition error: {str(e)}"}
    
    # Specific transactional email methods
    def send_signup_confirmation_transactional(self, email: str, name: str = "", magic_link_url: str = "", verification_code: str = "") -> Dict[str, Any]:
        """Send signup confirmation using transactional email"""
        message_id = os.getenv("CUSTOMERIO_SIGNUP_CONFIRMATION_MESSAGE_ID", "signup_confirmation")
        message_data = {
            "customer": {
                "name": name,
                "magic_link_url": magic_link_url,
                "verification_code": verification_code
            },
            # Also send flat structure in case template expects it differently
            "name": name,
            "magic_link_url": magic_link_url,
            "verification_code": verification_code,
            # Debug: Send simple test data
            "test_message": f"DEBUG: Data received - Name: {name}, Code: {verification_code}"
        }
        return self.send_transactional_email(message_id, email, message_data)
    
    def send_signup_reminder_transactional(self, email: str, name: str = "", magic_link_url: str = "") -> Dict[str, Any]:
        """Send signup reminder using transactional email"""
        message_id = os.getenv("CUSTOMERIO_SIGNUP_REMINDER_MESSAGE_ID", "signup_reminder")
        message_data = {
            "email": email,
            "name": name,
            "magic_link_url": magic_link_url
        }
        return self.send_transactional_email(message_id, email, message_data)
    
    def send_signin_transactional(self, email: str, name: str = "", magic_link_url: str = "", verification_code: str = "") -> Dict[str, Any]:
        """Send signin link and verification code using transactional email"""
        message_id = os.getenv("CUSTOMERIO_SIGNIN_MESSAGE_ID", "signin")
        message_data = {
            "email": email,
            "name": name,
            "magic_link_url": magic_link_url,
            "verification_code": verification_code
        }
        return self.send_transactional_email(message_id, email, message_data)
    
    def send_podcast_claim_intent_transactional(self, email: str, name: str = "", podcast_title: str = "", verification_code: str = "") -> Dict[str, Any]:
        """Send podcast claim intent confirmation using transactional email"""
        message_id = os.getenv("CUSTOMERIO_PODCAST_CLAIM_INTENT_MESSAGE_ID", "podcast_claim_intent")
        message_data = {
            "email": email,
            "name": name,
            "podcast_title": podcast_title,
            "verification_code": verification_code
        }
        return self.send_transactional_email(message_id, email, message_data)
    
    def send_podcast_claim_intent_reminder_transactional(self, email: str, name: str = "", podcast_title: str = "", verification_code: str = "") -> Dict[str, Any]:
        """Send podcast claim intent reminder using transactional email"""
        message_id = os.getenv("CUSTOMERIO_PODCAST_CLAIM_INTENT_REMINDER_MESSAGE_ID", "podcast_claim_intent_reminder")
        message_data = {
            "email": email,
            "name": name,
            "podcast_title": podcast_title,
            "verification_code": verification_code
        }
        return self.send_transactional_email(message_id, email, message_data)
    
    
    def send_podcast_claim_success_transactional(self, email: str, name: str = "", podcast_title: str = "") -> Dict[str, Any]:
        """Send podcast claim success notification using transactional email"""
        message_id = os.getenv("CUSTOMERIO_PODCAST_CLAIM_SUCCESS_MESSAGE_ID", "podcast_claim_success")
        message_data = {
            "email": email,
            "name": name,
            "podcast_title": podcast_title
        }
        return self.send_transactional_email(message_id, email, message_data)
    
    def send_podcast_claim_login_reminder_transactional(self, email: str, name: str = "", podcast_title: str = "", magic_link_url: str = "") -> Dict[str, Any]:
        """Send podcast claim login reminder to user with magic link to restart claim process"""
        message_id = os.getenv("CUSTOMERIO_PODCAST_CLAIM_LOGIN_REMINDER_MESSAGE_ID", "podcast_claim_login_reminder")
        message_data = {
            "email": email,
            "name": name,
            "podcast_title": podcast_title,
            "magic_link_url": magic_link_url
        }
        return self.send_transactional_email(message_id, email, message_data)
    
