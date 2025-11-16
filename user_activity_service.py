"""
User Activity Service
Handles user activity tracking and feed generation
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException

from supabase_client import SupabaseClient

logger = logging.getLogger(__name__)


class UserActivityService:
    def __init__(self):
        self.supabase_client = SupabaseClient()

    def _generate_signed_url_for_media(self, media_url: Optional[str], storage_path: Optional[str] = None) -> Optional[str]:
        """
        Generate signed URL for media item if storage_path exists, otherwise return public URL

        Args:
            media_url: Public R2 URL
            storage_path: Storage path in R2 bucket

        Returns:
            Signed URL if storage_path exists, otherwise the original public URL
        """
        # If no storage_path, return the public URL as-is (backward compatibility)
        if not storage_path:
            return media_url

        # Generate signed URL using MediaService
        try:
            from media_service import MediaService
            media_service = MediaService()
            # Use expiry parameter (not expiration) - 1 hour = 3600 seconds
            signed_url = media_service.generate_signed_url(storage_path, expiry=3600)
            return signed_url
        except Exception as e:
            logger.error(f"Failed to generate signed URL for {storage_path}: {e}")
            # Fallback to public URL if signing fails
            return media_url

    async def log_activity(self, user_id: str, activity_type: str, activity_data: Dict[str, Any]) -> Dict[str, Any]:
        """Log a user activity"""
        try:
            result = self.supabase_client.service_client.table("user_activity").insert({
                "user_id": user_id,
                "activity_type": activity_type,
                "activity_data": activity_data
            }).execute()

            if not result.data:
                raise Exception("Failed to log activity")

            return {
                "success": True,
                "activity_id": result.data[0]["id"]
            }

        except Exception as e:
            logger.error(f"Failed to log activity for {user_id}: {str(e)}")
            # Don't raise exception for activity logging failures
            return {"success": False, "error": str(e)}

    async def get_user_activity(
        self,
        user_id: str,
        activity_types: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Get user's activity feed"""
        try:
            query = self.supabase_client.service_client.table("user_activity").select(
                "*"
            ).eq("user_id", user_id)

            # Filter by activity types if provided
            if activity_types:
                query = query.in_("activity_type", activity_types)

            # Apply pagination
            query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

            result = query.execute()

            activities = result.data or []

            # Enrich activities with additional data
            enriched_activities = await self._enrich_activities(activities)

            return {
                "activities": enriched_activities,
                "total": len(enriched_activities)
            }

        except Exception as e:
            logger.error(f"Failed to get user activity for {user_id}: {str(e)}")
            raise HTTPException(500, f"Failed to get user activity: {str(e)}")

    async def get_activity_feed(
        self,
        user_id: str,
        include_connections: bool = True,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Get personalized activity feed including connections' activities"""
        try:
            user_ids = [user_id]

            # Include connections' activities if requested
            if include_connections:
                from user_connections_service import get_user_connections_service
                connections_service = get_user_connections_service()

                connections_result = await connections_service.get_user_connections(
                    user_id,
                    status="accepted",
                    limit=1000  # Get all connections
                )

                # Extract connection user IDs
                for conn in connections_result.get("connections", []):
                    user_ids.append(conn["user"]["id"])

            # Get activities from user and connections
            query = self.supabase_client.service_client.table("user_activity").select(
                "*"
            ).in_("user_id", user_ids)

            # Filter relevant activity types for feed
            feed_activity_types = [
                "post_created",
                "post_liked",
                "post_saved",
                "comment_created",
                "comment_liked",
                "connection_accepted",
                "podcast_followed",
                "podcast_saved",
                "episode_listened"
            ]
            query = query.in_("activity_type", feed_activity_types)

            # Apply pagination
            query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

            result = query.execute()

            activities = result.data or []

            # Enrich activities with user profiles and content
            enriched_activities = await self._enrich_activities(activities)

            return {
                "activities": enriched_activities,
                "total": len(enriched_activities)
            }

        except Exception as e:
            logger.error(f"Failed to get activity feed for {user_id}: {str(e)}")
            raise HTTPException(500, f"Failed to get activity feed: {str(e)}")

    async def delete_activity(self, user_id: str, activity_id: str) -> Dict[str, Any]:
        """Delete a user activity (admin only or own activities)"""
        try:
            # Verify activity belongs to user
            result = self.supabase_client.service_client.table("user_activity").select(
                "user_id"
            ).eq("id", activity_id).single().execute()

            if not result.data:
                raise HTTPException(404, "Activity not found")

            if result.data["user_id"] != user_id:
                raise HTTPException(403, "Not authorized to delete this activity")

            # Delete activity
            delete_result = self.supabase_client.service_client.table("user_activity").delete().eq(
                "id", activity_id
            ).execute()

            if not delete_result.data:
                raise Exception("Failed to delete activity")

            return {"success": True}

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to delete activity: {str(e)}")
            raise HTTPException(500, f"Failed to delete activity: {str(e)}")

    async def get_activity_stats(self, user_id: str, days: int = 30) -> Dict[str, Any]:
        """Get activity statistics for a user"""
        try:
            # Calculate date range
            start_date = datetime.now(timezone.utc) - timedelta(days=days)

            # Get activities in date range
            result = self.supabase_client.service_client.table("user_activity").select(
                "activity_type"
            ).eq("user_id", user_id).gte("created_at", start_date.isoformat()).execute()

            activities = result.data or []

            # Count by activity type
            activity_counts = {}
            for activity in activities:
                activity_type = activity["activity_type"]
                activity_counts[activity_type] = activity_counts.get(activity_type, 0) + 1

            return {
                "period_days": days,
                "total_activities": len(activities),
                "activity_breakdown": activity_counts
            }

        except Exception as e:
            logger.error(f"Failed to get activity stats for {user_id}: {str(e)}")
            raise HTTPException(500, f"Failed to get activity stats: {str(e)}")

    async def _enrich_activities(self, activities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Enrich activities with user profiles and related content"""
        if not activities:
            return []

        try:
            # Collect all IDs that we'll need from activities
            user_ids = set(activity["user_id"] for activity in activities)
            post_ids = set()
            comment_ids = set()
            podcast_ids = set()
            episode_ids = set()

            # Pre-scan activities to collect all IDs
            for activity in activities:
                activity_type = activity.get("activity_type")
                activity_data = activity.get("activity_data", {})

                # For connection activities, add the connected user
                if activity_type == "connection_accepted":
                    connected_user_id = activity_data.get("connected_user_id")
                    if connected_user_id:
                        user_ids.add(connected_user_id)

                # Collect post IDs
                elif activity_type in ["post_created", "post_liked", "post_saved"]:
                    post_id = activity_data.get("post_id")
                    if post_id:
                        post_ids.add(post_id)

                # Collect comment IDs
                elif activity_type in ["comment_created", "comment_liked"]:
                    comment_id = activity_data.get("comment_id")
                    if comment_id:
                        comment_ids.add(comment_id)

                # Collect podcast IDs
                elif activity_type in ["podcast_followed", "podcast_saved"]:
                    podcast_id = activity_data.get("podcast_id")
                    if podcast_id:
                        podcast_ids.add(podcast_id)

                # Collect episode IDs
                elif activity_type == "episode_listened":
                    episode_id = activity_data.get("episode_id")
                    podcast_id = activity_data.get("podcast_id")
                    if episode_id:
                        episode_ids.add(episode_id)
                    if podcast_id:
                        podcast_ids.add(podcast_id)

            # Batch fetch all user profiles
            from user_profile_service import UserProfileService
            profile_service = UserProfileService()
            user_profiles = await profile_service.get_users_by_ids(list(user_ids))
            profiles_map = {u["id"]: u for u in user_profiles}

            # Batch fetch all posts
            posts_map = {}
            if post_ids:
                posts_result = self.supabase_client.service_client.table("posts").select(
                    "id, content, post_type, user_id"
                ).in_("id", list(post_ids)).execute()
                if posts_result.data:
                    posts_map = {p["id"]: p for p in posts_result.data}
                    # Add post authors to user_ids for profile fetching
                    for post in posts_result.data:
                        if post.get("user_id"):
                            user_ids.add(post["user_id"])

            # Batch fetch all post media (first image for each post)
            post_media_map = {}
            if post_ids:
                # Get all media for the posts, ordered by position
                media_result = self.supabase_client.service_client.table("post_media").select(
                    "post_id, url, storage_path"
                ).in_("post_id", list(post_ids)).eq("type", "image").order("position").execute()

                if media_result.data:
                    # Group by post_id and take first image for each post, generating signed URLs
                    for media in media_result.data:
                        post_id = media["post_id"]
                        if post_id not in post_media_map:  # Only take the first image
                            # Generate signed URL for the media
                            signed_url = self._generate_signed_url_for_media(
                                media.get("url"),
                                media.get("storage_path")
                            )
                            post_media_map[post_id] = signed_url

            # Batch fetch all comments
            comments_map = {}
            if comment_ids:
                comments_result = self.supabase_client.service_client.table("post_comments").select(
                    "id, content, post_id"
                ).in_("id", list(comment_ids)).execute()
                if comments_result.data:
                    comments_map = {c["id"]: c for c in comments_result.data}
                    # Add comment post IDs to fetch those posts too
                    for comment in comments_result.data:
                        if comment.get("post_id"):
                            post_ids.add(comment["post_id"])

            # Fetch posts referenced by comments (if not already fetched)
            if comment_ids and post_ids:
                # Get the new post IDs that weren't already in posts_map
                new_post_ids = [pid for pid in post_ids if pid not in posts_map]
                if new_post_ids:
                    posts_result = self.supabase_client.service_client.table("posts").select(
                        "id, content, post_type, user_id"
                    ).in_("id", new_post_ids).execute()
                    if posts_result.data:
                        for p in posts_result.data:
                            posts_map[p["id"]] = p
                            # Add post authors to user_ids
                            if p.get("user_id"):
                                user_ids.add(p["user_id"])

                    # Also fetch media for these new posts
                    if new_post_ids:
                        media_result = self.supabase_client.service_client.table("post_media").select(
                            "post_id, url, storage_path"
                        ).in_("post_id", new_post_ids).eq("type", "image").order("position").execute()

                        if media_result.data:
                            for media in media_result.data:
                                post_id = media["post_id"]
                                if post_id not in post_media_map:  # Only take the first image
                                    # Generate signed URL for the media
                                    signed_url = self._generate_signed_url_for_media(
                                        media.get("url"),
                                        media.get("storage_path")
                                    )
                                    post_media_map[post_id] = signed_url

            # Batch fetch all podcasts
            podcasts_map = {}
            if podcast_ids:
                podcasts_result = self.supabase_client.service_client.table("podcasts").select(
                    "id, title, image_url"
                ).in_("id", list(podcast_ids)).execute()
                if podcasts_result.data:
                    podcasts_map = {p["id"]: p for p in podcasts_result.data}

            # Batch fetch all episodes
            episodes_map = {}
            if episode_ids:
                episodes_result = self.supabase_client.service_client.table("episodes").select(
                    "id, title, podcast_id, image_url"
                ).in_("id", list(episode_ids)).execute()
                if episodes_result.data:
                    episodes_map = {e["id"]: e for e in episodes_result.data}
                    # Add podcast IDs from episodes
                    for episode in episodes_result.data:
                        if episode.get("podcast_id"):
                            podcast_ids.add(episode["podcast_id"])

            # Fetch podcasts from episodes (if not already fetched)
            if podcast_ids and not podcasts_map:
                podcasts_result = self.supabase_client.service_client.table("podcasts").select(
                    "id, title, image_url"
                ).in_("id", list(podcast_ids)).execute()
                if podcasts_result.data:
                    for p in podcasts_result.data:
                        if p["id"] not in podcasts_map:
                            podcasts_map[p["id"]] = p

            # Now enrich each activity using the pre-fetched data
            enriched = []
            for activity in activities:
                enriched_activity = {
                    "id": activity["id"],
                    "activity_type": activity["activity_type"],
                    "activity_data": activity["activity_data"],
                    "user": profiles_map.get(activity["user_id"], {"id": activity["user_id"]}),
                    "created_at": activity["created_at"]
                }

                # Add type-specific enrichment using batch-fetched data
                enriched_activity = self._enrich_activity_by_type_batch(
                    enriched_activity,
                    profiles_map,
                    posts_map,
                    post_media_map,
                    comments_map,
                    podcasts_map,
                    episodes_map
                )

                enriched.append(enriched_activity)

            return enriched

        except Exception as e:
            logger.warning(f"Failed to enrich activities: {str(e)}")
            # Return original activities if enrichment fails
            return activities

    async def _enrich_activity_by_type(self, activity: Dict[str, Any], profiles_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Add type-specific enrichment to activity"""
        try:
            activity_type = activity["activity_type"]
            activity_data = activity["activity_data"]

            # Post-related activities
            if activity_type in ["post_created", "post_liked", "post_saved"]:
                post_id = activity_data.get("post_id")
                if post_id:
                    # Get post preview and media
                    post_result = self.supabase_client.service_client.table("posts").select(
                        "id, content, post_type, user_id"
                    ).eq("id", post_id).single().execute()

                    if post_result.data:
                        activity["post"] = post_result.data

                        # Try to get first image from post media
                        try:
                            media_result = self.supabase_client.service_client.table("post_media").select(
                                "url"
                            ).eq("post_id", post_id).eq("type", "image").order(
                                "position"
                            ).limit(1).execute()

                            if media_result.data and media_result.data[0].get("url"):
                                # Use the media URL directly (already signed)
                                activity["image_url"] = media_result.data[0]["url"]
                            else:
                                # No post image, use author's avatar from profiles_map
                                post_author_id = post_result.data.get("user_id")
                                if post_author_id and post_author_id in profiles_map:
                                    author_profile = profiles_map[post_author_id]
                                    if author_profile.get("avatar_url"):
                                        activity["image_url"] = author_profile["avatar_url"]
                        except Exception as e:
                            logger.warning(f"Failed to get post media/avatar: {str(e)}")

            # Comment-related activities
            elif activity_type in ["comment_created", "comment_liked"]:
                comment_id = activity_data.get("comment_id")
                if comment_id:
                    # Get comment preview and associated post
                    comment_result = self.supabase_client.service_client.table("post_comments").select(
                        "id, content, post_id"
                    ).eq("id", comment_id).single().execute()

                    if comment_result.data:
                        activity["comment"] = comment_result.data

                        # Also get the post for context
                        post_id = comment_result.data.get("post_id")
                        if post_id:
                            post_result = self.supabase_client.service_client.table("posts").select(
                                "id, content, post_type"
                            ).eq("id", post_id).single().execute()

                            if post_result.data:
                                activity["post"] = post_result.data

            # Connection activities
            elif activity_type == "connection_accepted":
                connected_user_id = activity_data.get("connected_user_id")
                if connected_user_id and connected_user_id in profiles_map:
                    # Use pre-fetched profile from profiles_map
                    connected_user = profiles_map[connected_user_id]
                    activity["connected_user"] = connected_user
                    # Use connected user's avatar as image
                    if connected_user.get("avatar_url"):
                        activity["image_url"] = connected_user["avatar_url"]

            # Podcast-related activities
            elif activity_type in ["podcast_followed", "podcast_saved"]:
                podcast_id = activity_data.get("podcast_id")
                if podcast_id:
                    podcast_result = self.supabase_client.service_client.table("podcasts").select(
                        "id, title, image_url"
                    ).eq("id", podcast_id).single().execute()

                    if podcast_result.data:
                        activity["podcast"] = podcast_result.data
                        # Use podcast image as image_url
                        if podcast_result.data.get("image_url"):
                            activity["image_url"] = podcast_result.data["image_url"]

            # Episode listen activity
            elif activity_type == "episode_listened":
                episode_id = activity_data.get("episode_id")
                podcast_id = activity_data.get("podcast_id")
                episode_image_url = None

                if episode_id:
                    episode_result = self.supabase_client.service_client.table("episodes").select(
                        "id, title, podcast_id, image_url"
                    ).eq("id", episode_id).single().execute()

                    if episode_result.data:
                        activity["episode"] = episode_result.data
                        podcast_id = episode_result.data.get("podcast_id")
                        episode_image_url = episode_result.data.get("image_url")

                # Get podcast info for context
                if podcast_id:
                    podcast_result = self.supabase_client.service_client.table("podcasts").select(
                        "id, title, image_url"
                    ).eq("id", podcast_id).single().execute()

                    if podcast_result.data:
                        activity["podcast"] = podcast_result.data
                        # Use episode image if available, otherwise use podcast image
                        if episode_image_url:
                            activity["image_url"] = episode_image_url
                        elif podcast_result.data.get("image_url"):
                            activity["image_url"] = podcast_result.data["image_url"]

        except Exception as e:
            logger.warning(f"Failed to enrich activity by type: {str(e)}")

        return activity

    def _enrich_activity_by_type_batch(
        self,
        activity: Dict[str, Any],
        profiles_map: Dict[str, Dict[str, Any]],
        posts_map: Dict[str, Dict[str, Any]],
        post_media_map: Dict[str, str],
        comments_map: Dict[str, Dict[str, Any]],
        podcasts_map: Dict[str, Dict[str, Any]],
        episodes_map: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Add type-specific enrichment to activity using pre-fetched batch data"""
        try:
            activity_type = activity["activity_type"]
            activity_data = activity["activity_data"]

            # Post-related activities
            if activity_type in ["post_created", "post_liked", "post_saved"]:
                post_id = activity_data.get("post_id")
                if post_id and post_id in posts_map:
                    activity["post"] = posts_map[post_id]

                    # Only include image if the post has media (image type posts)
                    if post_id in post_media_map:
                        activity["image_url"] = post_media_map[post_id]
                    else:
                        # No image for non-image posts
                        activity["image_url"] = None

            # Comment-related activities
            elif activity_type in ["comment_created", "comment_liked"]:
                comment_id = activity_data.get("comment_id")
                if comment_id and comment_id in comments_map:
                    activity["comment"] = comments_map[comment_id]

                    # Also get the post for context
                    post_id = comments_map[comment_id].get("post_id")
                    if post_id and post_id in posts_map:
                        activity["post"] = posts_map[post_id]

                        # Only include image if the post being commented on has media
                        if post_id in post_media_map:
                            activity["image_url"] = post_media_map[post_id]
                        else:
                            activity["image_url"] = None

            # Connection activities
            elif activity_type == "connection_accepted":
                connected_user_id = activity_data.get("connected_user_id")
                if connected_user_id and connected_user_id in profiles_map:
                    # Use pre-fetched profile from profiles_map
                    connected_user = profiles_map[connected_user_id]
                    activity["connected_user"] = connected_user
                    # Only use connected user's avatar if available
                    if connected_user.get("avatar_url"):
                        activity["image_url"] = connected_user["avatar_url"]
                    else:
                        activity["image_url"] = None

            # Podcast-related activities
            elif activity_type in ["podcast_followed", "podcast_saved"]:
                podcast_id = activity_data.get("podcast_id")
                if podcast_id and podcast_id in podcasts_map:
                    activity["podcast"] = podcasts_map[podcast_id]
                    # Only use podcast cover art if available
                    if podcasts_map[podcast_id].get("image_url"):
                        activity["image_url"] = podcasts_map[podcast_id]["image_url"]
                    else:
                        activity["image_url"] = None

            # Episode listen activity
            elif activity_type == "episode_listened":
                episode_id = activity_data.get("episode_id")
                podcast_id = activity_data.get("podcast_id")
                episode_image_url = None

                if episode_id and episode_id in episodes_map:
                    activity["episode"] = episodes_map[episode_id]
                    podcast_id = episodes_map[episode_id].get("podcast_id")
                    episode_image_url = episodes_map[episode_id].get("image_url")

                # Get podcast info for context
                if podcast_id and podcast_id in podcasts_map:
                    activity["podcast"] = podcasts_map[podcast_id]
                    # Only use episode or podcast cover art if available
                    if episode_image_url:
                        activity["image_url"] = episode_image_url
                    elif podcasts_map[podcast_id].get("image_url"):
                        activity["image_url"] = podcasts_map[podcast_id]["image_url"]
                    else:
                        activity["image_url"] = None

        except Exception as e:
            logger.warning(f"Failed to enrich activity by type (batch): {str(e)}")

        return activity


# Global instance
_user_activity_service = None

def get_user_activity_service() -> UserActivityService:
    """Get or create global UserActivityService instance"""
    global _user_activity_service
    if _user_activity_service is None:
        _user_activity_service = UserActivityService()
    return _user_activity_service
