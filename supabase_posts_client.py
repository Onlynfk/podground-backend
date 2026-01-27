import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
import functools
from feed_cache_service import get_feed_cache_service

logger = logging.getLogger(__name__)

class SupabasePostsClient:
    """Extension to SupabaseClient for posts and social features"""

    def __init__(self, supabase_client):
        self.client = supabase_client
        # Thread pool for parallelizing I/O-bound operations like signed URL generation
        self._thread_pool = ThreadPoolExecutor(max_workers=10)
        # Initialize feed cache service with event-based invalidation
        self.feed_cache = get_feed_cache_service()
        self.feed_cache.set_supabase_client(supabase_client.service_client)

    def _generate_signed_url_for_media(self, media_item: Dict) -> str:
        """
        Generate signed URL for media item if storage_path exists, otherwise return public URL

        Args:
            media_item: Dict with 'url', 'storage_path', and other media fields

        Returns:
            Signed URL if storage_path exists, otherwise the original public URL
        """
        storage_path = media_item.get("storage_path")

        # If no storage_path, return the public URL as-is (backward compatibility)
        if not storage_path:
            return media_item.get("url", "")

        # Generate signed URL using MediaService (same as message media)
        try:
            from media_service import MediaService
            media_service = MediaService()
            # Use expiry parameter (not expiration) - 1 hour = 3600 seconds
            signed_url = media_service.generate_signed_url(storage_path, expiry=3600)
            return signed_url
        except Exception as e:
            logger.error(f"Failed to generate signed URL for {storage_path}: {e}")
            # Fallback to public URL if signing fails
            return media_item.get("url", "")

    def _generate_signed_url_from_r2_url(self, direct_url: Optional[str]) -> Optional[str]:
        """
        Convert a direct R2 URL to a pre-signed URL

        Args:
            direct_url: Direct R2 public URL (e.g., "https://pub-bucket.r2.dev/path/to/file.jpg")

        Returns:
            Pre-signed URL with expiry, or original URL if signing fails
        """
        if not direct_url:
            return direct_url

        try:
            from media_service import MediaService
            import os

            media_service = MediaService()
            r2_public_url = os.getenv('R2_PUBLIC_URL', f"https://pub-{media_service.r2_bucket}.r2.dev")

            # Extract storage path from the direct URL
            # Example: "https://pub-bucket.r2.dev/categories/image.jpg" -> "categories/image.jpg"
            if r2_public_url in direct_url:
                storage_path = direct_url.replace(f"{r2_public_url}/", "")
                # Generate signed URL - 1 hour expiry
                signed_url = media_service.generate_signed_url(storage_path, expiry=3600)
                return signed_url
            else:
                # Not an R2 URL, return as-is (backward compatibility for external URLs)
                return direct_url

        except Exception as e:
            logger.warning(f"Failed to generate signed URL from R2 URL {direct_url}: {e}")
            # Fallback to original URL if signing fails
            return direct_url

    async def _generate_signed_urls_parallel(self, media_items: List[Dict]) -> List[str]:
        """
        Generate signed URLs for multiple media items in parallel using thread pool.

        Args:
            media_items: List of media item dictionaries

        Returns:
            List of signed URLs in the same order as input
        """
        if not media_items:
            return []

        # Create tasks to run in thread pool
        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(
                self._thread_pool,
                self._generate_signed_url_for_media,
                media
            )
            for media in media_items
        ]

        # Wait for all tasks to complete
        return await asyncio.gather(*tasks)

    async def _regenerate_urls_in_feed(self, feed_data: Dict) -> None:
        """
        Regenerate fresh pre-signed URLs for all media in cached feed data.
        This ensures URLs are always fresh even when served from cache.

        Args:
            feed_data: Feed response dictionary with posts
        """
        try:
            posts = feed_data.get("posts", [])
            if not posts:
                return

            # Collect all media items and avatars that need URL regeneration
            media_tasks = []
            avatar_tasks = []

            for post in posts:
                # Regenerate post media URLs
                media_items = post.get("media_items", [])
                if media_items:
                    media_tasks.append((post, media_items))

                # Regenerate user avatar URL
                user = post.get("user", {})
                avatar_storage_path = user.get("avatar_storage_path")
                if avatar_storage_path:
                    avatar_tasks.append(user)

            # Generate all URLs in parallel
            loop = asyncio.get_event_loop()
            all_tasks = []

            # Create tasks for post media
            for post, media_items in media_tasks:
                task = loop.run_in_executor(
                    self._thread_pool,
                    self._regenerate_media_urls_sync,
                    media_items
                )
                all_tasks.append((task, 'media', post, media_items))

            # Create tasks for avatars
            for user in avatar_tasks:
                task = loop.run_in_executor(
                    self._thread_pool,
                    self._generate_avatar_url_sync,
                    user.get("avatar_storage_path")
                )
                all_tasks.append((task, 'avatar', user, None))

            # Wait for all URL generation tasks
            results = await asyncio.gather(*[task for task, _, _, _ in all_tasks], return_exceptions=True)

            # Apply results back to the feed data
            for i, (task, task_type, target, media_items) in enumerate(all_tasks):
                try:
                    result = results[i]
                    if isinstance(result, Exception):
                        logger.error(f"Error regenerating {task_type} URL: {result}")
                        continue

                    if task_type == 'media' and media_items:
                        # Update media item URLs
                        for j, media in enumerate(media_items):
                            if j < len(result):
                                media['url'] = result[j]
                    elif task_type == 'avatar' and result:
                        # Update avatar URL
                        target['avatar_url'] = result

                except Exception as e:
                    logger.error(f"Error applying regenerated {task_type} URL: {e}")

            logger.debug(f"Regenerated URLs for {len(media_tasks)} media groups and {len(avatar_tasks)} avatars")

        except Exception as e:
            logger.error(f"Error regenerating URLs in feed: {e}", exc_info=True)
            # Don't fail the request if URL regeneration fails

    def _regenerate_media_urls_sync(self, media_items: List[Dict]) -> List[str]:
        """Synchronous wrapper to regenerate URLs for media items"""
        return [self._generate_signed_url_for_media(media) for media in media_items]

    def _generate_avatar_url_sync(self, storage_path: str) -> Optional[str]:
        """Synchronous wrapper to generate avatar URL"""
        if not storage_path:
            return None

        try:
            from media_service import MediaService
            media_service = MediaService()
            return media_service.generate_signed_url(storage_path, expiry=3600)
        except Exception as e:
            logger.error(f"Failed to generate avatar URL for {storage_path}: {e}")
            return None

    # Posts CRUD
    async def get_available_categories(self) -> List[Dict[str, Any]]:
        """Get all available post categories for AI post categorization"""
        try:
            result = self.client.service_client.table("post_categories").select(
                "*"
            ).eq("is_active", True).order("sort_order").execute()

            categories = result.data or []

            # Convert direct R2 URLs to signed URLs for category images
            for category in categories:
                if category.get("image_url"):
                    category["image_url"] = self._generate_signed_url_from_r2_url(category["image_url"])

            return categories
        except Exception as e:
            logger.error(f"Failed to get available categories: {str(e)}")
            return []

    async def create_post(self, user_id: str, post_data: Dict) -> Dict:
        """Create a new post"""
        try:
            # Check if user provided a category_id
            category_id = post_data.get("category_id")

            # If no category provided, use AI to categorize the post
            if not category_id:
                # Get available categories for AI categorization
                available_categories = await self.get_available_categories()

                if available_categories:
                    try:
                        from ai_categorization_service import ai_categorization
                        category_id = await ai_categorization.categorize_post(
                            post_data["content"],
                            available_categories
                        )

                        # Fallback to a default category if AI categorization fails
                        if not category_id:
                            category_id = await ai_categorization.get_fallback_category(available_categories)

                    except Exception as e:
                        logger.warning(f"AI categorization failed, using fallback: {str(e)}")
                        # Use first available category as fallback
                        if available_categories:
                            category_id = available_categories[0]["id"]
            else:
                logger.info(f"Using user-provided category_id: {category_id}")

            # Create post
            post = {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "content": post_data["content"],
                "post_type": post_data["post_type"],
                "podcast_episode_url": post_data.get("podcast_episode_url"),
                "category_id": category_id,
            }
            
            post_result = self.client.service_client.table("posts").insert(post).execute()
            
            if not post_result.data:
                return {"success": False, "error": "Failed to create post"}
            
            post_id = post_result.data[0]["id"]
            
            # Handle media items
            # Prefer media_items (has storage_path), fallback to media_urls for backward compatibility
            media_urls_for_marking = []

            if post_data.get("media_items"):
                # New format with full media info including storage_path
                media_records = []
                for i, media_item in enumerate(post_data["media_items"]):
                    media_record = {
                        "post_id": post_id,
                        "url": media_item.get("url"),
                        "storage_path": media_item.get("storage_path"),  # Store R2 path for signed URLs
                        "type": media_item.get("type", "image"),
                        "thumbnail_url": media_item.get("thumbnail_url"),
                        "duration": media_item.get("duration"),
                        "width": media_item.get("width"),
                        "height": media_item.get("height"),
                        "position": i
                    }
                    media_records.append(media_record)
                    # Collect URLs for marking as used
                    if media_item.get("url"):
                        media_urls_for_marking.append(media_item.get("url"))

                self.client.service_client.table("post_media").insert(media_records).execute()

            elif post_data.get("media_urls"):
                # Fallback for backward compatibility (no storage_path)
                media_records = []
                for i, url in enumerate(post_data["media_urls"]):
                    media_records.append({
                        "post_id": post_id,
                        "url": url,
                        "type": post_data.get("media_type", "image"),
                        "position": i
                    })
                    media_urls_for_marking.append(url)

                self.client.service_client.table("post_media").insert(media_records).execute()

            # Mark temporary media as used to prevent cleanup deletion
            if media_urls_for_marking:
                try:
                    from media_service import MediaService
                    media_service = MediaService()
                    await media_service.mark_media_as_used(media_urls_for_marking, user_id)
                    logger.info(f"Marked {len(media_urls_for_marking)} media files as used for post {post_id}")
                except Exception as e:
                    logger.warning(f"Failed to mark media as used for post {post_id}: {str(e)}")

            # Handle hashtags/topics
            if post_data.get("hashtags"):
                # Extract and link hashtags to topics
                # TODO: Implement hashtag processing
                pass

            # Log activity
            try:
                from user_activity_service import get_user_activity_service
                activity_service = get_user_activity_service()
                await activity_service.log_activity(user_id, "post_created", {"post_id": post_id})
            except Exception as e:
                logger.warning(f"Failed to log post_created activity: {str(e)}")

            # Fetch and return the complete post data
            complete_post = self.get_post(post_id, user_id)

            # Invalidate feed cache (application-level)
            self.feed_cache.invalidate_via_database()
            logger.info(f"Feed cache invalidated after post creation: {post_id}")

            if complete_post["success"]:
                return {"success": True, "data": complete_post["data"]}
            else:
                # Fallback to just returning the post_id
                return {"success": True, "data": {"post_id": post_id}}
            
        except Exception as e:
            logger.error(f"Create post error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def get_post(self, post_id: str, user_id: Optional[str] = None) -> Dict:
        """Get a single post with all details"""
        try:
            # Get post with media and category
            query = self.client.service_client.table("posts").select(
                "*, post_media(*), post_categories(id, name, display_name, color)"
            ).eq("id", post_id).single()
            
            post_result = query.execute()
            
            if not post_result.data:
                return {"success": False, "error": "Post not found"}
            
            post = post_result.data

            # Get user data for the post (same logic as get_feed)
            try:
                # Get auth user data
                user_response = self.client.service_client.auth.admin.get_user_by_id(post["user_id"])
                user_metadata = {}
                name = "Unknown User"

                if user_response and user_response.user:
                    post_user = user_response.user
                    user_metadata = post_user.user_metadata or {}
                    # Try to get name from various possible fields
                    name = user_metadata.get("name") or user_metadata.get("full_name") or user_metadata.get("first_name", "")
                    if user_metadata.get("last_name"):
                        name = f"{name} {user_metadata.get('last_name')}".strip()
                    if not name:
                        name = post_user.email.split('@')[0] if hasattr(post_user, 'email') else "Unknown User"

                # Fetch user profile for avatar_url and bio
                user_profile = {}
                try:
                    profile_result = self.client.service_client.table("user_profiles").select(
                        "avatar_url, bio"
                    ).eq("user_id", post["user_id"]).execute()

                    if profile_result.data:
                        user_profile = profile_result.data[0]
                except Exception as e:
                    logger.warning(f"Failed to fetch user profile: {str(e)}")

                # Fetch podcast claim for podcast_name and podcast_id
                podcast_claim = {}
                try:
                    claim_result = self.client.service_client.table("podcast_claims").select(
                        "listennotes_id"
                    ).eq("user_id", post["user_id"]).eq("is_verified", True).eq("claim_status", "verified").execute()

                    if claim_result.data:
                        listennotes_id = claim_result.data[0]["listennotes_id"]
                        # Fetch podcast info
                        podcast_result = self.client.service_client.table("podcasts").select(
                            "id, title"
                        ).eq("listennotes_id", listennotes_id).execute()

                        if podcast_result.data:
                            podcast_claim = {
                                "podcast_id": podcast_result.data[0]["id"],
                                "podcast_name": podcast_result.data[0]["title"]
                            }
                except Exception as e:
                    logger.warning(f"Failed to fetch podcast claim: {str(e)}")

                # Get avatar URL and bio from user_profiles table
                avatar_url_raw = user_profile.get("avatar_url")
                avatar_url = self._generate_signed_url_from_r2_url(avatar_url_raw) if avatar_url_raw else None
                bio = user_profile.get("bio")

                # Get podcast info from podcast claims
                podcast_name = podcast_claim.get("podcast_name")
                podcast_id = podcast_claim.get("podcast_id")

                post["user"] = {
                    "id": post["user_id"],
                    "name": name,
                    "avatar_url": avatar_url,
                    "podcast_name": podcast_name,
                    "podcast_id": podcast_id,
                    "bio": bio,
                }
            except Exception as e:
                logger.error(f"Failed to fetch user data for post: {str(e)}")
                # Add minimal user data
                post["user"] = {
                    "id": post["user_id"],
                    "name": "Unknown User",
                    "avatar_url": None,
                    "podcast_name": None,
                    "podcast_id": None,
                    "bio": None,
                }
            
            # Format media as simple URLs array for frontend
            # Generate signed URLs from storage_path if available
            post["media_urls"] = [
                self._generate_signed_url_for_media(media) for media in post.get("post_media", [])
            ]

            # Also keep detailed media items if needed
            post["media_items"] = [
                {
                    "id": media.get("id"),
                    "url": self._generate_signed_url_for_media(media),  # Use signed URL
                    "type": media.get("type", "image"),
                    "thumbnail_url": media.get("thumbnail_url"),
                    "duration": media.get("duration"),
                    "width": media.get("width"),
                    "height": media.get("height")
                }
                for media in post.get("post_media", [])
            ]
            
            # Remove raw post_media
            if "post_media" in post:
                del post["post_media"]
            
            # Format engagement counts
            post["engagement"] = {
                "likes_count": post.get("likes_count", 0),
                "comments_count": post.get("comments_count", 0),
                "shares_count": post.get("shares_count", 0),
                "saves_count": post.get("saves_count", 0)
            }
            
            # Get user interaction status if user_id provided
            if user_id:
                # Check if liked
                like_result = self.client.service_client.table("post_likes").select("id").eq(
                    "post_id", post_id
                ).eq("user_id", user_id).execute()
                is_liked = len(like_result.data) > 0
                
                # Check if saved
                save_result = self.client.service_client.table("post_saves").select("id").eq(
                    "post_id", post_id
                ).eq("user_id", user_id).execute()
                is_saved = len(save_result.data) > 0
                
                # Format user engagement
                post["user_engagement"] = {
                    "liked": is_liked,
                    "saved": is_saved,
                    "commented": False  # TODO: Check if user has commented
                }
            else:
                post["user_engagement"] = {
                    "liked": False,
                    "saved": False,
                    "commented": False
                }
            
            # Add empty arrays for TODO items
            post["mentions"] = []  # TODO: Implement mentions
            post["hashtags"] = []  # TODO: Implement hashtags
            post["category"] = post.get("post_categories")
            
            # Ensure required fields are always present (safety check)
            if "user" not in post or not post["user"]:
                logger.warning(f"Missing user field for post {post.get('id', 'unknown')}, adding fallback")
                post["user"] = {
                    "id": post.get("user_id", "unknown"),
                    "name": "Unknown User",
                    "avatar_url": None,
                    "podcast_name": None,
                    "podcast_id": None,
                    "bio": None,
                }
            
            # Ensure media_urls is always an array
            if "media_urls" not in post:
                post["media_urls"] = []
            
            # Ensure engagement exists
            if "engagement" not in post:
                post["engagement"] = {
                    "likes_count": 0,
                    "comments_count": 0,
                    "shares_count": 0,
                    "saves_count": 0
                }
            
            # Ensure user_engagement exists
            if "user_engagement" not in post:
                post["user_engagement"] = {
                    "liked": False,
                    "saved": False,
                    "commented": False
                }
            
            return {"success": True, "data": post}
            
        except Exception as e:
            logger.error(f"Get post error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def get_feed_by_category(self, user_id: str, category_id: str, limit: int = 20, cursor: Optional[str] = None) -> Dict:
        """Get feed filtered by AI-assigned category"""
        try:
            # Get posts that match the specified category_id (AI categorized)
            query = self.client.service_client.table("posts").select(
                "*, post_media(*), post_categories(id, name, display_name, color)"
            ).eq("category_id", category_id).is_("deleted_at", None).order("created_at", desc=True)
            
            if cursor:
                query = query.lt("created_at", cursor)
                
            query = query.limit(limit)
            posts_result = query.execute()
            posts = posts_result.data
            
            if not posts:
                return {
                    "success": True,
                    "data": {
                        "posts": [],
                        "next_cursor": None,
                        "has_more": False
                    }
                }
            
            # Get unique user IDs from posts
            unique_user_ids = list(set(p["user_id"] for p in posts))
            
            # Fetch user data from auth.users
            users_data = {}
            try:
                # Fetch users one by one
                for uid in unique_user_ids:
                    try:
                        user_response = self.client.service_client.auth.admin.get_user_by_id(uid)
                        if user_response and user_response.user:
                            user = user_response.user
                            users_data[uid] = {
                                "id": user.id,
                                "email": user.email,
                                "user_metadata": user.user_metadata or {}
                            }
                    except Exception:
                        # Skip users that can't be fetched
                        pass
                        
            except Exception as e:
                logger.error(f"Failed to fetch user data for category feed: {str(e)}")
                # Continue without user data rather than failing the entire request
            
            # Get user engagement data
            post_ids = [p["id"] for p in posts]
            
            # Get likes for current user
            likes_result = self.client.service_client.table("post_likes").select(
                "post_id"
            ).in_("post_id", post_ids).eq("user_id", user_id).execute()
            liked_posts = {l["post_id"] for l in likes_result.data}
            
            # Get saves for current user
            saves_result = self.client.service_client.table("post_saves").select(
                "post_id"
            ).in_("post_id", post_ids).eq("user_id", user_id).execute()
            saved_posts = {s["post_id"] for s in saves_result.data}
            
            # Format posts with user data and interaction status
            formatted_posts = []
            for post in posts:
                try:
                    # Get user data
                    user_data = users_data.get(post["user_id"], {})
                    user_metadata = user_data.get("user_metadata", {})
                    
                    # Simple name formatting
                    name = "Unknown User"
                    if user_metadata:
                        name = (user_metadata.get("name") or
                               user_metadata.get("full_name") or
                               user_metadata.get("first_name", "Unknown User"))

                    # Generate pre-signed URL for avatar if it exists
                    avatar_url_raw = user_metadata.get("avatar_url")
                    avatar_url = self._generate_signed_url_from_r2_url(avatar_url_raw) if avatar_url_raw else None

                    # Create post structure matching backend expectations (same as get_feed)
                    formatted_post = {
                        "id": post["id"],
                        "content": post.get("content", ""),
                        "post_type": post.get("post_type", "text"),
                        "created_at": post.get("created_at"),
                        "updated_at": post.get("updated_at"),
                        "is_published": True,  # Default to True until is_published column is added
                        "is_pinned": post.get("is_pinned", False),
                        "podcast_episode_url": post.get("podcast_episode_url"),
                        "likes_count": post.get("likes_count", 0),
                        "comments_count": post.get("comments_count", 0),
                        "shares_count": post.get("shares_count", 0),
                        "saves_count": post.get("saves_count", 0),
                        "category_id": post.get("category_id"),  # Include category_id for debugging
                        "user": {
                            "id": post["user_id"],
                            "name": name,
                            "avatar_url": avatar_url,
                            "podcast_name": user_metadata.get("podcast_name"),
                            "podcast_id": user_metadata.get("podcast_id"),
                            "bio": user_metadata.get("bio"),
                        },
                        "media_urls": [
                            self._generate_signed_url_for_media(media) for media in post.get("post_media", []) if media.get("url") or media.get("storage_path")
                        ],
                        "media_items": [
                            {
                                "id": media.get("id"),
                                "url": self._generate_signed_url_for_media(media),
                                "type": media.get("type", "image"),
                                "thumbnail_url": media.get("thumbnail_url"),
                                "duration": media.get("duration"),
                                "width": media.get("width"),
                                "height": media.get("height")
                            }
                            for media in post.get("post_media", [])
                        ],
                        "engagement": {
                            "likes_count": post.get("likes_count", 0),
                            "comments_count": post.get("comments_count", 0),
                            "shares_count": post.get("shares_count", 0),
                            "saves_count": post.get("saves_count", 0)
                        },
                        "user_engagement": {
                            "liked": post["id"] in liked_posts,
                            "saved": post["id"] in saved_posts,
                            "commented": False
                        },
                        "is_liked": post["id"] in liked_posts,
                        "is_saved": post["id"] in saved_posts,
                        "is_shared": False,
                        "category": post.get("post_categories")
                    }
                    
                    formatted_posts.append(formatted_post)
                    
                except Exception as e:
                    logger.error(f"Error formatting category post {post.get('id', 'unknown')}: {e}")
                    continue
            
            next_cursor = posts[-1]["created_at"] if posts else None
            
            return {
                "success": True,
                "data": {
                    "posts": formatted_posts,
                    "next_cursor": next_cursor,
                    "has_more": len(posts) == limit
                }
            }
            
        except Exception as e:
            logger.error(f"Get feed by category error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def get_feed(self, user_id: str, limit: int = 20, cursor: Optional[str] = None, offset: Optional[int] = None) -> Dict:
        """Get feed showing all posts in the database with current user data (with event-based caching)"""
        try:
            # Check cache first (event-based + TTL validation)
            cached_result = self.feed_cache.get(user_id, limit, cursor, offset)
            if cached_result:
                logger.debug(f"Feed cache HIT for user {user_id[:8]}... - regenerating URLs")
                # Regenerate fresh pre-signed URLs (URLs in cache may be expired)
                await self._regenerate_urls_in_feed(cached_result)
                return {
                    "success": True,
                    "data": cached_result
                }

            # Cache miss - fetch fresh data
            logger.debug(f"Feed cache miss for user {user_id[:8]}..., fetching from database")

            # Show all posts from all users, not just connections
            # This creates a public feed where everyone sees all content

            # Build query - get all posts with category information
            query = self.client.service_client.table("posts").select(
                "*, post_media(*), post_categories(id, name, display_name, color)"
            ).is_("deleted_at", None).order("is_pinned", desc=True).order("created_at", desc=True).limit(limit)

            # Apply pagination - cursor takes precedence over offset
            if cursor:
                query = query.lt("created_at", cursor)
            elif offset is not None and offset > 0:
                query = query.range(offset, offset + limit - 1)

            posts_result = query.execute()
            posts = posts_result.data

            # Get user engagement data for all posts
            if posts:
                post_ids = [p["id"] for p in posts]

                # Get likes
                likes_result = self.client.service_client.table("post_likes").select(
                    "post_id"
                ).in_("post_id", post_ids).eq("user_id", user_id).execute()
                liked_posts = {l["post_id"] for l in likes_result.data}

                # Get saves
                saves_result = self.client.service_client.table("post_saves").select(
                    "post_id"
                ).in_("post_id", post_ids).eq("user_id", user_id).execute()
                saved_posts = {s["post_id"] for s in saves_result.data}

                # Get unique user IDs from posts
                unique_user_ids = list(set(p["user_id"] for p in posts))

                # Fetch user profiles using cached UserProfileService
                users_profiles_map = {}
                try:
                    # Import locally to avoid circular import
                    from user_profile_service import UserProfileService

                    profile_service = UserProfileService()
                    users_profiles = await profile_service.get_users_by_ids(unique_user_ids)

                    # Convert list to map for easier lookup
                    users_profiles_map = {user["id"]: user for user in users_profiles}

                    logger.debug(f"Fetched {len(users_profiles)} user profiles for feed (cached)")

                except Exception as e:
                    logger.error(f"Failed to fetch user profiles for feed: {str(e)}")
                    # Continue without user data rather than failing the entire request

                # Format posts with cached user profile data
                formatted_posts = []
                for post in posts:
                    try:
                        # Get cached user profile data
                        user_profile = users_profiles_map.get(post["user_id"], {})

                        # Extract user data from cached profile
                        name = user_profile.get("name", "Unknown User")
                        avatar_url = user_profile.get("avatar_url")  # Already signed in cache
                        avatar_storage_path = user_profile.get("avatar_storage_path")  # Store for URL regeneration
                        bio = user_profile.get("bio")
                        podcast_name = user_profile.get("podcast_name")
                        podcast_id = user_profile.get("podcast_id")

                        # Parallelize signed URL generation for media
                        post_media_list = post.get("post_media", [])
                        media_with_path = [media for media in post_media_list if media.get("url") or media.get("storage_path")]

                        # Generate signed URLs in parallel
                        signed_urls = await self._generate_signed_urls_parallel(post_media_list) if post_media_list else []
                        signed_urls_filtered = await self._generate_signed_urls_parallel(media_with_path) if media_with_path else []

                        # Build media_items with signed URLs and storage paths
                        media_items_formatted = []
                        for idx, media in enumerate(post_media_list):
                            media_items_formatted.append({
                                "id": media.get("id"),
                                "url": signed_urls[idx] if idx < len(signed_urls) else "",
                                "storage_path": media.get("storage_path"),  # Store for URL regeneration
                                "type": media.get("type", "image"),
                                "thumbnail_url": media.get("thumbnail_url"),
                                "duration": media.get("duration"),
                                "width": media.get("width"),
                                "height": media.get("height")
                            })

                        # Create post structure matching backend expectations
                        formatted_post = {
                            "id": post["id"],
                            "content": post.get("content", ""),
                            "post_type": post.get("post_type", "text"),  # Required field
                            "created_at": post.get("created_at"),
                            "updated_at": post.get("updated_at"),
                            "is_published": True,  # Default to True until is_published column is added
                            "is_pinned": post.get("is_pinned", False),
                            "podcast_episode_url": post.get("podcast_episode_url"),
                            "likes_count": post.get("likes_count", 0),
                            "comments_count": post.get("comments_count", 0),
                            "shares_count": post.get("shares_count", 0),
                            "saves_count": post.get("saves_count", 0),
                            "user": {
                                "id": post["user_id"],
                                "name": name,
                                "avatar_url": avatar_url,
                                "avatar_storage_path": avatar_storage_path,  # Store for URL regeneration
                                "podcast_name": podcast_name,
                                "podcast_id": podcast_id,
                                "bio": bio,
                            },
                            "media_urls": signed_urls_filtered,
                            "media_items": media_items_formatted,
                            "engagement": {
                                "likes_count": post.get("likes_count", 0),
                                "comments_count": post.get("comments_count", 0),
                                "shares_count": post.get("shares_count", 0),
                                "saves_count": post.get("saves_count", 0)
                            },
                            "user_engagement": {
                                "liked": post["id"] in liked_posts,
                                "saved": post["id"] in saved_posts,
                                "commented": False
                            },
                            "is_liked": post["id"] in liked_posts,
                            "is_saved": post["id"] in saved_posts,
                            "is_shared": False,
                            "category": post.get("post_categories")
                        }

                        # Ensure user field is always present (safety check)
                        if "user" not in formatted_post or not formatted_post["user"]:
                            logger.warning(f"Missing user field in get_feed for post {post.get('id', 'unknown')}, adding fallback")
                            formatted_post["user"] = {
                                "id": post.get("user_id", "unknown"),
                                "name": "Unknown User",
                                "avatar_url": None,
                                "podcast_name": None,
                                "podcast_id": None,
                                "bio": None,
                            }
                        
                        formatted_posts.append(formatted_post)
                        
                    except Exception as e:
                        logger.error(f"Error formatting post {post.get('id', 'unknown')}: {e}")
                        # Still add the post with minimal data to avoid breaking the frontend
                        try:
                            fallback_post = {
                                "id": post.get("id", "unknown"),
                                "content": post.get("content", ""),
                                "post_type": post.get("post_type", "text"),
                                "created_at": post.get("created_at"),
                                "updated_at": post.get("updated_at"),
                                "is_published": True,  # Default to True until is_published column is added
                                "is_pinned": post.get("is_pinned", False),
                                "podcast_episode_url": post.get("podcast_episode_url"),
                                "likes_count": 0,
                                "comments_count": 0,
                                "shares_count": 0,
                                "saves_count": 0,
                                "user": {
                                    "id": post.get("user_id", "unknown"),
                                    "name": "Unknown User",
                                    "avatar_url": None,
                                    "podcast_name": None,
                                    "podcast_id": None,
                                    "bio": None,
                                },
                                "media_urls": [],
                                "media_items": [],
                                "engagement": {
                                    "likes_count": 0,
                                    "comments_count": 0,
                                    "shares_count": 0,
                                    "saves_count": 0
                                },
                                "user_engagement": {
                                    "liked": False,
                                    "saved": False,
                                    "commented": False
                                },
                                "is_liked": False,
                                "is_saved": False,
                                "is_shared": False,
                                "category": None
                            }
                            formatted_posts.append(fallback_post)
                        except Exception as fallback_error:
                            logger.error(f"Failed to create fallback post: {fallback_error}")
                            # Skip this post if even fallback fails
                            continue
            else:
                formatted_posts = []
            
            next_cursor = posts[-1]["created_at"] if posts else None
            next_offset = None

            # Calculate next offset if offset was used
            if offset is not None:
                next_offset = offset + limit if len(posts) == limit else None

            # Prepare response data
            response_data = {
                "posts": formatted_posts,
                "next_cursor": next_cursor,
                "next_offset": next_offset,
                "has_more": len(posts) == limit,
                "total_returned": len(formatted_posts)
            }

            # Cache the result (will be automatically invalidated by database triggers)
            self.feed_cache.set(user_id, limit, cursor, offset, response_data)
            logger.debug(f"Cached feed for user {user_id[:8]}...")

            return {
                "success": True,
                "data": response_data
            }
            
        except Exception as e:
            logger.error(f"Get feed error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def update_post(self, post_id: str, user_id: str, update_data: Dict) -> Dict:
        """Update a post with full control over content and media

        Supports:
        - Update text content (including clearing with empty string)
        - Keep specific media items (via keep_media_ids)
        - Add new media items

        Media handling logic:
        - If keep_media_ids not provided: existing media unchanged
        - If keep_media_ids provided: delete media not in the list
        - New media_items always added
        """
        try:
            # Verify ownership
            post_check = self.client.service_client.table("posts").select("user_id").eq(
                "id", post_id
            ).single().execute()

            if not post_check.data or post_check.data["user_id"] != user_id:
                return {"success": False, "error": "Unauthorized"}

            # Update post fields (content, post_type, etc.)
            update_fields = {
                "updated_at": datetime.utcnow().isoformat()
            }

            if "content" in update_data:
                update_fields["content"] = update_data["content"]

            if "post_type" in update_data:
                update_fields["post_type"] = update_data["post_type"]

            if "podcast_episode_url" in update_data:
                update_fields["podcast_episode_url"] = update_data["podcast_episode_url"]

            result = self.client.service_client.table("posts").update(
                update_fields
            ).eq("id", post_id).execute()

            # Handle media operations
            if "keep_media_ids" in update_data:
                keep_media_ids = update_data["keep_media_ids"]

                # Get all current media for this post
                current_media_result = self.client.service_client.table("post_media").select("id").eq(
                    "post_id", post_id
                ).execute()

                if current_media_result.data:
                    current_media_ids = [media["id"] for media in current_media_result.data]

                    # Calculate which media to delete (current media NOT in keep list)
                    media_ids_to_delete = [mid for mid in current_media_ids if mid not in keep_media_ids]

                    # Delete media not in keep list
                    if media_ids_to_delete:
                        try:
                            self.client.service_client.table("post_media").delete().in_(
                                "id", media_ids_to_delete
                            ).eq("post_id", post_id).execute()
                            logger.info(f"Deleted {len(media_ids_to_delete)} media items from post {post_id}")
                        except Exception as e:
                            logger.error(f"Failed to delete media from post {post_id}: {str(e)}")

            # Add new media items if provided
            if "media_items" in update_data and update_data["media_items"]:
                media_items = update_data["media_items"]

                for media_item in media_items:
                    try:
                        self.client.service_client.table("post_media").insert({
                            "post_id": post_id,
                            "url": media_item.get("url"),
                            "storage_path": media_item.get("storage_path"),
                            "type": media_item.get("type", "image"),
                            "thumbnail_url": media_item.get("thumbnail_url"),
                            "duration": media_item.get("duration"),
                            "width": media_item.get("width"),
                            "height": media_item.get("height")
                        }).execute()
                        logger.info(f"Added media to post {post_id}: {media_item.get('url')}")
                    except Exception as e:
                        logger.error(f"Failed to add media to post {post_id}: {str(e)}")

            # Invalidate feed cache (application-level)
            self.feed_cache.invalidate_via_database()
            logger.info(f"Feed cache invalidated after post update: {post_id}")

            return {"success": True, "data": result.data[0] if result.data else None}

        except Exception as e:
            logger.error(f"Update post error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def delete_post(self, post_id: str, user_id: str) -> Dict:
        """Soft delete a post"""
        try:
            # Verify ownership
            post_check = self.client.service_client.table("posts").select("user_id").eq(
                "id", post_id
            ).single().execute()
            
            if not post_check.data or post_check.data["user_id"] != user_id:
                return {"success": False, "error": "Unauthorized"}
            
            # Soft delete
            result = self.client.service_client.table("posts").update({
                "deleted_at": datetime.utcnow().isoformat()
            }).eq("id", post_id).execute()

            # Invalidate feed cache (application-level)
            self.feed_cache.invalidate_via_database()
            logger.info(f"Feed cache invalidated after post deletion: {post_id}")

            return {"success": True}
            
        except Exception as e:
            logger.error(f"Delete post error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    # Interactions
    def toggle_like(self, post_id: str, user_id: str) -> Dict:
        """Like or unlike a post"""
        try:
            # Verify post exists
            post_check = self.client.service_client.table("posts").select("id").eq(
                "id", post_id
            ).is_("deleted_at", None).execute()

            if not post_check.data:
                return {"success": False, "error": "Post not found"}

            # Check if already liked
            existing = self.client.service_client.table("post_likes").select("id").eq(
                "post_id", post_id
            ).eq("user_id", user_id).execute()

            if existing.data:
                # Unlike
                self.client.service_client.table("post_likes").delete().eq(
                    "post_id", post_id
                ).eq("user_id", user_id).execute()

                # Decrement count
                self.client.service_client.rpc("decrement_post_likes", {"post_id": post_id}).execute()

                # Invalidate feed cache (application-level)
                self.feed_cache.invalidate_via_database()
                logger.info(f"Feed cache invalidated after post unlike: {post_id}")

                return {"success": True, "liked": False}
            else:
                # Like
                self.client.service_client.table("post_likes").insert({
                    "post_id": post_id,
                    "user_id": user_id
                }).execute()

                # Increment count
                self.client.service_client.rpc("increment_post_likes", {"post_id": post_id}).execute()

                # Log activity
                try:
                    from user_activity_service import get_user_activity_service
                    activity_service = get_user_activity_service()
                    asyncio.create_task(activity_service.log_activity(user_id, "post_liked", {"post_id": post_id}))
                except Exception as e:
                    logger.warning(f"Failed to log post_liked activity: {str(e)}")

                # Invalidate feed cache (application-level)
                self.feed_cache.invalidate_via_database()
                logger.info(f"Feed cache invalidated after post like: {post_id}")

                return {"success": True, "liked": True}

        except Exception as e:
            logger.error(f"Toggle like error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def add_comment(self, post_id: str, user_id: str, content: str, parent_id: Optional[str] = None) -> Dict:
        """Add a comment to a post"""
        try:
            comment = {
                "post_id": post_id,
                "user_id": user_id,
                "content": content,
                "parent_comment_id": parent_id
            }
            
            result = self.client.service_client.table("post_comments").insert(comment).execute()
            
            if result.data:
                comment_id = result.data[0]["id"]

                # Increment comment count on post
                self.client.service_client.rpc("increment_post_comments", {"post_id": post_id}).execute()

                # If reply, increment reply count on parent
                if parent_id:
                    self.client.service_client.rpc("increment_comment_replies", {"comment_id": parent_id}).execute()

                # Log activity
                try:
                    from user_activity_service import get_user_activity_service
                    activity_service = get_user_activity_service()
                    asyncio.create_task(activity_service.log_activity(user_id, "comment_created", {"comment_id": comment_id, "post_id": post_id}))
                except Exception as e:
                    logger.warning(f"Failed to log comment_created activity: {str(e)}")

                # Send email notifications (background task)
                try:
                    import asyncio
                    from background_tasks import send_activity_notification_email
                    from email_notification_service import NOTIFICATION_TYPE_POST_REPLY

                    # Get post owner
                    post_result = self.client.service_client.table("posts").select("user_id").eq("id", post_id).single().execute()

                    if post_result.data:
                        post_owner_id = post_result.data["user_id"]

                        # Notify post owner (unless they're the commenter)
                        if post_owner_id != user_id:
                            # Send email immediately as background task (non-blocking)
                            asyncio.create_task(send_activity_notification_email(
                                user_id=post_owner_id,
                                notification_type=NOTIFICATION_TYPE_POST_REPLY,
                                actor_id=user_id,
                                resource_id=post_id
                            ))

                    # If this is a reply to another comment, notify the parent comment owner
                    if parent_id:
                        parent_comment_result = self.client.service_client.table("post_comments").select("user_id").eq("id", parent_id).single().execute()

                        if parent_comment_result.data:
                            parent_comment_owner_id = parent_comment_result.data["user_id"]

                            # Don't notify if:
                            # 1. User is replying to their own comment
                            # 2. Parent comment owner is the post owner (already notified above)
                            if parent_comment_owner_id != user_id and parent_comment_owner_id != post_owner_id:
                                # Send email notification to parent comment owner
                                asyncio.create_task(send_activity_notification_email(
                                    user_id=parent_comment_owner_id,
                                    notification_type=NOTIFICATION_TYPE_POST_REPLY,
                                    actor_id=user_id,
                                    resource_id=post_id
                                ))
                                logger.info(f"Sent comment reply notification to parent comment owner {parent_comment_owner_id}")

                except Exception as e:
                    logger.warning(f"Failed to send reply notifications: {str(e)}")

                # Invalidate feed cache (application-level)
                self.feed_cache.invalidate_via_database()
                logger.info(f"Feed cache invalidated after comment creation: {comment_id}")

                return {"success": True, "data": result.data[0]}
            
            return {"success": False, "error": "Failed to add comment"}
            
        except Exception as e:
            logger.error(f"Add comment error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def edit_comment(self, comment_id: str, user_id: str, content: str) -> Dict:
        """Edit a comment"""
        try:
            # Validate that content is provided and not empty
            if not content or content.strip() == '':
                return {"success": False, "error": "Content cannot be empty"}
            
            # Update the comment content only
            result = self.client.service_client.table("post_comments") \
                .update({
                    "content": content.strip(),
                    "updated_at": "now()"  # Most tables have updated_at instead of edited_at
                }) \
                .eq("id", comment_id) \
                .eq("user_id", user_id) \
                .execute()
            
            if result.data:
                # The comment response will include updated_at to track edit time
                comment_data = result.data[0]
                # Add a computed field to indicate if the comment was edited
                if comment_data.get("created_at") and comment_data.get("updated_at"):
                    comment_data["is_edited"] = comment_data["created_at"] != comment_data["updated_at"]
                else:
                    comment_data["is_edited"] = False

                # Invalidate feed cache (application-level)
                self.feed_cache.invalidate_via_database()
                logger.info(f"Feed cache invalidated after comment edit: {comment_id}")

                return {"success": True, "data": comment_data}
            else:
                return {"success": False, "error": "Comment not found, unauthorized, or already deleted"}
                
        except Exception as e:
            logger.error(f"Edit comment error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def delete_comment(self, comment_id: str, user_id: str) -> Dict:
        """Delete a comment (soft delete)"""
        try:
            # First get the comment to check ownership and get post_id for decrementing count
            comment_result = self.client.service_client.table("post_comments") \
                .select("id, post_id, user_id, parent_comment_id") \
                .eq("id", comment_id) \
                .single() \
                .execute()
            
            if not comment_result.data:
                return {"success": False, "error": "Comment not found"}
            
            comment = comment_result.data
            
            # Check if user owns the comment
            if comment["user_id"] != user_id:
                return {"success": False, "error": "Unauthorized to delete this comment"}
            
            # Soft delete the comment
            result = self.client.service_client.table("post_comments") \
                .update({
                    "deleted_at": "now()",
                    "content": "[deleted]"  # Replace content for privacy
                }) \
                .eq("id", comment_id) \
                .eq("user_id", user_id) \
                .execute()
            
            if result.data:
                # Decrement comment count on post
                self.client.service_client.rpc("decrement_post_comments", {"post_id": comment["post_id"]}).execute()
                
                # If it was a reply, decrement reply count on parent
                if comment.get("parent_comment_id"):
                    self.client.service_client.rpc("decrement_comment_replies", {"comment_id": comment["parent_comment_id"]}).execute()

                # Invalidate feed cache (application-level)
                self.feed_cache.invalidate_via_database()
                logger.info(f"Feed cache invalidated after comment deletion: {comment_id}")

                logger.info(f"User {user_id} deleted comment {comment_id}")
                return {"success": True, "message": "Comment deleted successfully"}
            else:
                return {"success": False, "error": "Failed to delete comment"}
                
        except Exception as e:
            logger.error(f"Delete comment error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def get_comments(self, post_id: str, user_id: Optional[str] = None, limit: int = 20, cursor: Optional[str] = None) -> Dict:
        """Get comments for a post"""
        try:
            query = self.client.service_client.table("post_comments").select(
                "*"
            ).eq("post_id", post_id).is_("parent_comment_id", None).is_(
                "deleted_at", None
            ).order("created_at", desc=True).limit(limit)
            
            if cursor:
                query = query.lt("created_at", cursor)
            
            result = query.execute()
            comments = result.data
            
            if comments:
                # Get unique user IDs from comments
                unique_user_ids = list(set(c["user_id"] for c in comments))
                
                # Fetch user data from auth.users, user_signup_tracking, and user_profiles
                users_data = {}
                signup_tracking_data = {}
                podcast_claims_data = {}
                user_profiles_data = {}

                try:
                    # Fetch auth user data one by one to avoid loading all users
                    for uid in unique_user_ids:
                        try:
                            user_response = self.client.service_client.auth.admin.get_user_by_id(uid)
                            if user_response and user_response.user:
                                user = user_response.user
                                users_data[uid] = {
                                    "id": user.id,
                                    "email": user.email,
                                    "user_metadata": user.user_metadata or {}
                                }
                        except Exception:
                            # Skip users that can't be fetched
                            pass

                    # Batch fetch user profile data (includes avatar_url)
                    if unique_user_ids:
                        profiles_result = self.client.service_client.table("user_profiles").select(
                            "user_id, avatar_url"
                        ).in_("user_id", unique_user_ids).execute()

                        if profiles_result.data:
                            for profile in profiles_result.data:
                                user_profiles_data[profile["user_id"]] = profile
                    
                    # Fetch additional user data from user_signup_tracking
                    if unique_user_ids:
                        signup_result = self.client.service_client.table("user_signup_tracking") \
                            .select("user_id, email, name") \
                            .in_("user_id", unique_user_ids) \
                            .execute()
                        
                        if signup_result.data:
                            for signup_user in signup_result.data:
                                signup_tracking_data[signup_user["user_id"]] = signup_user
                        
                        # Fetch podcast claims for all users
                        claims_result = self.client.service_client.table("podcast_claims") \
                            .select("user_id, listennotes_id") \
                            .in_("user_id", unique_user_ids) \
                            .eq("is_verified", True) \
                            .eq("claim_status", "verified") \
                            .execute()
                        
                        if claims_result.data:
                            # Get all unique listennotes_ids
                            listennotes_ids = [claim["listennotes_id"] for claim in claims_result.data]
                            
                            # Fetch podcast info for all claims
                            if listennotes_ids:
                                podcasts_result = self.client.service_client.table("podcasts") \
                                    .select("id, listennotes_id, title") \
                                    .in_("listennotes_id", listennotes_ids) \
                                    .execute()
                                
                                if podcasts_result.data:
                                    # Create lookup map
                                    podcasts_map = {p["listennotes_id"]: p for p in podcasts_result.data}
                                    
                                    # Map claims to podcast data
                                    for claim in claims_result.data:
                                        podcast = podcasts_map.get(claim["listennotes_id"])
                                        if podcast:
                                            podcast_claims_data[claim["user_id"]] = {
                                                "podcast_id": podcast["id"],
                                                "podcast_name": podcast["title"]
                                            }
                                
                except Exception as e:
                    logger.error(f"Failed to fetch user data for comments: {str(e)}")

                # Fetch replies for all parent comments
                comment_ids = [c["id"] for c in comments]
                replies_result = self.client.service_client.table("post_comments").select(
                    "*"
                ).in_("parent_comment_id", comment_ids).is_(
                    "deleted_at", None
                ).order("created_at", desc=False).execute()  # Order replies chronologically (oldest first)

                replies = replies_result.data or []

                # Batch fetch data for reply authors that aren't already fetched
                if replies:
                    reply_user_ids = list(set(r["user_id"] for r in replies))
                    new_reply_user_ids = [uid for uid in reply_user_ids if uid not in users_data]

                    if new_reply_user_ids:
                        # Batch fetch auth user data for new reply authors
                        for uid in new_reply_user_ids:
                            try:
                                user_response = self.client.service_client.auth.admin.get_user_by_id(uid)
                                if user_response and user_response.user:
                                    user = user_response.user
                                    users_data[uid] = {
                                        "id": user.id,
                                        "email": user.email,
                                        "user_metadata": user.user_metadata or {}
                                    }
                            except Exception:
                                pass

                        # Batch fetch user profile data for new reply authors (includes avatar_url)
                        profiles_result = self.client.service_client.table("user_profiles").select(
                            "user_id, avatar_url"
                        ).in_("user_id", new_reply_user_ids).execute()

                        if profiles_result.data:
                            for profile in profiles_result.data:
                                user_profiles_data[profile["user_id"]] = profile

                        # Batch fetch signup tracking data for new reply authors
                        signup_result = self.client.service_client.table("user_signup_tracking") \
                            .select("user_id, email, name") \
                            .in_("user_id", new_reply_user_ids) \
                            .execute()

                        if signup_result.data:
                            for signup_user in signup_result.data:
                                signup_tracking_data[signup_user["user_id"]] = signup_user

                        # Batch fetch podcast claims for new reply authors (FIX N+1 QUERY PROBLEM)
                        claims_result = self.client.service_client.table("podcast_claims") \
                            .select("user_id, listennotes_id") \
                            .in_("user_id", new_reply_user_ids) \
                            .eq("is_verified", True) \
                            .eq("claim_status", "verified") \
                            .execute()

                        if claims_result.data:
                            # Get all unique listennotes_ids
                            listennotes_ids = [claim["listennotes_id"] for claim in claims_result.data]

                            # Batch fetch podcast info for all claims
                            if listennotes_ids:
                                podcasts_result = self.client.service_client.table("podcasts") \
                                    .select("id, listennotes_id, title") \
                                    .in_("listennotes_id", listennotes_ids) \
                                    .execute()

                                if podcasts_result.data:
                                    # Create lookup map
                                    podcasts_map = {p["listennotes_id"]: p for p in podcasts_result.data}

                                    # Map claims to podcast data
                                    for claim in claims_result.data:
                                        podcast = podcasts_map.get(claim["listennotes_id"])
                                        if podcast:
                                            podcast_claims_data[claim["user_id"]] = {
                                                "podcast_id": podcast["id"],
                                                "podcast_name": podcast["title"]
                                            }

                # Generate presigned URLs for all avatars
                import os
                from media_service import MediaService
                media_service = MediaService()
                r2_public_url = os.getenv('R2_PUBLIC_URL', '')

                signed_avatar_urls = {}
                for uid, profile in user_profiles_data.items():
                    avatar_url = profile.get("avatar_url")
                    if avatar_url and r2_public_url:
                        try:
                            # Extract storage path from the URL
                            storage_path = avatar_url.replace(f"{r2_public_url}/", "")
                            # Generate signed URL with 1 hour expiry
                            signed_url = media_service.generate_signed_url(storage_path, expiry=3600)
                            signed_avatar_urls[uid] = signed_url
                        except Exception as e:
                            logger.warning(f"Failed to generate signed URL for avatar {avatar_url}: {e}")
                            signed_avatar_urls[uid] = None
                    else:
                        signed_avatar_urls[uid] = None

                # Batch fetch comment likes for current user
                comment_likes_set = set()
                if user_id:
                    all_comment_ids = [c["id"] for c in comments] + [r["id"] for r in replies]
                    if all_comment_ids:
                        try:
                            likes_result = self.client.service_client.table("comment_likes").select(
                                "comment_id"
                            ).eq("user_id", user_id).in_("comment_id", all_comment_ids).execute()

                            if likes_result.data:
                                comment_likes_set = set(like["comment_id"] for like in likes_result.data)
                        except Exception as e:
                            logger.error(f"Failed to fetch comment likes: {str(e)}")

                # Group replies by parent_comment_id
                replies_by_parent = {}
                for reply in replies:
                    parent_id = reply["parent_comment_id"]
                    if parent_id not in replies_by_parent:
                        replies_by_parent[parent_id] = []
                    replies_by_parent[parent_id].append(reply)

                # Format comments with user data
                formatted_comments = []
                for comment in comments:
                    user_data = users_data.get(comment["user_id"], {})
                    user_metadata = user_data.get("user_metadata", {})
                    signup_data = signup_tracking_data.get(comment["user_id"], {})
                    podcast_claim = podcast_claims_data.get(comment["user_id"], {})
                    
                    # Get user profile data from multiple sources (signup_tracking takes priority)
                    name = (signup_data.get("name") or 
                           user_metadata.get("name") or 
                           user_metadata.get("full_name") or 
                           user_metadata.get("first_name") or
                           "Unknown User")
                    
                    # If still no name, try email fallback
                    if name == "Unknown User":
                        email = signup_data.get("email") or user_data.get("email")
                        if email:
                            name = email.split('@')[0]

                    # Get avatar_url from presigned URLs
                    avatar_url = signed_avatar_urls.get(comment["user_id"])
                    # Get bio from auth metadata only
                    bio = user_metadata.get("bio")
                    
                    # Get podcast info from claims (default to None if not found)
                    podcast_name = podcast_claim.get("podcast_name", None)
                    podcast_id = podcast_claim.get("podcast_id", None)
                    
                    # TODO: Add actual connection status checking
                    connection_status = None
                    
                    # Check if comment has been edited
                    is_edited = False
                    if comment.get("created_at") and comment.get("updated_at"):
                        is_edited = comment["created_at"] != comment["updated_at"]
                    
                    # Format replies for this comment
                    formatted_replies = []
                    comment_replies = replies_by_parent.get(comment["id"], [])
                    for reply in comment_replies:
                        reply_user_data = users_data.get(reply["user_id"], {})
                        reply_user_metadata = reply_user_data.get("user_metadata", {})
                        reply_signup_data = signup_tracking_data.get(reply["user_id"], {})
                        reply_podcast_claim = podcast_claims_data.get(reply["user_id"], {})

                        reply_name = (reply_signup_data.get("name") or
                                     reply_user_metadata.get("name") or
                                     reply_user_metadata.get("full_name") or
                                     reply_user_metadata.get("first_name") or
                                     "Unknown User")

                        if reply_name == "Unknown User":
                            reply_email = reply_signup_data.get("email") or reply_user_data.get("email")
                            if reply_email:
                                reply_name = reply_email.split('@')[0]

                        # Get avatar_url from presigned URLs
                        reply_avatar_url = signed_avatar_urls.get(reply["user_id"])

                        reply_is_edited = False
                        if reply.get("created_at") and reply.get("updated_at"):
                            reply_is_edited = reply["created_at"] != reply["updated_at"]

                        formatted_reply = {
                            **reply,
                            "created_at": reply.get("created_at"),
                            "updated_at": reply.get("updated_at"),
                            "user": {
                                "name": reply_name,
                                "avatar_url": reply_avatar_url,
                                "podcast_name": reply_podcast_claim.get("podcast_name"),
                                "podcast_id": reply_podcast_claim.get("podcast_id"),
                                "connection_status": None
                            },
                            "is_edited": reply_is_edited,
                            "edited_at": reply.get("updated_at") if reply_is_edited else None,
                            "is_liked": reply["id"] in comment_likes_set
                        }
                        formatted_replies.append(formatted_reply)

                    formatted_comment = {
                        **comment,
                        "created_at": comment.get("created_at"),
                        "updated_at": comment.get("updated_at"),
                        "user": {
                            "name": name,
                            "avatar_url": avatar_url,
                            "podcast_name": podcast_name,
                            "podcast_id": podcast_id,
                            "connection_status": connection_status
                        },
                        "is_edited": is_edited,
                        "edited_at": comment.get("updated_at") if is_edited else None,
                        "is_liked": comment["id"] in comment_likes_set,
                        "replies": formatted_replies
                    }

                    formatted_comments.append(formatted_comment)
            else:
                formatted_comments = []
            
            return {
                "success": True,
                "data": {
                    "comments": formatted_comments,
                    "next_cursor": comments[-1]["created_at"] if comments else None,
                    "has_more": len(comments) == limit
                }
            }
            
        except Exception as e:
            logger.error(f"Get comments error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def toggle_save(self, post_id: str, user_id: str) -> Dict:
        """Save or unsave a post"""
        try:
            # Check if already saved
            existing = self.client.service_client.table("post_saves").select("id").eq(
                "post_id", post_id
            ).eq("user_id", user_id).execute()
            
            if existing.data:
                # Unsave
                self.client.service_client.table("post_saves").delete().eq(
                    "post_id", post_id
                ).eq("user_id", user_id).execute()
                
                # Decrement count
                self.client.service_client.rpc("decrement_post_saves", {"post_id": post_id}).execute()
                
                return {"success": True, "saved": False}
            else:
                # Save
                self.client.service_client.table("post_saves").insert({
                    "post_id": post_id,
                    "user_id": user_id
                }).execute()

                # Increment count
                self.client.service_client.rpc("increment_post_saves", {"post_id": post_id}).execute()

                # Log activity
                try:
                    from user_activity_service import get_user_activity_service
                    activity_service = get_user_activity_service()
                    asyncio.create_task(activity_service.log_activity(user_id, "post_saved", {"post_id": post_id}))
                except Exception as e:
                    logger.warning(f"Failed to log post_saved activity: {str(e)}")

                return {"success": True, "saved": True}
                
        except Exception as e:
            logger.error(f"Toggle save error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def share_post(self, post_id: str, user_id: str, share_type: str = "internal") -> Dict:
        """Share a post"""
        try:
            # Record share
            self.client.service_client.table("post_shares").insert({
                "post_id": post_id,
                "user_id": user_id,
                "share_type": share_type
            }).execute()

            # Increment count
            self.client.service_client.rpc("increment_post_shares", {"post_id": post_id}).execute()

            return {"success": True}

        except Exception as e:
            logger.error(f"Share post error: {str(e)}")
            return {"success": False, "error": str(e)}

    def toggle_comment_like(self, comment_id: str, user_id: str) -> Dict:
        """Like or unlike a comment"""
        try:
            # Verify comment exists
            comment_check = self.client.service_client.table("post_comments").select("id").eq(
                "id", comment_id
            ).is_("deleted_at", None).execute()

            if not comment_check.data:
                return {"success": False, "error": "Comment not found"}

            # Check if already liked
            existing = self.client.service_client.table("comment_likes").select("id").eq(
                "comment_id", comment_id
            ).eq("user_id", user_id).execute()

            if existing.data:
                # Unlike
                self.client.service_client.table("comment_likes").delete().eq(
                    "comment_id", comment_id
                ).eq("user_id", user_id).execute()

                # Decrement count
                self.client.service_client.rpc("decrement_comment_likes", {"comment_id": comment_id}).execute()

                # Invalidate feed cache (application-level)
                self.feed_cache.invalidate_via_database()
                logger.info(f"Feed cache invalidated after comment unlike: {comment_id}")

                return {"success": True, "liked": False}
            else:
                # Like
                self.client.service_client.table("comment_likes").insert({
                    "comment_id": comment_id,
                    "user_id": user_id
                }).execute()

                # Increment count
                self.client.service_client.rpc("increment_comment_likes", {"comment_id": comment_id}).execute()

                # Log activity
                try:
                    from user_activity_service import get_user_activity_service
                    activity_service = get_user_activity_service()
                    asyncio.create_task(activity_service.log_activity(user_id, "comment_liked", {"comment_id": comment_id}))
                except Exception as e:
                    logger.warning(f"Failed to log comment_liked activity: {str(e)}")

                # Invalidate feed cache (application-level)
                self.feed_cache.invalidate_via_database()
                logger.info(f"Feed cache invalidated after comment like: {comment_id}")

                return {"success": True, "liked": True}

        except Exception as e:
            logger.error(f"Toggle comment like error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    # Network/Connections
    def send_connection_request(self, follower_id: str, following_id: str) -> Dict:
        """Send a connection request"""
        try:
            # Check if connection already exists
            existing = self.client.service_client.table("user_connections").select("id, status").eq(
                "follower_id", follower_id
            ).eq("following_id", following_id).execute()
            
            if existing.data:
                status = existing.data[0]["status"]
                if status == "accepted":
                    return {"success": False, "error": "Already connected"}
                elif status == "pending":
                    return {"success": False, "error": "Request already pending"}
            
            # Create connection request
            result = self.client.service_client.table("user_connections").insert({
                "follower_id": follower_id,
                "following_id": following_id,
                "status": "pending"
            }).execute()
            
            return {"success": True, "data": result.data[0] if result.data else None}
            
        except Exception as e:
            logger.error(f"Send connection request error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def accept_connection(self, connection_id: str, user_id: str) -> Dict:
        """Accept a connection request"""
        try:
            # Verify the connection request is for this user
            check = self.client.service_client.table("user_connections").select(
                "*"
            ).eq("id", connection_id).single().execute()
            
            if not check.data or check.data["following_id"] != user_id:
                return {"success": False, "error": "Unauthorized"}
            
            # Accept connection
            result = self.client.service_client.table("user_connections").update({
                "status": "accepted",
                "accepted_at": datetime.utcnow().isoformat()
            }).eq("id", connection_id).execute()
            
            return {"success": True}
            
        except Exception as e:
            logger.error(f"Accept connection error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def get_connections(self, user_id: str, status: str = "accepted", limit: int = 20, cursor: Optional[str] = None) -> Dict:
        """Get user connections"""
        try:
            # For pending connections (connection requests), we want connections where
            # other users are requesting to follow this user (following_id = user_id)
            # For accepted connections, we want connections where this user is following others
            # (follower_id = user_id) OR others are following this user (following_id = user_id)
            
            if status == "pending":
                # Connection requests: others requesting to follow this user
                query = self.client.service_client.table("user_connections").select(
                    "*"
                ).eq("following_id", user_id).eq("status", status).order(
                    "created_at", desc=True
                ).limit(limit)
            else:
                # Accepted connections: this user following others
                query = self.client.service_client.table("user_connections").select(
                    "*"
                ).eq("follower_id", user_id).eq("status", status).order(
                    "created_at", desc=True
                ).limit(limit)
            
            if cursor:
                query = query.lt("created_at", cursor)
            
            result = query.execute()
            
            return {
                "success": True,
                "data": {
                    "connections": result.data,
                    "next_cursor": result.data[-1]["created_at"] if result.data else None,
                    "has_more": len(result.data) == limit
                }
            }
            
        except Exception as e:
            logger.error(f"Get connections error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def get_suggested_creators(self, user_id: str, limit: int = 10) -> Dict:
        """Get suggested creators to follow"""
        try:
            # For MVP: Get users who have created posts (active creators) that the user is not following
            # Future: Add recommendation algorithm based on interests, mutual connections, etc.
            
            # Get current connections (users this user is following)
            connections = self.client.service_client.table("user_connections").select(
                "following_id"
            ).eq("follower_id", user_id).execute()
            
            connected_ids = [c["following_id"] for c in connections.data] if connections.data else []
            connected_ids.append(user_id)  # Exclude self
            
            # Get users who have created posts (active creators) - excluding those already connected
            active_creators = self.client.service_client.table("posts").select(
                "user_id"
            ).not_.in_("user_id", connected_ids).is_("deleted_at", None).execute()
            
            if not active_creators.data:
                return {"success": True, "data": []}
            
            # Get unique user IDs and limit them
            unique_user_ids = list(set([p["user_id"] for p in active_creators.data]))[:limit]
            
            # Get user details from auth for the suggested creators
            suggestions = []
            try:
                for uid in unique_user_ids:
                    try:
                        user_response = self.client.service_client.auth.admin.get_user_by_id(uid)
                        if user_response and user_response.user:
                            user = user_response.user
                            user_metadata = user.user_metadata or {}
                            suggestions.append({
                                "user_id": uid,
                                "email": user.email,
                                "user_metadata": user_metadata,
                                "podcast_name": podcast_name,
                                "reason": "Active creator"  # Simple reason for now
                            })
                    except Exception:
                        # Skip users that can't be fetched
                        continue
                        
                    # Break early if we have enough suggestions
                    if len(suggestions) >= limit:
                        break
                        
            except Exception as e:
                logger.error(f"Failed to fetch user details for suggestions: {str(e)}")
                # Return empty list rather than failing entirely
                return {"success": True, "data": []}
            
            return {"success": True, "data": suggestions}
            
        except Exception as e:
            logger.error(f"Get suggested creators error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def get_saved_posts(self, user_id: str, limit: int = 20, cursor: Optional[str] = None) -> Dict:
        """Get posts saved by a user"""
        try:
            # Get saved post IDs and when they were saved
            query = self.client.service_client.table("post_saves").select(
                "post_id, created_at"
            ).eq("user_id", user_id)
            
            # Apply cursor pagination
            if cursor:
                query = query.lt("created_at", cursor)
            
            # Order by when saved (newest first) and limit
            query = query.order("created_at", desc=True).limit(limit)
            saves_result = query.execute()
            
            if not saves_result.data:
                return {
                    "success": True,
                    "data": {
                        "posts": [],
                        "next_cursor": None,
                        "has_more": False
                    }
                }
            
            # Get the post IDs and saved dates
            post_ids = [save["post_id"] for save in saves_result.data]
            saved_dates = {save["post_id"]: save["created_at"] for save in saves_result.data}
            
            # Get full post details for the saved posts
            posts_query = self.client.service_client.table("posts").select(
                "*, post_media(*), post_categories(id, name, display_name, color)"
            ).in_("id", post_ids).is_("deleted_at", None)
            
            posts_result = posts_query.execute()
            posts_data = posts_result.data or []
            
            # Get user data for all posts
            if posts_data:
                # Get unique user IDs from posts
                unique_user_ids = list(set(p["user_id"] for p in posts_data))

                # Fetch user data from auth.users, user_profiles, and podcast_claims
                users_data = {}
                user_profiles = {}
                podcast_claims_data = {}
                try:
                    # Fetch users one by one to avoid loading all users
                    for uid in unique_user_ids:
                        try:
                            user_response = self.client.service_client.auth.admin.get_user_by_id(uid)
                            if user_response and user_response.user:
                                user = user_response.user
                                users_data[uid] = {
                                    "id": user.id,
                                    "email": user.email,
                                    "user_metadata": user.user_metadata or {}
                                }
                        except Exception:
                            # Skip users that can't be fetched
                            pass

                    # Batch fetch user profiles for avatar URLs and bio
                    if unique_user_ids:
                        profiles_result = self.client.service_client.table("user_profiles").select(
                            "user_id, avatar_url, bio"
                        ).in_("user_id", unique_user_ids).execute()

                        if profiles_result.data:
                            for profile in profiles_result.data:
                                user_profiles[profile["user_id"]] = profile

                        # Batch fetch podcast claims for all users (FIX N+1 QUERY PROBLEM)
                        claims_result = self.client.service_client.table("podcast_claims") \
                            .select("user_id, listennotes_id") \
                            .in_("user_id", unique_user_ids) \
                            .eq("is_verified", True) \
                            .eq("claim_status", "verified") \
                            .execute()

                        if claims_result.data:
                            # Get all unique listennotes_ids
                            listennotes_ids = [claim["listennotes_id"] for claim in claims_result.data]

                            # Batch fetch podcast info for all claims
                            if listennotes_ids:
                                podcasts_result = self.client.service_client.table("podcasts") \
                                    .select("id, listennotes_id, title") \
                                    .in_("listennotes_id", listennotes_ids) \
                                    .execute()

                                if podcasts_result.data:
                                    # Create lookup map
                                    podcasts_map = {p["listennotes_id"]: p for p in podcasts_result.data}

                                    # Map claims to podcast data
                                    for claim in claims_result.data:
                                        podcast = podcasts_map.get(claim["listennotes_id"])
                                        if podcast:
                                            podcast_claims_data[claim["user_id"]] = {
                                                "podcast_id": podcast["id"],
                                                "podcast_name": podcast["title"]
                                            }

                except Exception as e:
                    logger.error(f"Failed to fetch user data for saved posts: {str(e)}")
                    # Continue without user data rather than failing the entire request

                # Get user engagement data for all posts
                user_liked = self.client.service_client.table("post_likes").select("post_id").in_(
                    "post_id", post_ids
                ).eq("user_id", user_id).execute()
                liked_posts = {l["post_id"] for l in user_liked.data}
                
                # Format posts
                formatted_posts = []
                for post in posts_data:
                    try:
                        # Get user data
                        user_data = users_data.get(post["user_id"], {})
                        user_metadata = user_data.get("user_metadata", {})
                        user_profile = user_profiles.get(post["user_id"], {})

                        # Simple name formatting
                        name = "Unknown User"
                        if user_metadata:
                            name = (user_metadata.get("name") or
                                   user_metadata.get("full_name") or
                                   user_metadata.get("first_name", "Unknown User"))

                        # Get avatar URL and bio from user_profiles table
                        avatar_url_raw = user_profile.get("avatar_url")
                        avatar_url = self._generate_signed_url_from_r2_url(avatar_url_raw) if avatar_url_raw else None
                        bio = user_profile.get("bio")

                        # Get podcast info from pre-fetched podcast claims data (avoids N+1 query)
                        podcast_claim = podcast_claims_data.get(post["user_id"], {})
                        podcast_name = podcast_claim.get("podcast_name")
                        podcast_id = podcast_claim.get("podcast_id")

                        # Create post structure matching backend expectations
                        formatted_post = {
                            "id": post["id"],
                            "content": post.get("content", ""),
                            "post_type": post.get("post_type", "text"),
                            "created_at": post.get("created_at"),
                            "updated_at": post.get("updated_at"),
                            "is_published": True,  # Default to True until is_published column is added
                            "is_pinned": post.get("is_pinned", False),
                            "podcast_episode_url": post.get("podcast_episode_url"),
                            "likes_count": post.get("likes_count", 0),
                            "comments_count": post.get("comments_count", 0),
                            "shares_count": post.get("shares_count", 0),
                            "saves_count": post.get("saves_count", 0),
                            "user": {
                                "id": post["user_id"],
                                "name": name,
                                "avatar_url": avatar_url,
                                "podcast_name": podcast_name,
                                "podcast_id": podcast_id,
                                "bio": bio,
                            },
                            "media_urls": [
                                self._generate_signed_url_for_media(media) for media in post.get("post_media", []) if media.get("url") or media.get("storage_path")
                            ],
                            "media_items": [
                                {
                                    "id": media.get("id"),
                                    "url": self._generate_signed_url_for_media(media),
                                    "type": media.get("type", "image"),
                                    "thumbnail_url": media.get("thumbnail_url"),
                                    "duration": media.get("duration"),
                                    "width": media.get("width"),
                                    "height": media.get("height")
                                }
                                for media in post.get("post_media", [])
                            ],
                            "engagement": {
                                "likes_count": post.get("likes_count", 0),
                                "comments_count": post.get("comments_count", 0),
                                "shares_count": post.get("shares_count", 0),
                                "saves_count": post.get("saves_count", 0)
                            },
                            "user_engagement": {
                                "liked": post["id"] in liked_posts,
                                "saved": True,  # Always true for saved posts
                                "commented": False
                            },
                            "is_liked": post["id"] in liked_posts,
                            "is_saved": True,  # Always true for saved posts
                            "is_shared": False,
                            "saved_at": saved_dates.get(post["id"]),  # When the user saved this post
                            "category": post.get("post_categories")
                        }

                        # Ensure user field is always present (safety check)
                        if "user" not in formatted_post or not formatted_post["user"]:
                            logger.warning(f"Missing user field in get_saved_posts for post {post.get('id', 'unknown')}, adding fallback")
                            formatted_post["user"] = {
                                "id": post.get("user_id", "unknown"),
                                "name": "Unknown User",
                                "avatar_url": None,
                                "podcast_name": None,
                                "podcast_id": None,
                                "bio": None,
                            }
                        
                        formatted_posts.append(formatted_post)
                        
                    except Exception as e:
                        logger.error(f"Error formatting saved post {post.get('id', 'unknown')}: {e}")
                        continue
                
                # Sort posts by saved date to maintain order
                formatted_posts.sort(key=lambda p: p.get("saved_at", ""), reverse=True)
                
            else:
                formatted_posts = []
            
            return {
                "success": True,
                "data": {
                    "posts": formatted_posts,
                    "next_cursor": saves_result.data[-1]["created_at"] if saves_result.data else None,
                    "has_more": len(saves_result.data) == limit
                }
            }
            
        except Exception as e:
            logger.error(f"Get saved posts error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def get_user_posts(self, current_user_id: str, author_id: str, limit: int = 20, offset: int = 0) -> Dict:
        """Get posts created by a specific user"""
        try:
            # Build base query
            query = self.client.service_client.table("posts").select(
                """
                *,
                post_media (*),
                post_likes (*),
                post_saves (*),
                post_categories(id, name, display_name, color)
                """
            ).eq("user_id", author_id)
            
            # If viewing someone else's posts, only show published
            # TODO: Uncomment when is_published column is added to database
            # if current_user_id != author_id:
            #     query = query.eq("is_published", True)
            
            # Order and apply pagination
            query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
            result = query.execute()
            
            # Get user data for the author once (since all posts are from same user)
            user_data = {}
            signup_data = {}
            user_profile = {}
            try:
                # Fetch auth user data
                user_response = self.client.service_client.auth.admin.get_user_by_id(author_id)
                if user_response and user_response.user:
                    user = user_response.user
                    user_data = {
                        "id": user.id,
                        "email": user.email,
                        "user_metadata": user.user_metadata or {}
                    }

                # Fetch additional user data from user_signup_tracking
                signup_result = self.client.service_client.table("user_signup_tracking") \
                    .select("user_id, email, name") \
                    .eq("user_id", author_id) \
                    .single() \
                    .execute()

                if signup_result.data:
                    signup_data = signup_result.data

                # Fetch user profile for avatar and bio
                profile_result = self.client.service_client.table("user_profiles").select(
                    "user_id, avatar_url, bio"
                ).eq("user_id", author_id).single().execute()

                if profile_result.data:
                    user_profile = profile_result.data
            except Exception as e:
                logger.warning(f"Could not fetch user data for author {author_id}: {e}")

            # Get user profile data from multiple sources
            user_metadata = user_data.get("user_metadata", {})
            name = (signup_data.get("name") or
                   user_metadata.get("name") or
                   user_metadata.get("full_name") or
                   user_metadata.get("first_name") or
                   signup_data.get("first_name") or
                   "Unknown User")

            # If still no name, try email fallback
            if name == "Unknown User":
                email = signup_data.get("email") or user_data.get("email")
                if email:
                    name = email.split('@')[0]

            # Get avatar_url and bio from user_profiles table
            avatar_url_raw = user_profile.get("avatar_url")
            avatar_url = self._generate_signed_url_from_r2_url(avatar_url_raw) if avatar_url_raw else None
            bio = user_profile.get("bio")
            
            # Get podcast info once for this user
            podcast_name = None
            podcast_id = None
            try:
                claims_result = self.client.service_client.table("podcast_claims") \
                    .select("listennotes_id") \
                    .eq("user_id", author_id) \
                    .eq("is_verified", True) \
                    .eq("claim_status", "verified") \
                    .limit(1) \
                    .execute()
                
                if claims_result.data:
                    listennotes_id = claims_result.data[0]["listennotes_id"]
                    
                    podcast_result = self.client.service_client.table("podcasts") \
                        .select("id, title") \
                        .eq("listennotes_id", listennotes_id) \
                        .single() \
                        .execute()
                    
                    if podcast_result.data:
                        podcast_id = podcast_result.data["id"]
                        podcast_name = podcast_result.data["title"]
            except Exception as e:
                logger.warning(f"Could not get claimed podcast for user {author_id}: {e}")

            # Batch fetch user engagement for all posts (FIX N+1 QUERY PROBLEM)
            liked_posts = set()
            saved_posts = set()
            if result.data:
                post_ids = [p["id"] for p in result.data]

                # Batch fetch likes
                likes_result = self.client.service_client.table("post_likes").select(
                    "post_id"
                ).in_("post_id", post_ids).eq("user_id", current_user_id).execute()
                liked_posts = {l["post_id"] for l in likes_result.data}

                # Batch fetch saves
                saves_result = self.client.service_client.table("post_saves").select(
                    "post_id"
                ).in_("post_id", post_ids).eq("user_id", current_user_id).execute()
                saved_posts = {s["post_id"] for s in saves_result.data}

            posts = []
            for post in result.data or []:
                # Extract media URLs from post_media (same as feed format)
                # Generate signed URLs from storage_path
                media_items_raw = post.get("post_media", [])
                media_urls = [self._generate_signed_url_for_media(item) for item in media_items_raw if item.get("url") or item.get("storage_path")]

                # Format media_items with signed URLs
                media_items = [
                    {
                        "id": media.get("id"),
                        "url": self._generate_signed_url_for_media(media),
                        "type": media.get("type", "image"),
                        "thumbnail_url": media.get("thumbnail_url"),
                        "duration": media.get("duration"),
                        "width": media.get("width"),
                        "height": media.get("height")
                    }
                    for media in media_items_raw
                ]

                formatted_post = {
                    "id": post["id"],
                    "content": post["content"],
                    "post_type": post.get("post_type", "text"),
                    "is_pinned": post.get("is_pinned", False),
                    "media_items": media_items,
                    "media_urls": media_urls,  # Add media_urls for compatibility
                    "created_at": post["created_at"],
                    "updated_at": post["updated_at"],
                    "likes_count": post.get("likes_count", 0),
                    "comments_count": post.get("comments_count", 0),
                    "shares_count": post.get("shares_count", 0),
                    "saves_count": post.get("saves_count", 0),
                    "user": {
                        "id": post.get("user_id", author_id),
                        "name": name,
                        "avatar_url": avatar_url,
                        "podcast_name": podcast_name,
                        "podcast_id": podcast_id,
                        "bio": bio,
                    },
                    "is_liked": post["id"] in liked_posts,
                    "is_saved": post["id"] in saved_posts,
                    "is_shared": False,
                    "category": post.get("post_categories")
                }
                
                # Ensure required fields are always present (safety check)
                if "user" not in formatted_post or not formatted_post["user"]:
                    logger.warning(f"Missing user field in get_user_posts for post {post.get('id', 'unknown')}, adding fallback")
                    formatted_post["user"] = {
                        "id": post.get("user_id", author_id),
                        "name": name,
                        "avatar_url": avatar_url,
                        "podcast_name": podcast_name,
                        "podcast_id": podcast_id,
                        "bio": bio,
                    }
                
                posts.append(formatted_post)
            
            return {
                "success": True,
                "data": {
                    "posts": posts,
                    "has_more": len(result.data) == limit,
                    "total_returned": len(posts),
                    "next_offset": offset + limit if len(result.data) == limit else None,
                    "offset": offset,
                    "limit": limit
                }
            }
            
        except Exception as e:
            logger.error(f"Get user posts error: {str(e)}")
            return {"success": False, "error": str(e)}