"""
Email Notification Service
Handles sending of email notifications via Customer.io with daily rate limiting
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Any
from supabase_client import get_supabase_client
from customerio_client import CustomerIOClient

logger = logging.getLogger(__name__)

# Notification type constants
NOTIFICATION_TYPE_POST_REPLY = "post_reply"
NOTIFICATION_TYPE_POST_REACTION = "post_reaction"
NOTIFICATION_TYPE_NEW_MESSAGE = "new_message"
NOTIFICATION_TYPE_CONNECTION_REQUEST = "connection_request"
NOTIFICATION_TYPE_PODCAST_FOLLOW = "podcast_follow"
NOTIFICATION_TYPE_PODCAST_LISTEN = "podcast_listen"

# Template ID mapping (from environment variables)
TEMPLATE_ID_MAP = {
    NOTIFICATION_TYPE_POST_REPLY: "CUSTOMERIO_TEMPLATE_POST_REPLY",
    NOTIFICATION_TYPE_POST_REACTION: "CUSTOMERIO_TEMPLATE_POST_REACTION",
    NOTIFICATION_TYPE_NEW_MESSAGE: "CUSTOMERIO_TEMPLATE_NEW_MESSAGE",
    NOTIFICATION_TYPE_CONNECTION_REQUEST: "CUSTOMERIO_TEMPLATE_CONNECTION_REQUEST",
    NOTIFICATION_TYPE_PODCAST_FOLLOW: "CUSTOMERIO_TEMPLATE_PODCAST_FOLLOW",
    NOTIFICATION_TYPE_PODCAST_LISTEN: "CUSTOMERIO_TEMPLATE_PODCAST_LISTEN",
}


class EmailNotificationService:
    def __init__(self):
        self.supabase = get_supabase_client()
        self.customerio = CustomerIOClient()
        self.enabled = os.getenv("ACTIVITY_EMAIL_NOTIFICATIONS_ENABLED", "false").lower() == "true"
        self.frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
        self.daily_limit = int(os.getenv("ACTIVITY_EMAIL_NOTIFICATION_DAILY_LIMIT", "10"))

        if not self.enabled:
            logger.info("Activity email notifications are DISABLED (ACTIVITY_EMAIL_NOTIFICATIONS_ENABLED=false)")
        else:
            logger.info(f"Activity email notifications ENABLED with daily limit of {self.daily_limit} emails per user")

    def get_emails_sent_today(self, user_id: str) -> int:
        """
        Get count of emails sent to user in the last 24 hours

        Args:
            user_id: User ID

        Returns:
            Count of emails sent in last 24 hours
        """
        try:
            # Calculate 24 hours ago
            twenty_four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=24)

            # Query email_notification_log for emails sent in last 24 hours
            result = self.supabase.service_client.table("email_notification_log").select(
                "notification_count"
            ).eq("user_id", user_id).gte("sent_at", twenty_four_hours_ago.isoformat()).execute()

            # Sum up all notification counts
            total_sent = sum(record.get("notification_count", 0) for record in (result.data or []))

            logger.debug(f"User {user_id[:8]}... has received {total_sent} emails in last 24 hours")
            return total_sent

        except Exception as e:
            logger.error(f"Error getting emails sent today for user {user_id}: {str(e)}", exc_info=True)
            return 0

    def can_send_email(self, user_id: str) -> bool:
        """
        Check if user can receive another email based on daily limit

        Args:
            user_id: User ID

        Returns:
            True if user can receive email, False if limit reached
        """
        emails_sent_today = self.get_emails_sent_today(user_id)
        can_send = emails_sent_today < self.daily_limit

        if not can_send:
            logger.info(f"Daily email limit reached for user {user_id[:8]}... ({emails_sent_today}/{self.daily_limit})")

        return can_send

    async def send_notification_email(
        self,
        user_id: str,
        notification_type: str,
        actor_id: Optional[str] = None,
        resource_id: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Send notification email immediately (called as background task)

        Args:
            user_id: User who will receive the notification
            notification_type: Type of notification (post_reply, post_reaction, etc.)
            actor_id: User who triggered the notification (optional)
            resource_id: ID of the post, message, podcast, etc. (optional)
            metadata: Additional data (optional)

        Returns:
            Dict with success status and details
        """
        if not self.enabled:
            logger.debug(f"Skipping notification email (disabled): {notification_type} for user {user_id}")
            return {"success": False, "error": "Email notifications disabled"}

        try:
            # Validate notification type
            if notification_type not in TEMPLATE_ID_MAP:
                logger.error(f"Invalid notification type: {notification_type}")
                return {"success": False, "error": f"Invalid notification type: {notification_type}"}

            # Check daily limit
            if not self.can_send_email(user_id):
                logger.info(f"Skipping {notification_type} email for user {user_id[:8]}... - daily limit reached")
                return {"success": False, "error": "Daily email limit reached", "limit_reached": True}

            # Get template ID from environment
            template_env_var = TEMPLATE_ID_MAP.get(notification_type)
            if not template_env_var:
                logger.error(f"No template mapping for {notification_type}")
                return {"success": False, "error": "No template mapping"}

            template_id = os.getenv(template_env_var)
            if not template_id:
                logger.warning(f"Template ID not configured: {template_env_var}")
                return {"success": False, "error": "Template ID not configured"}

            # Get user email from Supabase auth
            try:
                user_data = self.supabase.service_client.auth.admin.get_user_by_id(user_id)
                if not user_data or not hasattr(user_data, 'user') or not user_data.user:
                    logger.error(f"User {user_id} not found in auth")
                    return {"success": False, "error": "User not found"}

                user_email = user_data.user.email

                if not user_email:
                    logger.error(f"User {user_id} has no email")
                    return {"success": False, "error": "User has no email"}

            except Exception as auth_error:
                logger.error(f"Failed to get user {user_id} from auth: {str(auth_error)}")
                return {"success": False, "error": "Failed to get user email"}

            # Get first name from user_profiles table
            profile_result = self.supabase.service_client.table("user_profiles").select(
                "first_name"
            ).eq("user_id", user_id).single().execute()

            first_name = ""
            if profile_result.data:
                first_name = profile_result.data.get("first_name", "")

            # Prepare message data with name and magic link
            # Different URLs based on notification type
            if notification_type == NOTIFICATION_TYPE_NEW_MESSAGE:
                magic_link_url = f"{self.frontend_url}/messages"
            elif notification_type == NOTIFICATION_TYPE_CONNECTION_REQUEST:
                magic_link_url = f"{self.frontend_url}/home/network"
            else:
                magic_link_url = f"{self.frontend_url}/home/my-feed"

            message_data = {
                "name": first_name,
                "magic_link_url": magic_link_url
            }

            # Send via Customer.io
            logger.info(f"Sending {notification_type} email to {user_email}")

            response = self.customerio.send_transactional_email(
                message_id=template_id,
                email=user_email,
                message_data=message_data
            )

            if response.get("success"):
                logger.info(f"Successfully sent {notification_type} email to {user_email}")

                # Log the email in email_notification_log
                self.supabase.service_client.table("email_notification_log").insert({
                    "user_id": user_id,
                    "notification_count": 1,
                    "notification_types": {notification_type: 1},
                    "customer_io_response": response
                }).execute()

                return {
                    "success": True,
                    "notification_type": notification_type,
                    "email": user_email
                }
            else:
                logger.error(f"Failed to send {notification_type} email: {response.get('error')}")
                return {"success": False, "error": response.get("error")}

        except Exception as e:
            logger.error(f"Error sending notification email: {str(e)}", exc_info=True)
            return {"success": False, "error": str(e)}


# Singleton instance
_email_notification_service = None


def get_email_notification_service() -> EmailNotificationService:
    """Get singleton instance of EmailNotificationService"""
    global _email_notification_service
    if _email_notification_service is None:
        _email_notification_service = EmailNotificationService()
    return _email_notification_service
