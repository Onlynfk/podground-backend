from fastapi import HTTPException, Request
from typing import Optional

def get_current_user_from_request(request: Request) -> Optional[str]:
    """Extract user ID from session, return None if not authenticated"""
    try:
        user_id = request.session.get("user_id")
        return user_id if user_id else None
    except Exception:
        return None

def get_current_user_required(request: Request) -> str:
    """Extract user ID from session, raise exception if not authenticated"""
    user_id = get_current_user_from_request(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id
