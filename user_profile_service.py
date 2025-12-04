"""
User Profile Service
Handles user profile management, avatar uploads, and profile data operations
"""
import os
import hashlib
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path

import boto3
from botocore.config import Config
from fastapi import UploadFile, HTTPException
from PIL import Image
from io import BytesIO

from supabase_client import SupabaseClient
from user_profile_cache_service import get_user_profile_cache_service
from datetime_utils import format_datetime_central

logger = logging.getLogger(__name__)

class UserProfileService:
    def __init__(self):
        self.supabase_client = SupabaseClient()
        
        # Initialize R2 client for avatar uploads
        r2_account_id = os.getenv('R2_ACCOUNT_ID')
        if not r2_account_id:
            raise ValueError("R2_ACCOUNT_ID environment variable is required")
            
        self.r2_client = boto3.client(
            's3',
            endpoint_url=f"https://{r2_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),
            config=Config(signature_version='s3v4'),
            region_name='auto'
        )
        self.r2_bucket = os.getenv('R2_BUCKET_NAME')
        if not self.r2_bucket:
            raise ValueError("R2_BUCKET_NAME environment variable is required")
        self.r2_public_url = os.getenv('R2_PUBLIC_URL')
        if not self.r2_public_url:
            raise ValueError("R2_PUBLIC_URL environment variable is required")

        # Avatar settings
        # Get max avatar size from env var (in MB), default to 10MB
        max_avatar_size_mb = int(os.getenv('MAX_AVATAR_SIZE_MB', '10'))
        self.MAX_AVATAR_SIZE = max_avatar_size_mb * 1024 * 1024  # Convert MB to bytes
        self.AVATAR_SIZE = (400, 400)
        self.ALLOWED_AVATAR_TYPES = {'image/jpeg', 'image/png', 'image/webp'}

    def _generate_signed_avatar_url(self, avatar_url: Optional[str]) -> Optional[str]:
        """
        Convert avatar R2 URL to pre-signed URL

        Args:
            avatar_url: Direct R2 public URL (e.g., "https://pub-bucket.r2.dev/avatars/...")

        Returns:
            Pre-signed URL with expiry, or None if avatar_url is None
        """
        if not avatar_url:
            return None

        # Extract storage path from the URL
        storage_path = avatar_url.replace(f"{self.r2_public_url}/", "")

        # Generate signed URL with 1 hour expiry
        from media_service import MediaService
        media_service = MediaService()
        signed_url = media_service.generate_signed_url(storage_path, expiry=3600)
        return signed_url

    async def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        """Get complete user profile including claimed podcast info"""
        try:
            # Check cache first
            cache = get_user_profile_cache_service()
            cached_profile = cache.get(user_id)
            if cached_profile:
                logger.debug(f"Returning cached profile for user {user_id}")
                return cached_profile

            # Get user profile data
            profile_result = self.supabase_client.service_client.table("user_profiles").select(
                "*"
            ).eq("user_id", user_id).execute()

            profile_data = profile_result.data[0] if profile_result.data else {}

            # Get user signup data (name, email)
            signup_result = self.supabase_client.service_client.table("user_signup_tracking").select(
                "email, name"
            ).eq("user_id", user_id).execute()

            signup_data = signup_result.data[0] if signup_result.data else {}

            # Get claimed podcast info via podcast_claims table
            podcast_data = {}
            try:
                # Get user's verified podcast claim
                claims_result = self.supabase_client.service_client.table("podcast_claims").select(
                    "listennotes_id"
                ).eq("user_id", user_id).eq("is_verified", True).eq("claim_status", "verified").limit(1).execute()

                if claims_result.data:
                    listennotes_id = claims_result.data[0]["listennotes_id"]

                    # Get podcast info from main podcasts table
                    podcast_result = self.supabase_client.service_client.table("podcasts").select(
                        "id, title"
                    ).eq("listennotes_id", listennotes_id).single().execute()

                    if podcast_result.data:
                        podcast_data = podcast_result.data
            except Exception as e:
                logger.warning(f"Could not get claimed podcast for user {user_id}: {e}")

            # Get connection count
            connections_count = await self._get_connections_count(user_id)

            # Construct full name from first_name + last_name if available, otherwise use signup name
            first_name = profile_data.get("first_name")
            last_name = profile_data.get("last_name")

            if first_name and last_name:
                full_name = f"{first_name} {last_name}"
            elif first_name:
                full_name = first_name
            elif last_name:
                full_name = last_name
            else:
                full_name = signup_data.get("name")

            # Generate signed URL for avatar
            avatar_url = self._generate_signed_avatar_url(profile_data.get("avatar_url"))

            profile = {
                "id": user_id,
                "name": full_name,
                "first_name": first_name,
                "last_name": last_name,
                "email": signup_data.get("email"),
                "bio": profile_data.get("bio"),
                "location": profile_data.get("location"),
                "avatar_url": avatar_url,
                "podcast_id": podcast_data.get("id"),
                "podcast_name": podcast_data.get("title"),
                "connections_count": connections_count,
                "created_at": format_datetime_central(profile_data.get("created_at")),
                "updated_at": format_datetime_central(profile_data.get("updated_at"))
            }

            # Cache the profile
            cache.set(user_id, profile)
            logger.debug(f"Cached profile for user {user_id}")

            return profile

        except Exception as e:
            logger.error(f"Failed to get user profile {user_id}: {str(e)}")
            raise HTTPException(500, f"Failed to get user profile: {str(e)}")

    async def update_user_profile(self, user_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update user profile information"""
        try:
            # All profile fields go to user_profiles table
            allowed_profile_fields = {"bio", "location", "first_name", "last_name"}
            profile_data = {k: v for k, v in update_data.items() if k in allowed_profile_fields}

            if not profile_data:
                return await self.get_user_profile(user_id)

            # Check if profile exists
            existing_result = self.supabase_client.service_client.table("user_profiles").select(
                "id"
            ).eq("user_id", user_id).execute()

            if existing_result.data:
                # Update existing profile
                result = self.supabase_client.service_client.table("user_profiles").update(
                    profile_data
                ).eq("user_id", user_id).execute()
            else:
                # Create new profile
                profile_data["user_id"] = user_id
                result = self.supabase_client.service_client.table("user_profiles").insert(
                    profile_data
                ).execute()

            if not result.data:
                raise Exception("Failed to update profile")

            # Invalidate cache after update
            cache = get_user_profile_cache_service()
            cache.invalidate(user_id)
            logger.debug(f"Invalidated cache for user {user_id} after profile update")

            return await self.get_user_profile(user_id)

        except Exception as e:
            logger.error(f"Failed to update user profile {user_id}: {str(e)}")
            raise HTTPException(500, f"Failed to update profile: {str(e)}")

    async def upload_avatar(self, user_id: str, avatar_file: UploadFile) -> Dict[str, Any]:
        """Upload and set user avatar"""
        try:
            # Validate avatar file
            await self._validate_avatar_file(avatar_file)

            # Read and process avatar
            avatar_file.file.seek(0)
            file_content = await avatar_file.read()

            # Log file details for debugging
            logger.info(f"Avatar upload - user: {user_id}, filename: {avatar_file.filename}, "
                       f"content_type: {avatar_file.content_type}, size: {len(file_content)} bytes")

            if len(file_content) == 0:
                raise HTTPException(400, "Uploaded file is empty")

            # Process image (resize and optimize)
            processed_avatar = await self._process_avatar(file_content)
            
            # Generate storage path
            file_extension = Path(avatar_file.filename).suffix.lower()
            if not file_extension:
                file_extension = '.jpg'
            
            storage_path = f"avatars/{user_id}/{datetime.now().strftime('%Y%m%d_%H%M%S')}{file_extension}"
            
            # Upload to R2
            avatar_url = await self._upload_avatar_to_r2(processed_avatar, storage_path)
            
            # Update user profile with new avatar URL
            # Delete old avatar if exists
            await self._delete_old_avatar(user_id)
            
            # Update profile with new avatar URL
            await self._update_avatar_url(user_id, avatar_url)

            # Invalidate cache after avatar update
            cache = get_user_profile_cache_service()
            cache.invalidate(user_id)
            logger.debug(f"Invalidated cache for user {user_id} after avatar upload")

            # Generate pre-signed URL for response
            signed_avatar_url = self._generate_signed_avatar_url(avatar_url)

            return {
                "success": True,
                "avatar_url": signed_avatar_url
            }
            
        except Exception as e:
            logger.error(f"Avatar upload failed for user {user_id}: {str(e)}")
            raise HTTPException(500, f"Avatar upload failed: {str(e)}")

    async def delete_avatar(self, user_id: str) -> Dict[str, Any]:
        """Delete user avatar"""
        try:
            # Get current avatar URL
            profile_result = self.supabase_client.service_client.table("user_profiles").select(
                "avatar_url"
            ).eq("user_id", user_id).execute()

            if profile_result.data and profile_result.data[0].get("avatar_url"):
                # Delete from R2
                await self._delete_avatar_from_r2(profile_result.data[0]["avatar_url"])
            
            # Update profile to remove avatar URL
            await self._update_avatar_url(user_id, None)

            # Invalidate cache after avatar deletion
            cache = get_user_profile_cache_service()
            cache.invalidate(user_id)
            logger.debug(f"Invalidated cache for user {user_id} after avatar deletion")

            return {"success": True}
            
        except Exception as e:
            logger.error(f"Avatar deletion failed for user {user_id}: {str(e)}")
            raise HTTPException(500, f"Avatar deletion failed: {str(e)}")

    async def _validate_avatar_file(self, file: UploadFile):
        """Validate avatar file"""
        # Check file size
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
        
        if size > self.MAX_AVATAR_SIZE:
            raise HTTPException(400, f"Avatar too large. Maximum size: {self.MAX_AVATAR_SIZE / (1024 * 1024)}MB")
        
        # Check file type
        if file.content_type not in self.ALLOWED_AVATAR_TYPES:
            raise HTTPException(400, f"Unsupported avatar format. Allowed: {', '.join(self.ALLOWED_AVATAR_TYPES)}")

    async def _process_avatar(self, image_content: bytes) -> bytes:
        """Process avatar image: resize and optimize"""
        try:
            logger.debug(f"Processing avatar image, content size: {len(image_content)} bytes")

            # Open image
            image_bytes = BytesIO(image_content)
            image = Image.open(image_bytes)

            logger.debug(f"Image opened successfully - format: {image.format}, mode: {image.mode}, size: {image.size}")

            # Convert to RGB if necessary (handles RGBA, P mode images)
            if image.mode in ('RGBA', 'P'):
                # Create white background for transparent images
                background = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'P':
                    image = image.convert('RGBA')
                background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
                image = background
            elif image.mode != 'RGB':
                image = image.convert('RGB')

            # Resize to avatar dimensions (square crop from center)
            width, height = image.size

            # Crop to square from center
            if width != height:
                size = min(width, height)
                left = (width - size) // 2
                top = (height - size) // 2
                image = image.crop((left, top, left + size, top + size))

            # Resize to target size
            image = image.resize(self.AVATAR_SIZE, Image.Resampling.LANCZOS)

            # Convert to bytes
            output = BytesIO()
            image.save(output, format='JPEG', quality=85, optimize=True)
            return output.getvalue()

        except Exception as e:
            logger.error(f"Avatar processing failed: {str(e)}, content length: {len(image_content) if image_content else 0}")
            raise HTTPException(400, f"Invalid image file: {str(e)}")

    async def _upload_avatar_to_r2(self, image_content: bytes, storage_path: str) -> str:
        """Upload avatar to Cloudflare R2"""
        try:
            self.r2_client.put_object(
                Bucket=self.r2_bucket,
                Key=storage_path,
                Body=image_content,
                ContentType='image/jpeg',
                CacheControl='public, max-age=31536000'
            )
            
            return f"{self.r2_public_url}/{storage_path}"
            
        except Exception as e:
            logger.error(f"R2 avatar upload failed: {str(e)}")
            raise HTTPException(500, "Failed to upload avatar")

    async def _delete_avatar_from_r2(self, avatar_url: str):
        """Delete avatar from R2"""
        try:
            # Extract storage path from URL
            storage_path = avatar_url.replace(f"{self.r2_public_url}/", "")
            
            self.r2_client.delete_object(
                Bucket=self.r2_bucket,
                Key=storage_path
            )
            
        except Exception as e:
            logger.warning(f"Failed to delete avatar from R2: {str(e)}")

    async def _delete_old_avatar(self, user_id: str):
        """Delete user's old avatar"""
        try:
            profile_result = self.supabase_client.service_client.table("user_profiles").select(
                "avatar_url"
            ).eq("user_id", user_id).execute()

            if profile_result.data and profile_result.data[0].get("avatar_url"):
                await self._delete_avatar_from_r2(profile_result.data[0]["avatar_url"])
                
        except Exception as e:
            logger.warning(f"Failed to delete old avatar: {str(e)}")

    async def _update_avatar_url(self, user_id: str, avatar_url: Optional[str]):
        """Update avatar URL in user profile"""
        try:
            # Check if profile exists
            existing_result = self.supabase_client.service_client.table("user_profiles").select(
                "id"
            ).eq("user_id", user_id).execute()

            update_data = {"avatar_url": avatar_url}

            if existing_result.data:
                # Update existing profile
                result = self.supabase_client.service_client.table("user_profiles").update(
                    update_data
                ).eq("user_id", user_id).execute()

                if not result.data:
                    raise Exception("Failed to update avatar URL in database")

                logger.info(f"Successfully updated avatar URL for user {user_id}")
            else:
                # Create new profile
                update_data["user_id"] = user_id
                result = self.supabase_client.service_client.table("user_profiles").insert(
                    update_data
                ).execute()

                if not result.data:
                    raise Exception("Failed to insert avatar URL in database")

                logger.info(f"Successfully created profile with avatar URL for user {user_id}")

        except Exception as e:
            logger.error(f"Failed to update avatar URL for user {user_id}: {str(e)}")
            raise

    async def get_user_avatar(self, user_id: str) -> Dict[str, Any]:
        """
        Get user's avatar as a presigned URL

        Args:
            user_id: User ID

        Returns:
            Dictionary with avatar_url (presigned) or None if no avatar
        """
        try:
            # Get avatar URL from user profile
            profile_result = self.supabase_client.service_client.table("user_profiles").select(
                "avatar_url"
            ).eq("user_id", user_id).execute()

            if not profile_result.data or not profile_result.data[0].get("avatar_url"):
                return {
                    "avatar_url": None,
                    "has_avatar": False
                }

            avatar_url = profile_result.data[0]["avatar_url"]

            # Generate presigned URL
            signed_url = self._generate_signed_avatar_url(avatar_url)

            return {
                "avatar_url": signed_url,
                "has_avatar": True
            }

        except Exception as e:
            logger.error(f"Failed to get avatar for user {user_id}: {str(e)}")
            raise HTTPException(500, f"Failed to get avatar: {str(e)}")

    async def _get_connections_count(self, user_id: str) -> int:
        """Get count of accepted connections for user"""
        try:
            result = self.supabase_client.service_client.table("user_connections").select(
                "id", count="exact"
            ).or_(
                f"and(follower_id.eq.{user_id},status.eq.accepted),and(following_id.eq.{user_id},status.eq.accepted)"
            ).execute()

            return result.count or 0

        except Exception as e:
            logger.warning(f"Failed to get connections count: {str(e)}")
            return 0

    async def get_users_by_ids(self, user_ids: List[str]) -> List[Dict[str, Any]]:
        """Get multiple user profiles by IDs"""
        try:
            if not user_ids:
                return []

            # Check cache first
            cache = get_user_profile_cache_service()
            cached_profiles = cache.get_batch(user_ids)

            # Find which user_ids are not in cache
            missing_user_ids = [uid for uid in user_ids if uid not in cached_profiles]

            # If all profiles are cached, return them
            if not missing_user_ids:
                logger.debug(f"All {len(user_ids)} profiles found in cache")
                return list(cached_profiles.values())

            logger.debug(f"Fetching {len(missing_user_ids)}/{len(user_ids)} profiles from DB (cache miss)")

            # Get user profiles for missing IDs
            profiles_result = self.supabase_client.service_client.table("user_profiles").select(
                "*"
            ).in_("user_id", missing_user_ids).execute()
            
            profiles_map = {p["user_id"]: p for p in profiles_result.data or []}

            # Get user signup data (only for missing IDs)
            signup_result = self.supabase_client.service_client.table("user_signup_tracking").select(
                "user_id, email, name"
            ).in_("user_id", missing_user_ids).execute()

            signup_map = {s["user_id"]: s for s in signup_result.data or []}

            # Get claimed podcasts via podcast_claims table (only for missing IDs)
            podcasts_map = {}
            try:
                claims_result = self.supabase_client.service_client.table("podcast_claims").select(
                    "user_id, listennotes_id"
                ).in_("user_id", missing_user_ids).eq("is_verified", True).eq("claim_status", "verified").execute()

                if claims_result.data:
                    listennotes_ids = [claim["listennotes_id"] for claim in claims_result.data]

                    # Fetch podcast info for all claims
                    if listennotes_ids:
                        podcasts_result = self.supabase_client.service_client.table("podcasts").select(
                            "id, listennotes_id, title"
                        ).in_("listennotes_id", listennotes_ids).execute()

                        if podcasts_result.data:
                            # Create lookup map
                            podcasts_by_listennotes = {p["listennotes_id"]: p for p in podcasts_result.data}

                            # Map claims to podcast data by user_id
                            for claim in claims_result.data:
                                podcast = podcasts_by_listennotes.get(claim["listennotes_id"])
                                if podcast:
                                    podcasts_map[claim["user_id"]] = podcast
            except Exception as e:
                logger.warning(f"Could not get claimed podcasts: {e}")

            # Build profiles for missing users and cache them
            newly_fetched_profiles = []
            for user_id in missing_user_ids:
                profile = profiles_map.get(user_id, {})
                signup = signup_map.get(user_id, {})
                podcast = podcasts_map.get(user_id, {})

                # Construct full name from first_name + last_name if available, otherwise use signup name
                first_name = profile.get("first_name")
                last_name = profile.get("last_name")

                if first_name and last_name:
                    full_name = f"{first_name} {last_name}"
                elif first_name:
                    full_name = first_name
                elif last_name:
                    full_name = last_name
                else:
                    full_name = signup.get("name")

                # Generate signed URL for avatar
                avatar_url = self._generate_signed_avatar_url(profile.get("avatar_url"))

                user_profile = {
                    "id": user_id,
                    "name": full_name,
                    "email": signup.get("email"),
                    "bio": profile.get("bio"),
                    "location": profile.get("location"),
                    "avatar_url": avatar_url,
                    "podcast_id": podcast.get("id"),
                    "podcast_name": podcast.get("title")
                }
                newly_fetched_profiles.append(user_profile)

            # Cache the newly fetched profiles
            if newly_fetched_profiles:
                cache.set_batch(newly_fetched_profiles)
                logger.debug(f"Cached {len(newly_fetched_profiles)} newly fetched profiles")

            # Combine cached and newly fetched profiles, maintaining original order
            all_profiles = {**cached_profiles}
            for profile in newly_fetched_profiles:
                all_profiles[profile["id"]] = profile

            # Return in original order
            return [all_profiles[uid] for uid in user_ids if uid in all_profiles]
            
        except Exception as e:
            logger.error(f"Failed to get users by IDs: {str(e)}")
            return []