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
        # Pipelines API Key (for CDP - waitlist/contact management)
        self.pipelines_api_key = os.getenv("CUSTOMERIO_API_KEY")

        # App API Key (for Transactional emails)
        self.app_api_key = os.getenv("CUSTOMERIO_APP_API_KEY")

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
        self.client = bool(self.pipelines_api_key and self.base_url)
    
    def get_current_segment_id(self) -> str:
        """Get the appropriate segment ID based on current environment"""
        environment = os.getenv("ENVIRONMENT", "dev").lower()
        
        if environment == "prod":
            segment_id = os.getenv("CUSTOMERIO_PROD_SEGMENT_ID")
        else:
            segment_id = os.getenv("CUSTOMERIO_DEV_SEGMENT_ID")
        
        return segment_id
    
    def add_microgrant_contact(self, email: str, first_name: str = "", last_name: str = "", user_id: str = None) -> Dict[str, Any]:
        """Add a microgrant contact to Customer.io using Pipelines API"""
        if not self.client:
            return {"success": False, "error": "Customer.io API credentials not configured"}

        try:
            # Use provided user_id or fall back to email as stable identifier
            if not user_id:
                user_id = email
            
            # Create basic auth (Pipelines API key as username, no password)
            auth_string = f"{self.pipelines_api_key}:"
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

    def add_grant_application_contact(self, email: str, name: str = "", podcast_title: str = "", phone_number: str = None, user_id: str = None) -> Dict[str, Any]:
        """Add a grant application contact to Customer.io using Pipelines API"""
        if not self.client:
            return {"success": False, "error": "Customer.io API credentials not configured"}

        try:
            # Use provided user_id or fall back to email as stable identifier
            if not user_id:
                user_id = email

            # Create basic auth (Pipelines API key as username, no password)
            auth_string = f"{self.pipelines_api_key}:"
            encoded_auth = base64.b64encode(auth_string.encode()).decode()

            headers = {
                "Authorization": f"Basic {encoded_auth}",
                "Content-Type": "application/json"
            }

            # Get current environment
            environment = os.getenv("ENVIRONMENT", "dev")

            # Step 1: Identify the user with grant_submission trait
            identify_payload = {
                "userId": user_id,
                "traits": {
                    "email": email,
                    "grant_submission": environment
                }
            }

            # Add name if provided
            if name:
                identify_payload["traits"]["name"] = name

            # Add podcast title if provided
            if podcast_title:
                identify_payload["traits"]["podcast_title"] = podcast_title

            # Add phone number if provided
            if phone_number:
                identify_payload["traits"]["phone_number"] = phone_number

            logger.info(f"Customer.io Pipelines: Identifying grant application user {user_id} ({email}) with traits: {identify_payload['traits']}")

            # Send identify request
            identify_response = requests.post(
                f"{self.base_url}/identify",
                json=identify_payload,
                headers=headers,
                timeout=10
            )

            if not identify_response.ok:
                logger.error(f"Customer.io grant application identify failed: {identify_response.status_code} - {identify_response.text}")
                return {"success": False, "error": f"Failed to identify user: {identify_response.status_code}"}

            # Step 2: Track the grant application submission event
            track_payload = {
                "userId": user_id,
                "event": "grant_application_submitted",
                "properties": {
                    "source": "grant_application_api",
                    "email": email,
                    "grant_submission": environment,
                    "podcast_title": podcast_title
                }
            }

            logger.info(f"Customer.io Pipelines: Tracking event 'grant_application_submitted' for {user_id} ({email})")

            # Send track request
            track_response = requests.post(
                f"{self.base_url}/track",
                json=track_payload,
                headers=headers,
                timeout=10
            )

            if not track_response.ok:
                logger.error(f"Customer.io grant application track failed: {track_response.status_code} - {track_response.text}")
                return {"success": False, "error": f"Failed to track event: {track_response.status_code}"}

            logger.info(f"Customer.io Pipelines: Successfully processed grant application user {user_id} ({email})")

            # Get current environment segment ID
            segment_id = self.get_current_segment_id()
            if segment_id:
                logger.info(f"Customer.io: Grant application contact will be automatically added to {environment} segment (ID: {segment_id})")
                return {"success": True, "message": f"Grant application contact added to Customer.io ({environment} environment, auto-segmentation enabled)"}
            else:
                logger.warning(f"Customer.io: No segment ID configured for {environment} environment")
                return {"success": True, "message": f"Grant application contact added to Customer.io ({environment} environment, no segment configured)"}

        except Exception as e:
            # Log the full error for debugging
            logger.error(f"Customer.io Pipelines grant application error: {type(e).__name__}: {str(e)}", exc_info=True)
            return {"success": False, "error": f"Customer.io error: {str(e)}"}

    def add_contact(self, email: str, first_name: str = "", last_name: str = "", variant: str = "A", user_id: str = None) -> Dict[str, Any]:
        """Add a contact to Customer.io using Pipelines API with correct format"""
        if not self.client:
            return {"success": False, "error": "Customer.io API credentials not configured"}

        try:
            # Use provided user_id or fall back to email as stable identifier
            if not user_id:
                user_id = email

            # Create basic auth (Pipelines API key as username, no password)
            auth_string = f"{self.pipelines_api_key}:"
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
                    "name": name,
                    "email": email,
                    "variant": variant,
                    "waitlist_signup": environment
                }
            }

            # Add name if provided
            if name:
                identify_payload["traits"]["name"] = name

            logger.info(f"Customer.io Pipelines: Identifying user {user_id} ({email}) with traits: {identify_payload['traits']}")
            logger.info(f"Customer.io: Using base_url={self.base_url}, Pipelines API key={'***' + self.pipelines_api_key[-4:] if self.pipelines_api_key and len(self.pipelines_api_key) > 4 else 'NOT SET'}")

            # Send identify request
            identify_response = requests.post(
                f"{self.base_url}/identify",
                json=identify_payload,
                headers=headers,
                timeout=10
            )

            logger.info(f"Customer.io identify response: {identify_response.status_code}")
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

            logger.info(f"Customer.io track response: {track_response.status_code}")
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
    

    def update_user_attributes(self, user_id: str, email: str, attributes: Dict[str, Any]) -> Dict[str, Any]:
        """Update user attributes in Customer.io using Pipelines API"""
        if not self.client:
            return {"success": False, "error": "Customer.io API credentials not configured"}

        try:
            # Create basic auth (Pipelines API key as username, no password)
            auth_string = f"{self.pipelines_api_key}:"
            encoded_auth = base64.b64encode(auth_string.encode()).decode()

            headers = {
                "Authorization": f"Basic {encoded_auth}",
                "Content-Type": "application/json"
            }

            # Update user attributes
            identify_payload = {
                "userId": user_id,
                "traits": {
                    "email": email,
                    **attributes
                }
            }

            logger.info(f"Customer.io: Updating attributes for {email} with: {attributes}")

            # Send identify request to update user attributes
            identify_response = requests.post(
                f"{self.base_url}/identify",
                json=identify_payload,
                headers=headers,
                timeout=10
            )

            if not identify_response.ok:
                logger.error(f"Customer.io attribute update failed: {identify_response.status_code} - {identify_response.text}")
                return {"success": False, "error": f"Failed to update attributes: {identify_response.status_code}"}

            logger.info(f"Customer.io: Successfully updated attributes for {email}")

            return {
                "success": True,
                "message": f"Attributes updated for {email}"
            }

        except Exception as e:
            logger.error(f"Customer.io attribute update error: {type(e).__name__}: {str(e)}", exc_info=True)
            return {"success": False, "error": f"Customer.io update error: {str(e)}"}

    def mark_signup_confirmed(self, user_id: str, email: str, name: str = "") -> Dict[str, Any]:
        """Mark signup as confirmed in Customer.io by updating user attributes"""
        if not self.client:
            return {"success": False, "error": "Customer.io API credentials not configured"}

        try:
            environment = os.getenv("ENVIRONMENT", "dev").lower()

            # Create basic auth (Pipelines API key as username, no password)
            auth_string = f"{self.pipelines_api_key}:"
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
        if not self.app_api_key:
            return {"success": False, "error": "Customer.io App API Key not configured"}

        try:
            # Use Bearer token authentication for App API Key
            headers = {
                "Authorization": f"Bearer {self.app_api_key}",
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
    
    def send_signup_reminder_transactional(self, email: str, name: str = "", magic_link_url: str = "", verification_code: str = "") -> Dict[str, Any]:
        """Send signup reminder using transactional email"""
        message_id = os.getenv("CUSTOMERIO_SIGNUP_REMINDER_MESSAGE_ID", "signup_reminder")
        message_data = {
            "email": email,
            "name": name,
            "magic_link_url": magic_link_url,
            "verification_code": verification_code
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

    def send_podcast_claim_email_not_found_transactional(self, email: str, name: str = "", rss_update_url: str = "", listennotes_id: str = "") -> Dict[str, Any]:
        """Send email notification when podcast claim fails because email not found on ListenNotes"""
        message_id = os.getenv("CUSTOMERIO_PODCAST_CLAIM_EMAIL_NOT_FOUND_MESSAGE_ID", "podcast_claim_email_not_found")
        message_data = {
            "email": email,
            "name": name,
            "rss_update_url": rss_update_url,
            "listennotes_id": listennotes_id
        }
        return self.send_transactional_email(message_id, email, message_data)

    def send_podcast_email_found_transactional(self, email: str, name: str = "", onboarding_link: str = "") -> Dict[str, Any]:
        """Send email notification when podcast owner's email becomes available on ListenNotes after a refresh request"""
        message_id = os.getenv("CUSTOMERIO_PODCAST_EMAIL_FOUND_MESSAGE_ID", "podcast_email_found")
        message_data = {
            "email": email,
            "name": name,
            "onboarding_link": onboarding_link
        }
        return self.send_transactional_email(message_id, email, message_data)

