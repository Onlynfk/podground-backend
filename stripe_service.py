"""
Stripe Service
Handles all Stripe API interactions for subscription management.
"""
import stripe
import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class StripeService:
    """Service for interacting with Stripe API"""

    def __init__(self):
        """Initialize Stripe with API key"""
        self.secret_key = os.getenv("STRIPE_SECRET_KEY")
        if not self.secret_key:
            logger.warning("STRIPE_SECRET_KEY not set - Stripe features will not work")
            return

        stripe.api_key = self.secret_key
        self.webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

        # Price IDs for subscription plans
        self.pro_monthly_price_id = os.getenv("STRIPE_PRICE_ID_PRO_MONTHLY")
        self.lifetime_price_id = os.getenv("STRIPE_PRICE_ID_LIFETIME")

        # Success/Cancel URLs
        self.success_url = os.getenv("STRIPE_SUCCESS_URL", "https://app.podground.io/subscription/success")
        self.cancel_url = os.getenv("STRIPE_CANCEL_URL", "https://app.podground.io/subscription/canceled")

        logger.info("Stripe service initialized")

    def get_or_create_customer(self, user_id: str, email: str, name: Optional[str] = None) -> Optional[str]:
        """
        Get existing Stripe customer or create a new one.

        Args:
            user_id: Internal user ID
            email: User's email address
            name: User's name (optional)

        Returns:
            Stripe customer ID or None on error
        """
        try:
            # Search for existing customer by email
            customers = stripe.Customer.list(email=email, limit=1)

            if customers.data:
                customer_id = customers.data[0].id
                logger.info(f"Found existing Stripe customer: {customer_id} for email {email}")
                return customer_id

            # Create new customer
            customer_data = {
                "email": email,
                "metadata": {
                    "user_id": user_id
                }
            }

            if name:
                customer_data["name"] = name

            customer = stripe.Customer.create(**customer_data)
            logger.info(f"Created new Stripe customer: {customer.id} for user {user_id}")
            return customer.id

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating/getting customer: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error creating/getting Stripe customer: {str(e)}")
            return None

    def create_checkout_session(
        self,
        customer_id: str,
        price_id: str,
        user_id: str,
        mode: str = "subscription",
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Create a Stripe Checkout Session for subscription or one-time payment.

        Args:
            customer_id: Stripe customer ID
            price_id: Stripe price ID
            user_id: Internal user ID for metadata
            mode: "subscription" for Pro monthly or "payment" for lifetime
            success_url: Custom success URL (optional)
            cancel_url: Custom cancel URL (optional)

        Returns:
            Dict with session_id and url, or None on error
        """
        try:
            session_data = {
                "customer": customer_id,
                "mode": mode,
                "payment_method_types": ["card"],
                "line_items": [{
                    "price": price_id,
                    "quantity": 1
                }],
                "success_url": success_url or self.success_url,
                "cancel_url": cancel_url or self.cancel_url,
                "metadata": {
                    "user_id": user_id
                },
                "allow_promotion_codes": True,
                "billing_address_collection": "auto"
            }

            # Add subscription-specific data for recurring payments
            if mode == "subscription":
                session_data["subscription_data"] = {
                    "metadata": {
                        "user_id": user_id
                    }
                }
            # Add payment intent data for one-time payments
            elif mode == "payment":
                session_data["payment_intent_data"] = {
                    "metadata": {
                        "user_id": user_id,
                        "plan_type": "lifetime"
                    }
                }

            session = stripe.checkout.Session.create(**session_data)

            logger.info(f"Created {mode} checkout session {session.id} for customer {customer_id}")

            return {
                "session_id": session.id,
                "url": session.url,
                "mode": mode
            }

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating checkout session: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error creating checkout session: {str(e)}")
            return None

    def create_customer_portal_session(
        self,
        customer_id: str,
        return_url: Optional[str] = None
    ) -> Optional[str]:
        """
        Create a Stripe Customer Portal session for subscription management.

        Args:
            customer_id: Stripe customer ID
            return_url: URL to return to after portal session

        Returns:
            Portal session URL or None on error
        """
        try:
            portal_session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url or self.success_url
            )

            logger.info(f"Created portal session for customer {customer_id}")
            return portal_session.url

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating portal session: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error creating portal session: {str(e)}")
            return None

    def retrieve_subscription(self, subscription_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve subscription details from Stripe.

        Args:
            subscription_id: Stripe subscription ID

        Returns:
            Subscription data dict or None on error
        """
        try:
            subscription = stripe.Subscription.retrieve(subscription_id)

            # Convert Stripe object to dict for easier access
            sub_dict = dict(subscription)

            # Get period dates from items (subscription items have the current period)
            items_data = sub_dict.get('items', {}).get('data', [])
            plan_id = None
            current_period_start = None
            current_period_end = None

            if items_data:
                first_item = items_data[0]
                plan_id = first_item.get('price', {}).get('id')
                current_period_start = first_item.get('current_period_start')
                current_period_end = first_item.get('current_period_end')

            return {
                "id": sub_dict['id'],
                "customer": sub_dict['customer'],
                "status": sub_dict['status'],
                "current_period_start": datetime.fromtimestamp(current_period_start, tz=timezone.utc) if current_period_start else None,
                "current_period_end": datetime.fromtimestamp(current_period_end, tz=timezone.utc) if current_period_end else None,
                "cancel_at_period_end": sub_dict['cancel_at_period_end'],
                "canceled_at": datetime.fromtimestamp(sub_dict['canceled_at'], tz=timezone.utc) if sub_dict.get('canceled_at') else None,
                "trial_start": datetime.fromtimestamp(sub_dict['trial_start'], tz=timezone.utc) if sub_dict.get('trial_start') else None,
                "trial_end": datetime.fromtimestamp(sub_dict['trial_end'], tz=timezone.utc) if sub_dict.get('trial_end') else None,
                "plan_id": plan_id,
                "metadata": sub_dict.get('metadata', {})
            }

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error retrieving subscription: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error retrieving subscription: {str(e)}")
            return None

    def verify_webhook_signature(self, payload: bytes, signature: str) -> Optional[Dict[str, Any]]:
        """
        Verify Stripe webhook signature and construct event.

        Args:
            payload: Raw request body bytes
            signature: Stripe signature from header

        Returns:
            Constructed Stripe event or None if verification fails
        """
        if not self.webhook_secret:
            logger.error("STRIPE_WEBHOOK_SECRET not configured")
            return None

        try:
            event = stripe.Webhook.construct_event(
                payload, signature, self.webhook_secret
            )
            return event

        except ValueError as e:
            logger.error(f"Invalid webhook payload: {str(e)}")
            return None
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid webhook signature: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error verifying webhook: {str(e)}")
            return None

    def retrieve_payment_intent(self, payment_intent_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve payment intent details from Stripe (for one-time payments).

        Args:
            payment_intent_id: Stripe payment intent ID

        Returns:
            Payment intent data dict or None on error
        """
        try:
            payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)

            return {
                "id": payment_intent.id,
                "customer": payment_intent.customer,
                "status": payment_intent.status,
                "amount": payment_intent.amount,
                "currency": payment_intent.currency,
                "created": datetime.fromtimestamp(payment_intent.created, tz=timezone.utc),
                "metadata": payment_intent.metadata
            }

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error retrieving payment intent: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error retrieving payment intent: {str(e)}")
            return None

    def cancel_subscription(self, subscription_id: str, cancel_immediately: bool = False) -> bool:
        """
        Cancel a subscription.

        Args:
            subscription_id: Stripe subscription ID
            cancel_immediately: If True, cancel immediately. If False, cancel at period end.

        Returns:
            True if successful, False otherwise
        """
        try:
            if cancel_immediately:
                stripe.Subscription.delete(subscription_id)
                logger.info(f"Immediately canceled subscription {subscription_id}")
            else:
                stripe.Subscription.modify(
                    subscription_id,
                    cancel_at_period_end=True
                )
                logger.info(f"Scheduled subscription {subscription_id} to cancel at period end")

            return True

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error canceling subscription: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Error canceling subscription: {str(e)}")
            return False

    def reactivate_subscription(self, subscription_id: str) -> bool:
        """
        Reactivate a subscription that was set to cancel at period end.

        Args:
            subscription_id: Stripe subscription ID

        Returns:
            True if successful, False otherwise
        """
        try:
            stripe.Subscription.modify(
                subscription_id,
                cancel_at_period_end=False
            )
            logger.info(f"Reactivated subscription {subscription_id}")
            return True

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error reactivating subscription: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Error reactivating subscription: {str(e)}")
            return False
