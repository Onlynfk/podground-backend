"""
Resource Interaction Service
Handles tracking user interactions with articles, videos, and guides
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from fastapi import HTTPException
import uuid

from supabase_client import SupabaseClient

logger = logging.getLogger(__name__)


class ResourceInteractionService:
    def __init__(self):
        self.supabase_client = SupabaseClient()

    async def track_interaction(
        self,
        user_id: str,
        resource_id: str,
        interaction_type: str,
        interaction_data: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Track a user interaction with a resource

        Args:
            user_id: User ID
            resource_id: Resource ID
            interaction_type: Type of interaction (article_opened, video_played, etc.)
            interaction_data: Additional data (position, percentage, etc.)
            session_id: Optional session ID to group related interactions

        Returns:
            Dictionary with success status and interaction ID
        """
        try:
            # Validate resource exists
            resource_result = self.supabase_client.service_client.table("resources").select(
                "id, type, duration"
            ).eq("id", resource_id).single().execute()

            if not resource_result.data:
                raise HTTPException(404, "Resource not found")

            resource = resource_result.data
            resource_type = resource["type"]

            # Generate session ID if not provided
            if not session_id:
                session_id = str(uuid.uuid4())

            # Insert interaction record
            interaction_record = {
                "user_id": user_id,
                "resource_id": resource_id,
                "interaction_type": interaction_type,
                "interaction_data": interaction_data or {},
                "session_id": session_id
            }

            interaction_result = self.supabase_client.service_client.table("resource_interactions").insert(
                interaction_record
            ).execute()

            if not interaction_result.data:
                raise Exception("Failed to record interaction")

            # Update aggregated stats
            await self._update_resource_stats(
                user_id=user_id,
                resource_id=resource_id,
                resource_type=resource_type,
                resource_duration=resource.get("duration"),
                interaction_type=interaction_type,
                interaction_data=interaction_data or {}
            )

            return {
                "success": True,
                "interaction_id": interaction_result.data[0]["id"],
                "session_id": session_id
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to track interaction: {str(e)}")
            raise HTTPException(500, f"Failed to track interaction: {str(e)}")

    async def _update_resource_stats(
        self,
        user_id: str,
        resource_id: str,
        resource_type: str,
        resource_duration: Optional[int],
        interaction_type: str,
        interaction_data: Dict[str, Any]
    ):
        """Update aggregated resource statistics"""
        try:
            # Get or create stats record
            stats_result = self.supabase_client.service_client.table("user_resource_stats").select(
                "*"
            ).eq("user_id", user_id).eq("resource_id", resource_id).execute()

            now = datetime.now(timezone.utc).isoformat()

            if not stats_result.data:
                # Create new stats record
                stats_data = {
                    "user_id": user_id,
                    "resource_id": resource_id,
                    "total_views": 1,
                    "total_watch_time": 0,
                    "total_read_time": 0,
                    "completion_percentage": 0,
                    "is_completed": False,
                    "last_position": 0,
                    "first_viewed_at": now,
                    "last_viewed_at": now
                }

                self.supabase_client.service_client.table("user_resource_stats").insert(
                    stats_data
                ).execute()
            else:
                # Update existing stats
                current_stats = stats_result.data[0]

                # Check if resource is already completed
                is_already_completed = current_stats.get("is_completed", False)

                # If already completed, ignore most interactions except reopening
                if is_already_completed:
                    # Only allow video_started/article_opened to update view count
                    if interaction_type in ["article_opened", "video_started"]:
                        update_data = {
                            "last_viewed_at": now,
                            "total_views": current_stats.get("total_views", 0) + 1
                        }
                        self.supabase_client.service_client.table("user_resource_stats").update(
                            update_data
                        ).eq("user_id", user_id).eq("resource_id", resource_id).execute()
                    # Ignore all other interactions for completed resources
                    logger.info(f"Skipping interaction {interaction_type} for completed resource {resource_id}")
                    return

                update_data = {"last_viewed_at": now}

                # Update based on interaction type
                if interaction_type in ["article_opened", "video_started"]:
                    update_data["total_views"] = current_stats.get("total_views", 0) + 1

                elif interaction_type == "video_progress":
                    # Update watch time and position
                    position = interaction_data.get("position", 0)
                    duration = interaction_data.get("duration", resource_duration or 0)
                    current_position = current_stats.get("last_position", 0)

                    logger.info(f"Video progress - position: {position}, current: {current_position}, will update: {position >= current_position}")

                    # Only update if user is moving forward or at same position (no backward seeks)
                    if position >= current_position:
                        update_data["last_position"] = position

                        if duration > 0:
                            completion_pct = int((position / duration) * 100)
                            update_data["completion_percentage"] = min(completion_pct, 100)

                        # Update watch time (estimate based on time since last interaction)
                        watch_time_delta = interaction_data.get("watch_time_delta", 0)
                        if watch_time_delta > 0:
                            update_data["total_watch_time"] = current_stats.get("total_watch_time", 0) + watch_time_delta

                        logger.info(f"Updated video progress - new position: {position}, completion: {update_data.get('completion_percentage', 0)}%")
                    else:
                        # User went backward - don't update progress
                        logger.info(f"Skipping video progress update - user at position {position}, last position was {current_position}")

                elif interaction_type == "article_read_progress":
                    # Update read progress
                    scroll_percentage = interaction_data.get("scroll_percentage", 0)
                    current_scroll = current_stats.get("last_position", 0)

                    # Only update if user scrolled forward or at same position
                    if scroll_percentage >= current_scroll:
                        update_data["completion_percentage"] = int(scroll_percentage)
                        update_data["last_position"] = int(scroll_percentage)  # Track scroll position

                        # Update read time
                        read_time_delta = interaction_data.get("read_time_delta", 0)
                        if read_time_delta > 0:
                            update_data["total_read_time"] = current_stats.get("total_read_time", 0) + read_time_delta
                    else:
                        # User scrolled backward or stayed at same position - don't update progress
                        logger.debug(f"Skipping article progress update - user at {scroll_percentage}%, last scroll was {current_scroll}%")

                elif interaction_type in ["video_completed", "article_completed"]:
                    update_data["is_completed"] = True
                    update_data["completion_percentage"] = 100
                    update_data["completed_at"] = now

                    # Update last_position to the end
                    if interaction_type == "video_completed":
                        # Use position if provided, otherwise use duration
                        position = interaction_data.get("position")
                        if position is not None:
                            update_data["last_position"] = position
                        else:
                            duration = interaction_data.get("duration", resource_duration)
                            if duration:
                                update_data["last_position"] = duration
                    elif interaction_type == "article_completed":
                        update_data["last_position"] = 100  # 100% scrolled

                elif interaction_type == "guide_downloaded":
                    update_data["is_completed"] = True
                    update_data["completion_percentage"] = 100

                # Perform update
                self.supabase_client.service_client.table("user_resource_stats").update(
                    update_data
                ).eq("user_id", user_id).eq("resource_id", resource_id).execute()

        except Exception as e:
            logger.warning(f"Failed to update resource stats: {str(e)}")
            # Don't fail the main request if stats update fails

    async def get_user_resource_stats(
        self,
        user_id: str,
        resource_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get aggregated stats for a user's interaction with a specific resource"""
        try:
            result = self.supabase_client.service_client.table("user_resource_stats").select(
                "*"
            ).eq("user_id", user_id).eq("resource_id", resource_id).single().execute()

            if not result.data:
                return None

            return result.data

        except Exception as e:
            logger.error(f"Failed to get resource stats: {str(e)}")
            return None

    async def get_user_interaction_history(
        self,
        user_id: str,
        resource_id: Optional[str] = None,
        interaction_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get user's interaction history"""
        try:
            query = self.supabase_client.service_client.table("resource_interactions").select(
                "*"
            ).eq("user_id", user_id)

            if resource_id:
                query = query.eq("resource_id", resource_id)

            if interaction_type:
                query = query.eq("interaction_type", interaction_type)

            query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

            result = query.execute()

            return result.data or []

        except Exception as e:
            logger.error(f"Failed to get interaction history: {str(e)}")
            raise HTTPException(500, f"Failed to get interaction history: {str(e)}")

    async def get_user_resources_progress(
        self,
        user_id: str,
        is_completed: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Get all resources a user has interacted with and their progress"""
        try:
            query = self.supabase_client.service_client.table("user_resource_stats").select(
                "*"
            ).eq("user_id", user_id)

            if is_completed is not None:
                query = query.eq("is_completed", is_completed)

            query = query.order("last_viewed_at", desc=True).range(offset, offset + limit - 1)

            result = query.execute()

            if not result.data:
                return {"resources": [], "total": 0}

            # Get resource details
            resource_ids = [stat["resource_id"] for stat in result.data]
            resources_result = self.supabase_client.service_client.table("resources").select(
                "*"
            ).in_("id", resource_ids).execute()

            resources_map = {r["id"]: r for r in resources_result.data or []}

            # Combine stats with resource data
            combined_data = []
            for stat in result.data:
                resource_data = resources_map.get(stat["resource_id"])
                if resource_data:
                    combined_data.append({
                        "resource": resource_data,
                        "stats": stat
                    })

            return {
                "resources": combined_data,
                "total": len(combined_data)
            }

        except Exception as e:
            logger.error(f"Failed to get user resources progress: {str(e)}")
            raise HTTPException(500, f"Failed to get resources progress: {str(e)}")


# Global instance
_resource_interaction_service = None

def get_resource_interaction_service() -> ResourceInteractionService:
    """Get or create global ResourceInteractionService instance"""
    global _resource_interaction_service
    if _resource_interaction_service is None:
        _resource_interaction_service = ResourceInteractionService()
    return _resource_interaction_service
