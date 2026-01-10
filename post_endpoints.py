from fastapi import APIRouter, Depends, HTTPException, Request
from typing import List, Dict, Any
import logging

from models import BlogCategory
from post_service import get_post_service, PostService
from auth_dependencies import get_current_user_required

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/categories", response_model=Dict[str, List[BlogCategory]], tags=["Posts"]
)
async def get_blog_categories(
    request: Request, post_service: PostService = Depends(get_post_service)
):
    """
    Get all blog categories.
    Authentication is required to access blog categories.
    """
    try:
        # Authentication required
        _ = get_current_user_required(request)

    except HTTPException:
        raise  # Re-raise HTTPException directly
    except Exception as e:
        logger.error(
            f"Error during authentication check for blog categories: {e}"
        )
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        categories = await post_service.get_post_categories()
        return {"categories": categories}

    except Exception as e:
        logger.error(f"Error getting blog categories: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Unable to fetch blog categories: {str(e)}",
        )
