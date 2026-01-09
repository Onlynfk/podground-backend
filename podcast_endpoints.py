"""
Podcast API Endpoints
New podcast system with ListenNotes integration and PostgreSQL caching
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from typing import List, Dict, Any, Optional
import logging
from datetime import datetime
import os

from supabase_client import get_supabase_client, SupabaseClient
from podcast_search_service import get_podcast_search_service, PodcastSearchService
from models import *

logger = logging.getLogger(__name__)
router = APIRouter()

from auth_dependencies import get_current_user_required

def get_podcast_service() -> PodcastSearchService:
    """Get podcast search service with dependencies"""
    supabase = get_supabase_client()
    api_key = os.getenv('LISTENNOTES_API_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail="ListenNotes API key not configured")
    return get_podcast_search_service(supabase.service_client, api_key)

# Search and Discovery

@router.get("/featured")
async def get_featured_podcasts(
    request: Request,
    limit: int = Query(20, ge=1, le=50),
    podcast_service: PodcastSearchService = Depends(get_podcast_service)
):
    """
    Get featured podcasts (curated list)
    """
    try:
        # Get current user (required)
        current_user_id = get_current_user_required(request)
        
        podcasts = await podcast_service.get_featured_podcasts(
            limit=limit,
            user_id=current_user_id
        )
        
        return {
            "results": podcasts,
            "total": len(podcasts),
            "source": "featured"
        }
        
    except Exception as e:
        logger.error(f"Error getting featured podcasts: {e}")
        raise HTTPException(status_code=500, detail="Unable to fetch featured podcasts")

@router.get("/categories/{category_id}")
async def get_podcasts_by_category(
    request: Request,
    category_id: str,
    limit: int = Query(20, ge=1, le=50),
    podcast_service: PodcastSearchService = Depends(get_podcast_service)
):
    """
    Get podcasts by category (mix of featured and API results)
    """
    try:
        # Get current user (required)
        current_user_id = get_current_user_required(request)
        
        podcasts = await podcast_service.get_podcasts_by_category(
            category_id=category_id,
            limit=limit,
            user_id=current_user_id
        )
        
        return {
            "results": podcasts,
            "total": len(podcasts),
            "category_id": category_id,
            "source": "category"
        }
        
    except Exception as e:
        logger.error(f"Error getting podcasts by category: {e}")
        raise HTTPException(status_code=500, detail="Unable to fetch podcasts for category")

@router.get("/categories")
async def get_enhanced_podcast_categories(
    request: Request,
    supabase: SupabaseClient = Depends(get_supabase_client)
):
    """
    Get all podcast categories for enhanced podcast system
    """
    try:
        # Authentication required
        _ = get_current_user_required(request)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during authentication check: {e}")
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        # Check if service client is available
        if not supabase.service_client:
            logger.error("Supabase service client not available. Check SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables.")
            raise HTTPException(status_code=500, detail="Database service not configured")

        # Use service client for reading categories (bypasses RLS)
        result = supabase.service_client.table('podcast_categories') \
            .select('*') \
            .eq('is_active', True) \
            .order('sort_order') \
            .execute()
        
        return {
            "categories": result.data or [],
            "total": len(result.data or [])
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting categories from database: {str(e)}")
        logger.error(f"Error type: {type(e).__name__}")
        raise HTTPException(status_code=500, detail=f"Unable to fetch categories: {str(e)}")

# Admin and Maintenance

@router.post("/admin/cache/cleanup")
async def cleanup_cache(
    request: Request,
    podcast_service: PodcastSearchService = Depends(get_podcast_service)
):
    """
    Clean up expired cache entries (admin only)
    """
    try:
        # Get current user (required for admin actions)
        current_user_id = get_current_user_required(request)
        # TODO: Add admin role check
        
        cleaned_count = await podcast_service.cleanup_expired_cache()
        
        return {
            "success": True,
            "message": f"Cleaned up {cleaned_count} expired cache entries",
            "cleaned_count": cleaned_count
        }
        
    except Exception as e:
        logger.error(f"Error cleaning up cache: {e}")
        raise HTTPException(status_code=500, detail="Unable to cleanup cache")

