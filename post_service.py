import logging
from typing import List

from supabase_client import SupabaseClient, get_supabase_client
from models import BlogCategory  # Assuming BlogCategory is in models.py

logger = logging.getLogger(__name__)


class PostService:
    def __init__(self, supabase_client: SupabaseClient):
        self.supabase_client = supabase_client

    async def get_blog_categories(self) -> List[BlogCategory]:
        """
        Fetches all active blog categories from the database.
        """
        try:
            # Check if service client is available
            if not self.supabase_client.service_client:
                logger.error(
                    "Supabase service client not available. Check SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables."
                )
                return []

            # Use service client for reading categories (bypasses RLS if needed for public access)
            # Assuming the table name for blog categories is 'post_categories' based on migration files
            result = (
                self.supabase_client.service_client.table("post_categories")
                .select("id, name")
                .eq("is_active", True)
                .order("name")
                .execute()
            )

            categories_data = result.data

            if not categories_data:
                return []

            # Map to BlogCategory Pydantic model
            blog_categories = [
                BlogCategory(id=item["id"], name=item["name"])
                for item in categories_data
            ]
            return blog_categories

        except Exception as e:
            logger.error(
                f"Error fetching blog categories from database: {str(e)}"
            )
            return []


async def get_post_service() -> PostService:
    """
    Dependency to get PostService instance.
    """
    supabase = get_supabase_client()
    return PostService(supabase)
