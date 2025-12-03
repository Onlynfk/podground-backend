"""
User Settings Service
Handles user notification preferences, privacy settings, and related operations
"""
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from fastapi import HTTPException

from supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class UserSettingsService:
    def __init__(self):
        self.supabase_client = get_supabase_client()

    # ==================== Notification Preferences ====================

    async def get_notification_preferences(self, user_id: str) -> Dict[str, Any]:
        """
        Get user's notification preferences
        Creates default preferences if they don't exist
        """
        try:
            result = self.supabase_client.service_client.table("user_notification_preferences").select(
                "*"
            ).eq("user_id", user_id).single().execute()

            if result.data:
                return result.data

            # Create default preferences if they don't exist
            return await self._create_default_notification_preferences(user_id)

        except Exception as e:
            # If no preferences found, create defaults
            if "No rows found" in str(e) or "JSON object requested" in str(e) or "Cannot coerce the result to a single JSON object" in str(e):
                return await self._create_default_notification_preferences(user_id)
            logger.error(f"Error getting notification preferences: {str(e)}")
            raise HTTPException(500, f"Failed to get notification preferences: {str(e)}")

    async def _create_default_notification_preferences(self, user_id: str) -> Dict[str, Any]:
        """Create default notification preferences for a user"""
        try:
            # Check if user exists in auth.users before creating preferences
            try:
                user_check = self.supabase_client.service_client.auth.admin.get_user_by_id(user_id)
                if not user_check:
                    logger.warning(f"User {user_id} does not exist in auth.users, cannot create notification preferences")
                    raise HTTPException(404, "User not found")
            except Exception as check_error:
                logger.warning(f"Could not verify user {user_id} exists: {str(check_error)}")
                raise HTTPException(404, "User not found")

            default_prefs = {
                "user_id": user_id,
                # Activity & Engagement - all default to true
                "new_follower": True,
                "replies_to_comments": True,
                "direct_messages": True,
                # Content Updates - all default to true
                "new_episodes_from_followed_shows": True,
                "recommended_episodes": True,
                # Events & Announcements
                "upcoming_events_and_workshops": True,
                "product_updates_and_new_features": True,
                "promotions_and_partner_deals": False,  # Default to false for marketing
                # Notification Methods - all default to true
                "email_notifications": True,
                "push_notifications": True,
            }

            result = self.supabase_client.service_client.table("user_notification_preferences").insert(
                default_prefs
            ).execute()

            if result.data:
                return result.data[0]
            raise Exception("Failed to create default preferences")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating default notification preferences: {str(e)}")
            raise HTTPException(500, f"Failed to create default preferences: {str(e)}")

    async def update_notification_preferences(
        self,
        user_id: str,
        preferences: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update user's notification preferences"""
        try:
            # Ensure user has preferences first
            await self.get_notification_preferences(user_id)

            # Filter to only allowed fields
            allowed_fields = [
                "new_follower",
                "replies_to_comments",
                "direct_messages",
                "new_episodes_from_followed_shows",
                "recommended_episodes",
                "upcoming_events_and_workshops",
                "product_updates_and_new_features",
                "promotions_and_partner_deals",
                "email_notifications",
                "push_notifications",
            ]

            update_data = {k: v for k, v in preferences.items() if k in allowed_fields}

            if not update_data:
                raise HTTPException(400, "No valid preference fields provided")

            result = self.supabase_client.service_client.table("user_notification_preferences").update(
                update_data
            ).eq("user_id", user_id).execute()

            if result.data:
                return result.data[0]
            raise Exception("Failed to update preferences")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating notification preferences: {str(e)}")
            raise HTTPException(500, f"Failed to update notification preferences: {str(e)}")

    # ==================== Privacy Settings ====================

    async def get_privacy_settings(self, user_id: str) -> Dict[str, Any]:
        """
        Get user's privacy settings
        Creates default settings if they don't exist
        """
        try:
            result = self.supabase_client.service_client.table("user_privacy_settings").select(
                "*"
            ).eq("user_id", user_id).execute()

            if result.data and len(result.data) > 0:
                return result.data[0]

            # Create default settings if they don't exist
            return await self._create_default_privacy_settings(user_id)

        except HTTPException as he:
            # If user not found (deleted user), return safe defaults instead of failing
            if he.status_code == 404:
                logger.warning(f"User {user_id} not found (likely deleted), returning default privacy settings")
                return {
                    "user_id": user_id,
                    "profile_visibility": True,
                    "search_visibility": True,
                    "show_activity_status": True,
                }
            raise
        except Exception as e:
            logger.error(f"Error getting privacy settings: {str(e)}")
            raise HTTPException(500, f"Failed to get privacy settings: {str(e)}")

    async def _create_default_privacy_settings(self, user_id: str) -> Dict[str, Any]:
        """Create default privacy settings for a user"""
        try:
            # Check if user exists in auth.users before creating settings
            try:
                user_check = self.supabase_client.service_client.auth.admin.get_user_by_id(user_id)
                if not user_check:
                    logger.warning(f"User {user_id} does not exist in auth.users, cannot create privacy settings")
                    raise HTTPException(404, "User not found")
            except Exception as check_error:
                logger.warning(f"Could not verify user {user_id} exists: {str(check_error)}")
                raise HTTPException(404, "User not found")

            default_settings = {
                "user_id": user_id,
                "profile_visibility": True,  # Profile visible by default
                "search_visibility": True,   # Searchable by default
                "show_activity_status": True,  # Activity status visible by default
            }

            result = self.supabase_client.service_client.table("user_privacy_settings").insert(
                default_settings
            ).execute()

            if result.data:
                return result.data[0]
            raise Exception("Failed to create default privacy settings")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating default privacy settings: {str(e)}")
            raise HTTPException(500, f"Failed to create default privacy settings: {str(e)}")

    async def update_privacy_settings(
        self,
        user_id: str,
        settings: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update user's privacy settings"""
        try:
            # Ensure user has settings first
            await self.get_privacy_settings(user_id)

            # Filter to only allowed fields
            allowed_fields = [
                "profile_visibility",
                "search_visibility",
                "show_activity_status",
            ]

            update_data = {k: v for k, v in settings.items() if k in allowed_fields}

            if not update_data:
                raise HTTPException(400, "No valid setting fields provided")

            result = self.supabase_client.service_client.table("user_privacy_settings").update(
                update_data
            ).eq("user_id", user_id).execute()

            if result.data:
                return result.data[0]
            raise Exception("Failed to update privacy settings")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating privacy settings: {str(e)}")
            raise HTTPException(500, f"Failed to update privacy settings: {str(e)}")

    # ==================== Helper Methods ====================

    async def can_send_notification(
        self,
        user_id: str,
        notification_type: str,
        method: str = "both"
    ) -> bool:
        """
        Check if a notification can be sent to a user based on their preferences

        Args:
            user_id: User ID to check
            notification_type: Type of notification (e.g., "new_follower", "direct_messages")
            method: "email", "push", or "both" (default)

        Returns:
            True if notification can be sent, False otherwise
        """
        try:
            prefs = await self.get_notification_preferences(user_id)

            # Check if the specific notification type is enabled
            notification_enabled = prefs.get(notification_type, False)
            if not notification_enabled:
                return False

            # Check notification method preferences
            if method == "email":
                return prefs.get("email_notifications", False)
            elif method == "push":
                return prefs.get("push_notifications", False)
            else:  # "both" - need at least one method enabled
                return prefs.get("email_notifications", False) or prefs.get("push_notifications", False)

        except Exception as e:
            logger.error(f"Error checking notification permission: {str(e)}")
            # Fail open - allow notification if we can't check
            return True

    async def is_user_profile_visible(
        self,
        user_id: str,
        requesting_user_id: Optional[str] = None
    ) -> bool:
        """
        Check if a user's profile is visible

        Args:
            user_id: User whose profile to check
            requesting_user_id: User requesting to view the profile (optional)

        Returns:
            True if profile is visible, False otherwise
        """
        try:
            # User can always see their own profile
            if requesting_user_id and user_id == requesting_user_id:
                return True

            settings = await self.get_privacy_settings(user_id)
            return settings.get("profile_visibility", True)

        except HTTPException as he:
            # If user not found (deleted user), return default visibility
            if he.status_code == 404:
                logger.debug(f"User {user_id} not found when checking profile visibility, defaulting to visible")
                return True
            logger.error(f"Error checking profile visibility for user {user_id}: {str(he)}")
            return True
        except Exception as e:
            logger.error(f"Error checking profile visibility for user {user_id} (requested by {requesting_user_id}): {str(e)}")
            # Fail open - show profile if we can't check
            return True

    async def is_user_searchable(self, user_id: str) -> bool:
        """
        Check if a user appears in search results

        Returns:
            True if user should appear in search, False otherwise
        """
        try:
            settings = await self.get_privacy_settings(user_id)
            return settings.get("search_visibility", True)

        except HTTPException as he:
            if he.status_code == 404:
                logger.debug(f"User {user_id} not found when checking search visibility, defaulting to visible")
                return True
            logger.error(f"Error checking search visibility: {str(he)}")
            return True
        except Exception as e:
            logger.error(f"Error checking search visibility: {str(e)}")
            # Fail open - show in search if we can't check
            return True

    async def should_show_activity_status(self, user_id: str) -> bool:
        """
        Check if user's activity status (online/offline) should be shown

        Returns:
            True if activity status should be shown, False otherwise
        """
        try:
            settings = await self.get_privacy_settings(user_id)
            return settings.get("show_activity_status", True)

        except HTTPException as he:
            if he.status_code == 404:
                logger.debug(f"User {user_id} not found when checking activity status visibility, defaulting to visible")
                return True
            logger.error(f"Error checking activity status visibility: {str(he)}")
            return True
        except Exception as e:
            logger.error(f"Error checking activity status visibility: {str(e)}")
            # Fail open - show status if we can't check
            return True

    async def get_all_settings(self, user_id: str) -> Dict[str, Any]:
        """
        Get all settings for a user (notification preferences + privacy settings)

        Returns:
            Dictionary with both notification_preferences and privacy_settings
        """
        try:
            prefs = await self.get_notification_preferences(user_id)
            privacy = await self.get_privacy_settings(user_id)

            return {
                "notification_preferences": prefs,
                "privacy_settings": privacy
            }

        except Exception as e:
            logger.error(f"Error getting all settings: {str(e)}")
            raise HTTPException(500, f"Failed to get user settings: {str(e)}")


# Global instance
_user_settings_service = None


def get_user_settings_service() -> UserSettingsService:
    """Get or create global UserSettingsService instance"""
    global _user_settings_service
    if _user_settings_service is None:
        _user_settings_service = UserSettingsService()
    return _user_settings_service
