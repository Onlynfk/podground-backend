"""
Subscription Service
Manages subscription data in the database.
"""
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from supabase_client import SupabaseClient

logger = logging.getLogger(__name__)

class SubscriptionService:
    """Service for managing subscription data in the database"""

    def __init__(self):
        """Initialize with Supabase client"""
        self.supabase_client = SupabaseClient()

    def get_or_create_stripe_customer(self, user_id: str, stripe_customer_id: str, email: str) -> Dict[str, Any]:
        """
        Get or create Stripe customer mapping in database.

        Args:
            user_id: Internal user ID
            stripe_customer_id: Stripe customer ID
            email: User email

        Returns:
            Dict with success status and data/error
        """
        try:
            # Check if mapping exists
            result = self.supabase_client.service_client.table("user_stripe_customers").select(
                "*"
            ).eq("user_id", user_id).execute()

            if result.data:
                logger.info(f"Found existing Stripe customer mapping for user {user_id}")
                return {"success": True, "data": result.data[0]}

            # Create new mapping
            insert_data = {
                "user_id": user_id,
                "stripe_customer_id": stripe_customer_id,
                "email": email
            }

            result = self.supabase_client.service_client.table("user_stripe_customers").insert(
                insert_data
            ).execute()

            if result.data:
                logger.info(f"Created Stripe customer mapping for user {user_id}")
                return {"success": True, "data": result.data[0]}

            return {"success": False, "error": "Failed to create customer mapping"}

        except Exception as e:
            logger.error(f"Error getting/creating Stripe customer mapping: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_stripe_customer_id(self, user_id: str) -> Optional[str]:
        """
        Get Stripe customer ID for a user.

        Args:
            user_id: Internal user ID

        Returns:
            Stripe customer ID or None
        """
        try:
            result = self.supabase_client.service_client.table("user_stripe_customers").select(
                "stripe_customer_id"
            ).eq("user_id", user_id).single().execute()

            if result.data:
                return result.data["stripe_customer_id"]

            return None

        except Exception as e:
            logger.error(f"Error getting Stripe customer ID: {str(e)}")
            return None

    def create_subscription(self, subscription_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new subscription record (recurring or lifetime).

        Args:
            subscription_data: Subscription data dict with keys:
                - user_id
                - stripe_subscription_id (for recurring) or payment_intent_id (for lifetime)
                - stripe_customer_id
                - status
                - plan_id
                - subscription_type ('recurring' or 'lifetime')
                - lifetime_access (boolean, for lifetime)
                - current_period_start (for recurring)
                - current_period_end (for recurring)
                - cancel_at_period_end (optional, for recurring)
                - canceled_at (optional)
                - trial_start (optional)
                - trial_end (optional)

        Returns:
            Dict with success status and data/error
        """
        try:
            # For recurring subscriptions, check by stripe_subscription_id
            if subscription_data.get("subscription_type") == "recurring":
                existing = self.supabase_client.service_client.table("subscriptions").select(
                    "id"
                ).eq("stripe_subscription_id", subscription_data["stripe_subscription_id"]).execute()

                if existing.data:
                    logger.warning(f"Subscription {subscription_data['stripe_subscription_id']} already exists")
                    return self.update_subscription(
                        subscription_data["stripe_subscription_id"],
                        subscription_data
                    )

            # For lifetime, check by user_id and lifetime_access
            elif subscription_data.get("subscription_type") == "lifetime":
                existing = self.supabase_client.service_client.table("subscriptions").select(
                    "id"
                ).eq("user_id", subscription_data["user_id"]).eq("lifetime_access", True).execute()

                if existing.data:
                    logger.warning(f"User {subscription_data['user_id']} already has lifetime access")
                    return {"success": False, "error": "User already has lifetime access"}

            result = self.supabase_client.service_client.table("subscriptions").insert(
                subscription_data
            ).execute()

            if result.data:
                sub_type = subscription_data.get('subscription_type', 'recurring')
                logger.info(f"Created {sub_type} subscription for user {subscription_data['user_id']}")
                return {"success": True, "data": result.data[0]}

            return {"success": False, "error": "Failed to create subscription"}

        except Exception as e:
            logger.error(f"Error creating subscription: {str(e)}")
            return {"success": False, "error": str(e)}

    def update_subscription(self, stripe_subscription_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update an existing subscription.

        Args:
            stripe_subscription_id: Stripe subscription ID
            update_data: Dict of fields to update

        Returns:
            Dict with success status and data/error
        """
        try:
            # Remove fields that shouldn't be updated
            update_fields = {k: v for k, v in update_data.items() if k not in ["id", "created_at", "stripe_subscription_id"]}

            result = self.supabase_client.service_client.table("subscriptions").update(
                update_fields
            ).eq("stripe_subscription_id", stripe_subscription_id).execute()

            if result.data:
                logger.info(f"Updated subscription {stripe_subscription_id}")
                return {"success": True, "data": result.data[0]}

            return {"success": False, "error": "Subscription not found"}

        except Exception as e:
            logger.error(f"Error updating subscription: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_user_subscription(self, user_id: str) -> Dict[str, Any]:
        """
        Get active subscription for a user.

        Args:
            user_id: Internal user ID

        Returns:
            Dict with success status and subscription data/error
        """
        try:
            result = self.supabase_client.service_client.table("subscriptions").select(
                "*"
            ).eq("user_id", user_id).order("created_at", desc=True).limit(1).execute()

            if result.data:
                return {"success": True, "data": result.data[0]}

            return {"success": True, "data": None}

        except Exception as e:
            logger.error(f"Error getting user subscription: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_subscription_by_stripe_id(self, stripe_subscription_id: str) -> Dict[str, Any]:
        """
        Get subscription by Stripe subscription ID.

        Args:
            stripe_subscription_id: Stripe subscription ID

        Returns:
            Dict with success status and subscription data/error
        """
        try:
            result = self.supabase_client.service_client.table("subscriptions").select(
                "*"
            ).eq("stripe_subscription_id", stripe_subscription_id).single().execute()

            if result.data:
                return {"success": True, "data": result.data}

            return {"success": False, "error": "Subscription not found"}

        except Exception as e:
            logger.error(f"Error getting subscription by Stripe ID: {str(e)}")
            return {"success": False, "error": str(e)}

    def delete_subscription(self, stripe_subscription_id: str) -> Dict[str, Any]:
        """
        Delete a subscription record (when subscription is permanently deleted).

        Args:
            stripe_subscription_id: Stripe subscription ID

        Returns:
            Dict with success status
        """
        try:
            # Instead of deleting, mark as canceled
            result = self.supabase_client.service_client.table("subscriptions").update({
                "status": "canceled",
                "canceled_at": datetime.now(timezone.utc).isoformat()
            }).eq("stripe_subscription_id", stripe_subscription_id).execute()

            if result.data:
                logger.info(f"Marked subscription {stripe_subscription_id} as canceled")
                return {"success": True}

            return {"success": False, "error": "Subscription not found"}

        except Exception as e:
            logger.error(f"Error deleting subscription: {str(e)}")
            return {"success": False, "error": str(e)}

    def has_active_subscription(self, user_id: str) -> bool:
        """
        Check if user has an active subscription (recurring Pro or lifetime).

        Args:
            user_id: Internal user ID

        Returns:
            True if user has active subscription or lifetime access, False otherwise
        """
        try:
            result = self.supabase_client.service_client.table("subscriptions").select(
                "status, current_period_end, lifetime_access, subscription_type"
            ).eq("user_id", user_id).execute()

            if not result.data:
                return False

            # Check for active subscription
            now = datetime.now(timezone.utc)
            for subscription in result.data:
                status = subscription.get("status")
                period_end = subscription.get("current_period_end")
                lifetime_access = subscription.get("lifetime_access", False)
                sub_type = subscription.get("subscription_type", "recurring")

                # Lifetime access is always active
                if lifetime_access or status == "lifetime_active":
                    return True

                # For recurring subscriptions, check active statuses
                if sub_type == "recurring" and status in ["active", "trialing"]:
                    # Check if not expired
                    if period_end:
                        period_end_dt = datetime.fromisoformat(period_end.replace("Z", "+00:00"))
                        if period_end_dt > now:
                            return True

            return False

        except Exception as e:
            logger.error(f"Error checking active subscription: {str(e)}")
            return False

    def get_user_by_stripe_customer_id(self, stripe_customer_id: str) -> Optional[str]:
        """
        Get user ID from Stripe customer ID.

        Args:
            stripe_customer_id: Stripe customer ID

        Returns:
            User ID or None
        """
        try:
            result = self.supabase_client.service_client.table("user_stripe_customers").select(
                "user_id"
            ).eq("stripe_customer_id", stripe_customer_id).single().execute()

            if result.data:
                return result.data["user_id"]

            return None

        except Exception as e:
            logger.error(f"Error getting user by Stripe customer ID: {str(e)}")
            return None

    def get_all_subscriptions(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all subscriptions, optionally filtered by status.

        Args:
            status: Filter by subscription status (optional)

        Returns:
            List of subscription dicts
        """
        try:
            query = self.supabase_client.service_client.table("subscriptions").select("*")

            if status:
                query = query.eq("status", status)

            result = query.execute()

            return result.data if result.data else []

        except Exception as e:
            logger.error(f"Error getting all subscriptions: {str(e)}")
            return []
