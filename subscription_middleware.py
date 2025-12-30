"""
Subscription Middleware
Provides decorators and utilities for protecting premium routes.
"""
import logging
from functools import wraps
from fastapi import HTTPException, Request
from subscription_service import SubscriptionService

logger = logging.getLogger(__name__)

def require_active_subscription(func):
    """
    Decorator to protect routes that require an active subscription.

    Usage:
        @app.get("/api/v1/premium/feature")
        @require_active_subscription
        async def premium_feature(request: Request):
            ...

    The decorator will:
    - Check if user is authenticated
    - Check if user has an active subscription
    - Raise 403 Forbidden if no active subscription
    - Raise 402 Payment Required if subscription expired/canceled
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Extract request from args or kwargs
        request = None
        for arg in args:
            if isinstance(arg, Request):
                request = arg
                break
        if not request and "request" in kwargs:
            request = kwargs["request"]

        if not request:
            logger.error("@require_active_subscription: No request object found")
            raise HTTPException(
                status_code=500,
                detail="Internal server error: Missing request object"
            )

        # Check if user is authenticated
        user_id = request.session.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="Authentication required"
            )

        # Check subscription status
        subscription_service = SubscriptionService()
        has_active = subscription_service.has_active_subscription(user_id)

        if not has_active:
            logger.warning(f"User {user_id} attempted to access premium feature without active subscription")
            raise HTTPException(
                status_code=402,
                detail="Active subscription required. Please subscribe to access this feature."
            )

        # User has active subscription, proceed with request
        return await func(*args, **kwargs)

    return wrapper


def check_subscription_status(user_id: str) -> dict:
    """
    Helper function to check subscription status for a user.

    Args:
        user_id: Internal user ID

    Returns:
        Dict with:
            - has_subscription: bool
            - status: str (if has subscription)
            - details: dict (full subscription data)
    """
    subscription_service = SubscriptionService()

    result = subscription_service.get_user_subscription(user_id)

    if not result["success"] or not result.get("data"):
        return {
            "has_subscription": False,
            "status": None,
            "details": None
        }

    subscription_data = result["data"]
    has_active = subscription_service.has_active_subscription(user_id)

    return {
        "has_subscription": True,
        "is_active": has_active,
        "status": subscription_data.get("status"),
        "details": subscription_data
    }


def get_subscription_tier(user_id: str) -> str:
    """
    Get subscription tier for a user.

    Args:
        user_id: Internal user ID

    Returns:
        Tier name: "free", "monthly", "yearly", or "unknown"
    """
    subscription_service = SubscriptionService()

    result = subscription_service.get_user_subscription(user_id)

    if not result["success"] or not result.get("data"):
        return "free"

    subscription_data = result["data"]
    plan_id = subscription_data.get("plan_id", "")

    # Determine tier from plan_id
    # You can customize this logic based on your Stripe Price IDs
    if "monthly" in plan_id.lower():
        return "monthly"
    elif "yearly" in plan_id.lower() or "annual" in plan_id.lower():
        return "yearly"

    return "unknown"
