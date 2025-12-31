"""
Resources Service - Handles resources, experts, and partner deals
Implements premium video access control as specified
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
import logging
import re
import os

from supabase_client import get_supabase_client
from access_control import get_user_subscription_status
from article_content_service import article_content_service
from action_guide_service import action_guide_service

logger = logging.getLogger(__name__)


class ResourcesService:
    def __init__(self):
        self.supabase_client = get_supabase_client()
        self.supabase = self.supabase_client.service_client

        # Get bucket names from environment (required)
        self.partners_bucket = os.getenv("R2_PARTNERS_BUCKET_NAME")
        if not self.partners_bucket:
            raise ValueError(
                "R2_PARTNERS_BUCKET_NAME environment variable is required"
            )

        self.resources_bucket = os.getenv("R2_RESOURCES_BUCKET_NAME")
        if not self.resources_bucket:
            raise ValueError(
                "R2_RESOURCES_BUCKET_NAME environment variable is required"
            )

    def _generate_signed_url_from_r2_url(
        self, direct_url: Optional[str]
    ) -> Optional[str]:
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
            r2_public_url = os.getenv(
                "R2_PUBLIC_URL",
                f"https://pub-{media_service.r2_bucket}.r2.dev",
            )

            # Extract storage path from the direct URL
            # Example: "https://pub-bucket.r2.dev/experts/avatar.jpg" -> "experts/avatar.jpg"
            if r2_public_url in direct_url:
                storage_path = direct_url.replace(f"{r2_public_url}/", "")
                # Generate signed URL - 1 hour expiry
                signed_url = media_service.generate_signed_url(
                    storage_path, expiry=3600
                )
                return signed_url
            else:
                # Not an R2 URL, return as-is (backward compatibility for external URLs)
                return direct_url

        except Exception as e:
            logger.warning(
                f"Failed to generate signed URL from R2 URL {direct_url}: {e}"
            )
            # Fallback to original URL if signing fails
            return direct_url

    async def get_resources(
        self,
        user_id: str,
        category: Optional[str] = None,
        resource_type: Optional[str] = None,
        is_premium: Optional[bool] = None,
        search: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Get resources with premium access control
        Articles are free, some videos are premium-only
        """
        try:
            # Get user subscription status
            user_subscription = await get_user_subscription_status(user_id)
            user_is_premium = user_subscription.get("is_premium", False)

            # Build query
            query = self.supabase.table("resources").select("*")

            # Apply filters with enhanced table structure

            if category:
                # Normalize: split "planning," or "planning, production" → ["planning"]
                cats = [
                    c.strip() for c in re.split(r",", category) if c.strip()
                ]

                if len(cats) == 1:
                    # Row must CONTAIN that one category
                    query = query.contains("category", cats)
                else:
                    # Row must OVERLAP any of these categories
                    query = query.overlaps("category", cats)

            if resource_type:
                query = query.eq("type", resource_type)

            # Premium access control: articles are free, some videos are premium-only
            if not user_is_premium:
                query = query.eq("is_premium", False)
            elif is_premium is not None:
                query = query.eq("is_premium", is_premium)

            # Search functionality
            if search:
                query = query.or_(
                    f"title.ilike.%{search}%,"
                    f"description.ilike.%{search}%,"
                    f"author.ilike.%{search}%"
                )

            # Add pagination and ordering
            query = query.order("created_at", desc=True).range(
                offset, offset + limit - 1
            )

            response = query.execute()

            if response.data:
                # Process resources and add access metadata
                resources = []
                for resource in response.data:
                    # Remove unwanted fields from response
                    resource_data = {
                        k: v
                        for k, v in resource.items()
                        if k
                        not in ["duration", "difficulty_level", "subcategory"]
                    }

                    # Add access metadata
                    resource_data["user_has_access"] = True
                    if resource.get("is_premium") and not user_is_premium:
                        resource_data["user_has_access"] = False
                        resource_data["requires_premium"] = True

                        # For premium content that user can't access, show teaser
                        if resource.get("type") == "video":
                            resource_data["video_url"] = None
                            resource_data["download_url"] = None
                            resource_data["description"] = (
                                f"🔒 {resource_data['description'][:100]}... [Premium content - upgrade to access]"
                            )

                    # Add content URLs for articles
                    if resource.get("type") in ["article", "guide"]:
                        resource_data["content_url"] = (
                            await article_content_service.generate_article_url(
                                resource["id"]
                            )
                        )
                        resource_data["content_api_url"] = (
                            f"/api/v1/resources/{resource['id']}/content"
                        )

                    # Add PDF guide download URL for articles and videos
                    if resource.get("type") in [
                        "article",
                        "video",
                    ] and resource.get("download_url"):
                        # For articles, use action guide service (existing functionality)
                        if resource.get("type") == "article":
                            download_url = (
                                action_guide_service.generate_download_url(
                                    resource["id"],
                                    resource.get("category", "general"),
                                )
                            )
                            if download_url:
                                resource_data["action_guide_url"] = (
                                    download_url
                                )
                            else:
                                resource_data["action_guide_url"] = (
                                    resource.get("download_url")
                                )

                        # For videos, use the new PDF service
                        elif resource.get("type") == "video":
                            from resource_pdf_service import (
                                resource_pdf_service,
                            )

                            download_url = (
                                resource_pdf_service.generate_download_url(
                                    resource["id"], "video"
                                )
                            )
                            if download_url:
                                resource_data["pdf_guide_url"] = download_url
                            else:
                                resource_data["pdf_guide_url"] = resource.get(
                                    "download_url"
                                )

                    if resource_data.get("user_has_access", False):
                        if resource.get("type") == "video":
                            fields_to_sign = (
                                "image_url",
                                "thumbnail_url",
                                "download_url",
                            )
                        else:
                            fields_to_sign = (
                                "image_url",
                                "thumbnail_url",
                                "url",
                                "download_url",
                            )
                        for field in fields_to_sign:
                            val = resource_data.get(field)
                            if val:
                                resource_data[field] = (
                                    self._generate_signed_url_from_r2_url(val)
                                )

                    resources.append(resource_data)

                result = {
                    "resources": resources,
                    "total_count": len(resources),
                    "has_more": len(resources) == limit,
                }
                return result

            return {"resources": [], "total_count": 0, "has_more": False}

        except Exception as e:
            logger.error(f"Error getting resources: {str(e)}")
            raise Exception("Failed to get resources")

    async def get_blog_posts(
        self, limit: int = 20, offset: int = 0
    ) -> Dict[str, Any]:
        """
        Get blog posts (resources where is_blog=True)
        This endpoint is public and does not require authentication.
        """
        try:
            query = (
                self.supabase.table("resources")
                .select("*")
                .eq("is_blog", True)
                .eq("type", "article")
                .order("created_at", desc=True)
                .range(offset, offset + limit - 1)
            )

            response = query.execute()

            if response.data:
                blogs = []
                for resource in response.data:
                    content = (
                        await article_content_service.get_article_content(
                            resource["id"]
                        )
                    )
                    blogs.append(
                        {
                            "id": resource["id"],
                            "slug": resource["id"],
                            "title": resource["title"],
                            "summary": resource.get("description"),
                            "content": content,
                            "created_at": resource.get("created_at"),
                            "author": "Podground Team",
                        }
                    )

                return {
                    "blogs": blogs,
                    "total_count": len(blogs),
                    "has_more": len(blogs) == limit,
                }

            return {"blogs": [], "total_count": 0, "has_more": False}

        except Exception as e:
            logger.error(f"Error getting blog posts: {str(e)}")
            raise Exception("Failed to get blog posts")

    async def get_resource_by_id(
        self, user_id: str, resource_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get single resource with premium access control"""
        try:
            # Get user subscription status
            user_subscription = await get_user_subscription_status(user_id)
            user_is_premium = user_subscription.get("is_premium", False)

            response = (
                self.supabase.table("resources")
                .select("*")
                .eq("id", resource_id)
                .execute()
            )

            if response.data:
                resource_raw = response.data[0]
                # Remove unwanted fields from response
                resource = {
                    k: v
                    for k, v in resource_raw.items()
                    if k not in ["duration", "difficulty_level", "subcategory"]
                }

                # Check premium access
                if resource.get("is_premium") and not user_is_premium:
                    # Return limited info for premium content
                    return {
                        "id": resource["id"],
                        "title": resource["title"],
                        "description": f"🔒 {resource['description'][:100]}... [Premium content - upgrade to access]",
                        "type": resource["type"],
                        "thumbnail_url": resource.get("thumbnail_url"),
                        "is_premium": True,
                        "user_has_access": False,
                        "requires_premium": True,
                    }

                # Increment view count
                await self._increment_view_count(resource_id)

                resource["user_has_access"] = True

                # For articles and guides, add content information
                if resource.get("type") in ["article", "guide"]:
                    # Add R2 content URL (direct link to markdown file)
                    resource["content_url"] = (
                        await article_content_service.generate_article_url(
                            resource_id
                        )
                    )

                    # Also add an API endpoint for fetching content through our API
                    resource["content_api_url"] = (
                        f"/api/v1/resources/{resource_id}/content"
                    )

                    # Check if content exists
                    metadata = (
                        await article_content_service.get_article_metadata(
                            resource_id
                        )
                    )
                    resource["has_content"] = metadata is not None

                # Add PDF guide download URL for articles and videos
                if resource.get("type") in [
                    "article",
                    "video",
                ] and resource.get("download_url"):
                    # For articles, use action guide service (existing functionality)
                    if resource.get("type") == "article":
                        download_url = (
                            action_guide_service.generate_download_url(
                                resource_id,
                                resource.get("category", "general"),
                            )
                        )
                        if download_url:
                            resource["action_guide_url"] = download_url
                        else:
                            resource["action_guide_url"] = resource.get(
                                "download_url"
                            )

                    # For videos, use the new PDF service
                    elif resource.get("type") == "video":
                        from resource_pdf_service import resource_pdf_service

                        download_url = (
                            resource_pdf_service.generate_download_url(
                                resource_id, "video"
                            )
                        )
                        if download_url:
                            resource["pdf_guide_url"] = download_url
                        else:
                            resource["pdf_guide_url"] = resource.get(
                                "download_url"
                            )

                if resource.get("user_has_access", False):
                    if resource.get("type") == "video":
                        fields_to_sign = (
                            "image_url",
                            "thumbnail_url",
                        )
                    else:
                        fields_to_sign = (
                            "image_url",
                            "thumbnail_url",
                            "url",
                        )
                    for field in fields_to_sign:
                        val = resource.get(field)
                        if val:
                            resource[field] = (
                                self._generate_signed_url_from_r2_url(val)
                            )

                return resource

            return None

        except Exception as e:
            logger.error(f"Error getting resource {resource_id}: {str(e)}")
            raise Exception("Failed to get resource")

    async def get_resource_categories(self) -> List[Dict[str, Any]]:
        """Get all active resource categories from database"""
        try:
            response = (
                self.supabase.table("resource_categories")
                .select("*")
                .eq("is_active", True)
                .order("sort_order")
                .execute()
            )
            return response.data or []
        except Exception as e:
            logger.error(f"Error getting resource categories: {str(e)}")
            # Fallback to static categories if database query fails
            return [
                {
                    "name": "planning",
                    "display_name": "Planning & Strategy",
                    "description": "Content planning and strategic guidance",
                },
                {
                    "name": "production",
                    "display_name": "Production & Editing",
                    "description": "Recording and editing techniques",
                },
                {
                    "name": "promotion",
                    "display_name": "Promotion & Growth",
                    "description": "Marketing and audience building",
                },
                {
                    "name": "monetization",
                    "display_name": "Monetization",
                    "description": "Revenue streams and business models",
                },
                {
                    "name": "equipment",
                    "display_name": "Equipment & Tools",
                    "description": "Microphones, software, and setups",
                },
            ]

    async def get_experts(
        self,
        is_available: Optional[bool] = None,
        search: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Get experts with filtering"""
        try:
            # Build simple query without category joins
            query = self.supabase.table("experts").select("*")

            # Apply filters
            if is_available is not None:
                query = query.eq("is_available", is_available)

            if search:
                query = query.or_(
                    f"name.ilike.%{search}%,"
                    f"title.ilike.%{search}%,"
                    f"specialization.ilike.%{search}%,"
                    f"bio.ilike.%{search}%"
                )

            # Order by rating and availability
            query = query.order("rating", desc=True).order(
                "is_available", desc=True
            )
            query = query.range(offset, offset + limit - 1)

            response = query.execute()

            if response.data:
                # Convert direct R2 URLs to signed URLs for expert avatar images
                experts = response.data
                for expert in experts:
                    if expert.get("avatar_url"):
                        expert["avatar_url"] = (
                            self._generate_signed_url_from_r2_url(
                                expert["avatar_url"]
                            )
                        )

                return {
                    "experts": experts,
                    "total_count": len(experts),
                    "has_more": len(experts) == limit,
                }

            return {"experts": [], "total_count": 0, "has_more": False}

        except Exception as e:
            logger.error(f"Error getting experts: {str(e)}")
            # Fallback to sample data if database query fails
            sample_experts = [
                {
                    "id": "1",
                    "name": "Sarah Johnson",
                    "title": "Podcast Production Specialist",
                    "specialization": "Audio Production",
                    "bio": "Expert in podcast production with 10+ years experience.",
                    "avatar_url": "https://images.unsplash.com/photo-1494790108755-2616b612b100?w=400",
                    "is_available": True,
                    "hourly_rate": 75.00,
                    "rating": 4.9,
                    "categories": [
                        {
                            "name": "audio-production",
                            "display_name": "Audio Production",
                            "color": "#FF6B6B",
                        }
                    ],
                }
            ]

            return {
                "experts": sample_experts,
                "total_count": len(sample_experts),
                "has_more": False,
            }

    def update_resource_download_url(
        self, resource_id: str, download_url: Optional[str]
    ) -> Dict[str, Any]:
        """Update the download URL for a resource"""
        try:
            update_data = {
                "download_url": download_url,
                "updated_at": datetime.utcnow().isoformat(),
            }

            result = (
                self.supabase.table("resources")
                .update(update_data)
                .eq("id", resource_id)
                .execute()
            )

            if result.data:
                return {"success": True, "data": result.data[0]}
            else:
                return {"success": False, "error": "Failed to update resource"}
        except Exception as e:
            logger.error(f"Error updating resource download URL: {str(e)}")
            return {"success": False, "error": str(e)}

    async def get_expert_by_id(
        self, expert_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get single expert by ID"""
        try:
            # Get expert data
            response = (
                self.supabase.table("experts")
                .select("*")
                .eq("id", expert_id)
                .execute()
            )

            if response.data:
                expert = response.data[0]
                # Convert direct R2 URL to signed URL for avatar image
                if expert.get("avatar_url"):
                    expert["avatar_url"] = (
                        self._generate_signed_url_from_r2_url(
                            expert["avatar_url"]
                        )
                    )
                return expert

            return None

        except Exception as e:
            logger.error(f"Error getting expert {expert_id}: {str(e)}")
            # Fallback to sample data
            if expert_id == "1":
                return {
                    "id": "1",
                    "name": "Sarah Johnson",
                    "title": "Podcast Production Specialist",
                    "specialization": "Audio Production",
                    "bio": "Expert in podcast production with 10+ years experience helping podcasters create professional-quality shows.",
                    "avatar_url": "https://images.unsplash.com/photo-1494790108755-2616b612b100?w=400",
                    "is_available": True,
                    "hourly_rate": 75.00,
                    "rating": 4.9,
                    "categories": [
                        {
                            "name": "audio-production",
                            "display_name": "Audio Production",
                            "color": "#FF6B6B",
                        }
                    ],
                }
            return None

    async def get_partner_deals(
        self, limit: int = 20, offset: int = 0
    ) -> Dict[str, Any]:
        """Get active partner deals"""
        try:
            from media_service import MediaService

            media_service = MediaService()

            # Build query - get all active deals
            query = (
                self.supabase.table("partner_deals")
                .select("*")
                .eq("is_active", True)
            )

            # Add pagination and ordering
            query = query.order("created_at", desc=True).range(
                offset, offset + limit - 1
            )

            response = query.execute()

            if response.data:
                # Process deals and add signed URLs for logos
                deals = []
                for deal in response.data:
                    # Remove deal_title from response
                    if "deal_title" in deal:
                        del deal["deal_title"]

                    # Generate signed URL for logo if image_url exists
                    if deal.get("image_url"):
                        try:
                            signed_url = media_service.generate_signed_url(
                                deal["image_url"],
                                expiry=3600,
                                bucket=self.partners_bucket,
                            )
                            deal["logo_url"] = signed_url
                        except Exception as e:
                            logger.warning(
                                f"Failed to generate signed URL for {deal['partner_name']}: {e}"
                            )
                            deal["logo_url"] = None

                    deals.append(deal)

                return {
                    "deals": deals,
                    "total_count": len(deals),
                    "has_more": len(deals) == limit,
                }

            return {"deals": [], "total_count": 0, "has_more": False}

        except Exception as e:
            logger.error(f"Error getting partner deals: {str(e)}")
            raise Exception("Failed to get partner deals")

    async def get_partner_deal_by_id(
        self, deal_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get single partner deal by ID"""
        try:
            from media_service import MediaService

            media_service = MediaService()

            response = (
                self.supabase.table("partner_deals")
                .select("*")
                .eq("id", deal_id)
                .eq("is_active", True)
                .execute()
            )

            if response.data:
                deal = response.data[0]

                # Remove deal_title from response
                if "deal_title" in deal:
                    del deal["deal_title"]

                # Generate signed URL for logo if image_url exists
                if deal.get("image_url"):
                    try:
                        signed_url = media_service.generate_signed_url(
                            deal["image_url"],
                            expiry=3600,
                            bucket=self.partners_bucket,
                        )
                        deal["logo_url"] = signed_url
                    except Exception as e:
                        logger.warning(
                            f"Failed to generate signed URL for {deal['partner_name']}: {e}"
                        )
                        deal["logo_url"] = None

                return deal

            return None

        except Exception as e:
            logger.error(f"Error getting partner deal {deal_id}: {str(e)}")
            return None

    async def get_article_content(
        self, user_id: str, resource_id: str
    ) -> Dict[str, Any]:
        """
        Get article content from R2
        Checks user access before returning content
        """
        try:
            # First check if user has access to the resource
            resource = await self.get_resource_by_id(user_id, resource_id)

            if not resource:
                return {"success": False, "error": "Resource not found"}

            if not resource.get("user_has_access", False):
                return {
                    "success": False,
                    "error": "Premium subscription required",
                }

            if resource.get("type") != "article":
                return {
                    "success": False,
                    "error": "Resource is not an article",
                }

            # Fetch content from R2
            content = await article_content_service.get_article_content(
                resource_id
            )

            if content:
                return {
                    "success": True,
                    "content": content,
                    "format": "markdown",
                    "resource": resource,
                }
            else:
                return {"success": False, "error": "Article content not found"}

        except Exception as e:
            logger.error(f"Error getting article content: {str(e)}")
            return {"success": False, "error": "Failed to get article content"}

    async def create_article_content(
        self,
        resource_id: str,
        content: str,
        title: str,
        author: str = "PodGround Team",
    ) -> Dict[str, Any]:
        """Create article content in R2"""
        try:
            result = await article_content_service.upload_article_content(
                resource_id=resource_id,
                content=content,
                title=title,
                author=author,
            )
            return result
        except Exception as e:
            logger.error(f"Error creating article content: {str(e)}")
            return {"success": False, "error": str(e)}

    async def create_resource(
        self, resource_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a new resource"""
        try:
            # Prepare data for insertion
            insert_data = {
                "title": resource_data["title"],
                "description": resource_data.get("description"),
                "type": resource_data["type"],
                "url": resource_data.get("url"),
                "image_url": resource_data.get("image_url"),
                "author": resource_data.get("author"),
                "read_time": resource_data.get("read_time"),
                "is_featured": resource_data.get("is_featured", False),
                "category": resource_data.get("category", "general"),
                "subcategory": resource_data.get("subcategory"),
                "video_url": resource_data.get("video_url"),
                "download_url": resource_data.get("download_url"),
                "duration": resource_data.get("duration"),
                "difficulty_level": resource_data.get(
                    "difficulty_level", "beginner"
                ),
                "tags": resource_data.get("tags", []),
                "is_premium": resource_data.get("is_premium", False),
                "thumbnail_url": resource_data.get("thumbnail_url"),
                "view_count": 0,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }

            # Remove None values to use database defaults
            insert_data = {
                k: v for k, v in insert_data.items() if v is not None
            }

            response = (
                self.supabase.table("resources").insert(insert_data).execute()
            )

            if response.data:
                created_resource = response.data[0]
                # Apply field filtering to response
                filtered_resource = {
                    k: v
                    for k, v in created_resource.items()
                    if k not in ["duration", "difficulty_level", "subcategory"]
                }

                return {"success": True, "data": filtered_resource}
            else:
                return {"success": False, "error": "Failed to create resource"}

        except Exception as e:
            logger.error(f"Error creating resource: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _increment_view_count(self, resource_id: str):
        """Increment view count for a resource"""
        try:
            # First get current view count
            current = (
                self.supabase.table("resources")
                .select("view_count")
                .eq("id", resource_id)
                .execute()
            )
            if current.data:
                new_count = (current.data[0].get("view_count") or 0) + 1
                self.supabase.table("resources").update(
                    {
                        "view_count": new_count,
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                ).eq("id", resource_id).execute()
        except Exception as e:
            logger.error(
                f"Error incrementing view count for resource {resource_id}: {str(e)}"
            )
            # Don't raise exception for non-critical operation


resources_service = ResourcesService()

