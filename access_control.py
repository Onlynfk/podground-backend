"""
Access Control utilities for role-based and subscription-based permissions
"""
import logging
from typing import Optional, Dict, List
from functools import wraps
from fastapi import HTTPException, Depends
from supabase_client import SupabaseClient, get_supabase_client

logger = logging.getLogger(__name__)

class AccessControl:
    """Handles role-based and subscription-based access control"""
    
    def __init__(self, supabase_client: SupabaseClient):
        self.supabase_client = supabase_client
    
    def get_user_role(self, user_id: str) -> Optional[str]:
        """Get user's primary role"""
        try:
            result = self.supabase_client.service_client.table("user_roles").select(
                "role"
            ).eq("user_id", user_id).eq("is_active", True).order(
                "granted_at", desc=True
            ).limit(1).execute()
            
            if result.data:
                return result.data[0]["role"]
            return "podcaster"  # Default role
            
        except Exception as e:
            logger.error(f"Error getting user role: {str(e)}")
            return "podcaster"
    
    def get_user_subscription_plan(self, user_id: str) -> Dict:
        """Get user's current subscription plan"""
        try:
            result = self.supabase_client.service_client.rpc(
                "get_user_subscription_plan", {"input_user_id": user_id}
            ).execute()
            
            if result.data:
                plan_data = result.data[0]
                return {
                    "plan_name": plan_data["plan_name"],
                    "plan_id": plan_data["plan_id"], 
                    "status": plan_data["status"],
                    "is_premium": plan_data["is_premium"]
                }
            
            # Default to free plan
            return {
                "plan_name": "free",
                "plan_id": 1,
                "status": "active", 
                "is_premium": False
            }
            
        except Exception as e:
            logger.error(f"Error getting user subscription: {str(e)}")
            return {"plan_name": "free", "plan_id": 1, "status": "active", "is_premium": False}
    
    
    def can_access_premium_resources(self, user_id: str) -> bool:
        """Check if user can access premium resources"""
        subscription = self.get_user_subscription_plan(user_id)
        
        try:
            # Get plan capabilities
            result = self.supabase_client.service_client.table("subscription_plans").select(
                "can_access_premium_resources"
            ).eq("id", subscription["plan_id"]).single().execute()
            
            if result.data:
                return result.data["can_access_premium_resources"]
            return False
            
        except Exception as e:
            logger.error(f"Error checking premium resource access: {str(e)}")
            return False
    
    def can_access_analytics(self, user_id: str) -> bool:
        """Check if user can access analytics"""
        subscription = self.get_user_subscription_plan(user_id)
        
        try:
            result = self.supabase_client.service_client.table("subscription_plans").select(
                "can_access_analytics"
            ).eq("id", subscription["plan_id"]).single().execute()
            
            if result.data:
                return result.data["can_access_analytics"]
            return False
            
        except Exception as e:
            logger.error(f"Error checking analytics access: {str(e)}")
            return False
    
    def can_create_events(self, user_id: str) -> bool:
        """Check if user can create events"""
        subscription = self.get_user_subscription_plan(user_id)
        
        try:
            result = self.supabase_client.service_client.table("subscription_plans").select(
                "can_create_events"
            ).eq("id", subscription["plan_id"]).single().execute()
            
            if result.data:
                return result.data["can_create_events"]
            return False
            
        except Exception as e:
            logger.error(f"Error checking event creation access: {str(e)}")
            return False

# Global access control instance
access_control: Optional[AccessControl] = None

def init_access_control(supabase_client: SupabaseClient):
    """Initialize global access control instance"""
    global access_control
    access_control = AccessControl(supabase_client)

def get_access_control() -> AccessControl:
    """Get global access control instance"""
    if access_control is None:
        raise HTTPException(status_code=500, detail="Access control not initialized")
    return access_control

# Dependency injection for FastAPI
def get_access_control_dependency() -> AccessControl:
    """FastAPI dependency for access control"""
    return get_access_control()

# Decorators for access control
def require_role(required_role: str):
    """Decorator to require specific role"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract user_id from kwargs (should be injected by auth dependency)
            user_id = kwargs.get('user_id')
            if not user_id:
                raise HTTPException(status_code=401, detail="User ID not found")
            
            ac = get_access_control()
            user_role = ac.get_user_role(user_id)
            
            if user_role != required_role and user_role != "admin":  # Admin can access everything
                raise HTTPException(
                    status_code=403, 
                    detail=f"Access denied. Required role: {required_role}"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator

def require_subscription(required_plan: str = "pro"):
    """Decorator to require specific subscription plan"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user_id = kwargs.get('user_id')
            if not user_id:
                raise HTTPException(status_code=401, detail="User ID not found")
            
            ac = get_access_control()
            user_role = ac.get_user_role(user_id)
            
            # Admin bypasses subscription checks
            if user_role == "admin":
                return await func(*args, **kwargs)
            
            subscription = ac.get_user_subscription_plan(user_id)
            
            # Simple two-tier system: free vs pro
            user_plan = subscription["plan_name"]
            
            if required_plan == "pro" and user_plan != "pro":
                raise HTTPException(
                    status_code=402,  # Payment Required
                    detail="This feature requires a Pro subscription"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_premium_access():
    """Decorator to require premium access"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user_id = kwargs.get('user_id')
            if not user_id:
                raise HTTPException(status_code=401, detail="User ID not found")
            
            ac = get_access_control()
            user_role = ac.get_user_role(user_id)
            
            # Admin bypasses all checks
            if user_role == "admin":
                return await func(*args, **kwargs)
            
            if not ac.can_access_premium_resources(user_id):
                raise HTTPException(
                    status_code=402,  # Payment Required
                    detail="This feature requires a premium subscription"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


async def get_user_subscription_status(user_id: str) -> Dict:
    """
    Get user subscription status for resources service
    This is a standalone function that can be imported and used
    """
    try:
        # Create a temporary AccessControl instance if global one isn't available
        if access_control is None:
            supabase_client = get_supabase_client()
            ac = AccessControl(supabase_client)
        else:
            ac = access_control
        
        subscription = ac.get_user_subscription_plan(user_id)
        return {
            "is_premium": subscription.get("is_premium", False),
            "plan_name": subscription.get("plan_name", "free"),
            "status": subscription.get("status", "active")
        }
    except Exception as e:
        logger.error(f"Error getting user subscription status: {str(e)}")
        # Return free/non-premium status on error
        return {
            "is_premium": False,
            "plan_name": "free",
            "status": "active"
        }