"""
Conversation Limits Endpoints for Free User Plan Restrictions
"""

from fastapi import APIRouter, Request, HTTPException, Depends
from slowapi import Limiter
from slowapi.util import get_remote_address
import logging

# These would need to be imported from main.py or shared module
# from main import get_current_user_from_session, supabase_client, limiter

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/api/v1/user/conversation-limits", response_model=dict, tags=["User"])
# @limiter.limit("60/minute")
async def get_conversation_limits(request: Request, user_id: str = Depends(get_current_user_from_session)):
    """Get user's conversation limits and usage status"""
    try:
        # Call the database function to get current status
        result = supabase_client.service_client.rpc(
            'get_user_conversation_status', 
            {'user_uuid': user_id}
        ).execute()
        
        if result.data and len(result.data) > 0:
            status = result.data[0]
            return {
                "success": True,
                "data": {
                    "conversations_used": status["conversations_used"],
                    "max_conversations": status["max_conversations"],
                    "conversations_remaining": status["conversations_remaining"],
                    "cycle_start_date": status["cycle_start_date"],
                    "cycle_end_date": status["cycle_end_date"],
                    "days_until_reset": status["days_until_reset"],
                    "can_start_new": status["can_start_new"]
                }
            }
        else:
            raise HTTPException(status_code=404, detail="Conversation limits not found")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting conversation limits: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/api/v1/user/conversation-limits/check", response_model=dict, tags=["User"])
# @limiter.limit("100/minute")
async def check_can_start_conversation(request: Request, user_id: str = Depends(get_current_user_from_session)):
    """Check if user can start a new conversation"""
    try:
        # Call the database function to check if user can start conversation
        result = supabase_client.service_client.rpc(
            'can_user_start_conversation', 
            {'user_uuid': user_id}
        ).execute()
        
        can_start = result.data if result.data is not None else False
        
        return {
            "success": True,
            "can_start_conversation": can_start,
            "message": "You can start a new conversation" if can_start else "You have reached your conversation limit for this month"
        }
            
    except Exception as e:
        logger.error(f"Error checking conversation limits: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/api/v1/user/conversation-limits/record", response_model=dict, tags=["User"])
# @limiter.limit("100/minute")
async def record_conversation_start(request: Request, conversation_data: dict, user_id: str = Depends(get_current_user_from_session)):
    """Record that a user started a new conversation (called by conversation system)"""
    try:
        conversation_id = conversation_data.get("conversation_id")
        if not conversation_id:
            raise HTTPException(status_code=400, detail="conversation_id is required")
        
        # Call the database function to record the new conversation
        result = supabase_client.service_client.rpc(
            'record_new_conversation', 
            {'user_uuid': user_id, 'conversation_id': conversation_id}
        ).execute()
        
        success = result.data if result.data is not None else False
        
        return {
            "success": success,
            "message": "Conversation recorded successfully" if success else "Failed to record conversation"
        }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error recording conversation: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")