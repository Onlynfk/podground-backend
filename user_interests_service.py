"""
User Interests Service
Handles user interests/topics management
"""
import logging
from typing import Dict, Any, List
from fastapi import HTTPException

from supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class UserInterestsService:
    def __init__(self):
        self.supabase_client = get_supabase_client()

    async def get_all_topics(self) -> List[Dict[str, Any]]:
        """Get all available topics"""
        try:
            result = self.supabase_client.service_client.table("topics").select(
                "*"
            ).order("category").order("name").execute()

            return result.data or []

        except Exception as e:
            logger.error(f"Failed to get topics: {str(e)}")
            raise HTTPException(500, f"Failed to get topics: {str(e)}")

    async def get_topics_by_category(self, category: str) -> List[Dict[str, Any]]:
        """Get topics by category"""
        try:
            result = self.supabase_client.service_client.table("topics").select(
                "*"
            ).eq("category", category).order("name").execute()

            return result.data or []

        except Exception as e:
            logger.error(f"Failed to get topics by category: {str(e)}")
            raise HTTPException(500, f"Failed to get topics by category: {str(e)}")

    async def get_user_interests(self, user_id: str) -> List[Dict[str, Any]]:
        """Get user's interests with topic details"""
        try:
            # Get user interests with topic info via join
            result = self.supabase_client.service_client.table("user_interests").select(
                """
                id,
                created_at,
                topic_id,
                topics (
                    id,
                    name,
                    category
                )
                """
            ).eq("user_id", user_id).execute()

            if not result.data:
                return []

            # Flatten the structure
            interests = []
            for item in result.data:
                if item.get("topics"):
                    interests.append({
                        "id": item["id"],
                        "topic_id": item["topic_id"],
                        "topic_name": item["topics"]["name"],
                        "topic_category": item["topics"]["category"],
                        "created_at": item["created_at"]
                    })

            return interests

        except Exception as e:
            logger.error(f"Failed to get user interests for {user_id}: {str(e)}")
            raise HTTPException(500, f"Failed to get user interests: {str(e)}")

    async def update_user_interests(self, user_id: str, topic_ids: List[str]) -> List[Dict[str, Any]]:
        """Replace user's interests with new set of topics"""
        try:
            # Validate topic IDs exist
            if topic_ids:
                topics_result = self.supabase_client.service_client.table("topics").select(
                    "id"
                ).in_("id", topic_ids).execute()

                valid_topic_ids = {t["id"] for t in topics_result.data or []}
                invalid_ids = set(topic_ids) - valid_topic_ids

                if invalid_ids:
                    raise HTTPException(400, f"Invalid topic IDs: {', '.join(invalid_ids)}")

            # Delete existing interests
            self.supabase_client.service_client.table("user_interests").delete().eq(
                "user_id", user_id
            ).execute()

            # Insert new interests
            if topic_ids:
                interests_data = [
                    {"user_id": user_id, "topic_id": topic_id}
                    for topic_id in topic_ids
                ]

                self.supabase_client.service_client.table("user_interests").insert(
                    interests_data
                ).execute()

            # Return updated interests
            return await self.get_user_interests(user_id)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to update user interests for {user_id}: {str(e)}")
            raise HTTPException(500, f"Failed to update user interests: {str(e)}")

    async def add_user_interest(self, user_id: str, topic_id: str) -> Dict[str, Any]:
        """Add a single interest to user's interests"""
        try:
            # Validate topic exists
            topic_result = self.supabase_client.service_client.table("topics").select(
                "id, name, category"
            ).eq("id", topic_id).single().execute()

            if not topic_result.data:
                raise HTTPException(404, "Topic not found")

            # Check if already exists
            existing = self.supabase_client.service_client.table("user_interests").select(
                "id"
            ).eq("user_id", user_id).eq("topic_id", topic_id).execute()

            if existing.data:
                raise HTTPException(400, "Interest already exists")

            # Insert new interest
            result = self.supabase_client.service_client.table("user_interests").insert({
                "user_id": user_id,
                "topic_id": topic_id
            }).execute()

            if not result.data:
                raise Exception("Failed to add interest")

            return {
                "id": result.data[0]["id"],
                "topic_id": topic_id,
                "topic_name": topic_result.data["name"],
                "topic_category": topic_result.data["category"],
                "created_at": result.data[0]["created_at"]
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to add user interest: {str(e)}")
            raise HTTPException(500, f"Failed to add interest: {str(e)}")

    async def remove_user_interest(self, user_id: str, topic_id: str) -> Dict[str, Any]:
        """Remove a single interest from user's interests"""
        try:
            # Delete the interest
            result = self.supabase_client.service_client.table("user_interests").delete().eq(
                "user_id", user_id
            ).eq("topic_id", topic_id).execute()

            if not result.data:
                raise HTTPException(404, "Interest not found")

            return {"success": True}

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to remove user interest: {str(e)}")
            raise HTTPException(500, f"Failed to remove interest: {str(e)}")

    async def get_users_by_interest(self, topic_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get users who share a specific interest"""
        try:
            # Validate topic exists
            topic_result = self.supabase_client.service_client.table("topics").select(
                "id, name"
            ).eq("id", topic_id).single().execute()

            if not topic_result.data:
                raise HTTPException(404, "Topic not found")

            # Get users with this interest
            result = self.supabase_client.service_client.table("user_interests").select(
                "user_id"
            ).eq("topic_id", topic_id).limit(limit).execute()

            if not result.data:
                return []

            user_ids = [item["user_id"] for item in result.data]

            # Get user profiles (use user_profile_service to get full profiles)
            from user_profile_service import UserProfileService
            profile_service = UserProfileService()

            users = await profile_service.get_users_by_ids(user_ids)

            return users

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get users by interest: {str(e)}")
            raise HTTPException(500, f"Failed to get users by interest: {str(e)}")


# Global instance
_user_interests_service = None

def get_user_interests_service() -> UserInterestsService:
    """Get or create global UserInterestsService instance"""
    global _user_interests_service
    if _user_interests_service is None:
        _user_interests_service = UserInterestsService()
    return _user_interests_service
