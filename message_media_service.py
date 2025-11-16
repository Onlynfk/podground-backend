"""
Message Media Service
Handles media file uploads to R2 and signed URL generation for message attachments
"""
import logging
import os
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from fastapi import HTTPException, UploadFile
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from supabase_client import SupabaseClient
from signed_url_cache_service import get_signed_url_cache_service

logger = logging.getLogger(__name__)


class MessageMediaService:
    def __init__(self):
        self.supabase_client = SupabaseClient()

        # Initialize R2 client
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
        self.bucket_name = os.getenv('R2_MESSAGES_BUCKET_NAME')
        if not self.bucket_name:
            raise ValueError("R2_MESSAGES_BUCKET_NAME environment variable is required")

        # Media type configurations
        self.allowed_media_types = {
            'image': {
                'mime_types': ['image/jpeg', 'image/png', 'image/gif', 'image/webp'],
                'max_size': 10 * 1024 * 1024,  # 10 MB
                'extensions': ['.jpg', '.jpeg', '.png', '.gif', '.webp']
            },
            'video': {
                'mime_types': ['video/mp4', 'video/quicktime', 'video/x-msvideo', 'video/webm'],
                'max_size': 100 * 1024 * 1024,  # 100 MB
                'extensions': ['.mp4', '.mov', '.avi', '.webm']
            },
            'audio': {
                'mime_types': ['audio/mpeg', 'audio/mp4', 'audio/wav', 'audio/webm'],
                'max_size': 50 * 1024 * 1024,  # 50 MB
                'extensions': ['.mp3', '.m4a', '.wav', '.webm']
            },
            'document': {
                'mime_types': ['application/pdf', 'application/msword',
                              'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                              'application/vnd.ms-excel',
                              'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                              'text/plain'],
                'max_size': 20 * 1024 * 1024,  # 20 MB
                'extensions': ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt']
            }
        }

    def _determine_media_type(self, mime_type: str, filename: str) -> str:
        """Determine media type from MIME type and filename"""
        for media_type, config in self.allowed_media_types.items():
            if mime_type in config['mime_types']:
                return media_type

        # Fallback to extension check
        file_ext = os.path.splitext(filename)[1].lower()
        for media_type, config in self.allowed_media_types.items():
            if file_ext in config['extensions']:
                return media_type

        raise HTTPException(400, f"Unsupported file type: {mime_type}")

    def _validate_file(self, file: UploadFile, media_type: str) -> None:
        """Validate file against media type constraints"""
        config = self.allowed_media_types.get(media_type)
        if not config:
            raise HTTPException(400, f"Invalid media type: {media_type}")

        # Validate MIME type
        if file.content_type not in config['mime_types']:
            raise HTTPException(
                400,
                f"Invalid file type for {media_type}. Allowed: {', '.join(config['mime_types'])}"
            )

        # Validate file extension
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in config['extensions']:
            raise HTTPException(
                400,
                f"Invalid file extension for {media_type}. Allowed: {', '.join(config['extensions'])}"
            )

    async def verify_conversation_access(self, user_id: str, conversation_id: str) -> bool:
        """Verify user is a participant in the conversation"""
        try:
            result = self.supabase_client.service_client.table("conversation_participants").select(
                "user_id"
            ).eq("conversation_id", conversation_id).eq("user_id", user_id).eq(
                "conversation_deleted_for_user", False
            ).is_("left_at", "null").execute()

            return bool(result.data)
        except Exception as e:
            logger.error(f"Failed to verify conversation access: {str(e)}")
            return False

    async def upload_message_media(
        self,
        user_id: str,
        message_id: str,
        conversation_id: str,
        files: List[UploadFile],
        display_order_start: int = 0
    ) -> List[Dict[str, Any]]:
        """Upload multiple media files for a message to R2"""
        try:
            # Verify user has access to conversation
            has_access = await self.verify_conversation_access(user_id, conversation_id)
            if not has_access:
                raise HTTPException(403, "Not authorized to upload media to this conversation")

            # Verify message exists and belongs to user
            message_result = self.supabase_client.service_client.table("messages").select(
                "id, sender_id, conversation_id"
            ).eq("id", message_id).single().execute()

            if not message_result.data:
                raise HTTPException(404, "Message not found")

            if message_result.data["sender_id"] != user_id:
                raise HTTPException(403, "Not authorized to add media to this message")

            if message_result.data["conversation_id"] != conversation_id:
                raise HTTPException(400, "Message does not belong to this conversation")

            uploaded_media = []

            for idx, file in enumerate(files):
                # Read file content
                file_content = await file.read()
                file_size = len(file_content)

                # Determine media type
                media_type = self._determine_media_type(file.content_type, file.filename)

                # Validate file
                self._validate_file(file, media_type)

                # Check file size
                max_size = self.allowed_media_types[media_type]['max_size']
                if file_size > max_size:
                    raise HTTPException(
                        400,
                        f"File {file.filename} exceeds maximum size of {max_size / (1024 * 1024):.1f} MB"
                    )

                # Generate unique filename
                file_ext = os.path.splitext(file.filename)[1]
                unique_filename = f"{uuid.uuid4()}{file_ext}"

                # Construct R2 path: messages/{conversation_id}/{message_id}/{filename}
                r2_path = f"messages/{conversation_id}/{message_id}/{unique_filename}"

                # Upload to R2
                try:
                    self.r2_client.put_object(
                        Bucket=self.bucket_name,
                        Key=r2_path,
                        Body=file_content,
                        ContentType=file.content_type,
                        Metadata={
                            'original_filename': file.filename,
                            'user_id': user_id,
                            'message_id': message_id,
                            'conversation_id': conversation_id
                        }
                    )
                    logger.info(f"Uploaded media to R2: {r2_path}")
                except ClientError as e:
                    logger.error(f"Failed to upload to R2: {str(e)}")
                    raise HTTPException(500, f"Failed to upload file {file.filename}")

                # Store metadata in database
                media_record = {
                    "message_id": message_id,
                    "media_type": media_type,
                    "file_path": r2_path,
                    "filename": file.filename,
                    "file_size": file_size,
                    "mime_type": file.content_type,
                    "display_order": display_order_start + idx
                }

                result = self.supabase_client.service_client.table("message_media").insert(
                    media_record
                ).execute()

                if result.data:
                    uploaded_media.append(result.data[0])

                # Reset file pointer for potential reuse
                await file.seek(0)

            return uploaded_media

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to upload message media: {str(e)}")
            raise HTTPException(500, f"Failed to upload media: {str(e)}")

    async def get_message_media(self, user_id: str, message_id: str) -> List[Dict[str, Any]]:
        """Get all media attachments for a message with signed URLs"""
        try:
            # Get message to verify access
            message_result = self.supabase_client.service_client.table("messages").select(
                "id, conversation_id"
            ).eq("id", message_id).single().execute()

            if not message_result.data:
                raise HTTPException(404, "Message not found")

            conversation_id = message_result.data["conversation_id"]

            # Verify user has access
            has_access = await self.verify_conversation_access(user_id, conversation_id)
            if not has_access:
                raise HTTPException(403, "Not authorized to view this message media")

            # Get media records
            media_result = self.supabase_client.service_client.table("message_media").select(
                "*"
            ).eq("message_id", message_id).order("display_order").execute()

            media_list = media_result.data or []

            # Generate signed URLs for each media item
            for media in media_list:
                media["url"] = self._generate_signed_url(media["file_path"])

                # Generate thumbnail URL if exists
                if media.get("thumbnail_path"):
                    media["thumbnail_url"] = self._generate_signed_url(media["thumbnail_path"])

            return media_list

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get message media: {str(e)}")
            raise HTTPException(500, f"Failed to get message media: {str(e)}")

    def _generate_signed_url(self, file_path: str, expiration: int = 3600) -> str:
        """
        Generate a signed URL for accessing media in R2
        Uses in-memory caching to avoid regenerating URLs
        """
        try:
            # Create cache key with bucket name for multi-bucket support
            cache_key = f"{self.bucket_name}/{file_path}"

            # Check cache first
            cache_service = get_signed_url_cache_service()
            cached_url = cache_service.get(cache_key, expiration)
            if cached_url:
                return cached_url

            # Generate new signed URL if not in cache
            url = self.r2_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': file_path
                },
                ExpiresIn=expiration
            )

            # Cache the generated URL
            cache_service.set(cache_key, url, expiration)

            return url
        except ClientError as e:
            logger.error(f"Failed to generate signed URL for {file_path}: {str(e)}")
            raise HTTPException(500, "Failed to generate media URL")

    async def delete_message_media(self, user_id: str, media_id: str) -> Dict[str, Any]:
        """Delete a media attachment (user must own the message)"""
        try:
            # Get media record
            media_result = self.supabase_client.service_client.table("message_media").select(
                "id, message_id, file_path, thumbnail_path"
            ).eq("id", media_id).single().execute()

            if not media_result.data:
                raise HTTPException(404, "Media not found")

            media = media_result.data

            # Verify user owns the message
            message_result = self.supabase_client.service_client.table("messages").select(
                "sender_id"
            ).eq("id", media["message_id"]).single().execute()

            if not message_result.data:
                raise HTTPException(404, "Message not found")

            if message_result.data["sender_id"] != user_id:
                raise HTTPException(403, "Not authorized to delete this media")

            # Delete from R2
            try:
                self.r2_client.delete_object(
                    Bucket=self.bucket_name,
                    Key=media["file_path"]
                )
                logger.info(f"Deleted media from R2: {media['file_path']}")

                # Delete thumbnail if exists
                if media.get("thumbnail_path"):
                    self.r2_client.delete_object(
                        Bucket=self.bucket_name,
                        Key=media["thumbnail_path"]
                    )
            except ClientError as e:
                logger.warning(f"Failed to delete from R2: {str(e)}")
                # Continue with database deletion even if R2 deletion fails

            # Delete from database
            self.supabase_client.service_client.table("message_media").delete().eq(
                "id", media_id
            ).execute()

            return {"success": True}

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to delete message media: {str(e)}")
            raise HTTPException(500, f"Failed to delete media: {str(e)}")

    async def cleanup_message_media(self, message_id: str) -> Dict[str, Any]:
        """Clean up all media for a deleted message (called internally)"""
        try:
            # Get all media for message
            media_result = self.supabase_client.service_client.table("message_media").select(
                "id, file_path, thumbnail_path"
            ).eq("message_id", message_id).execute()

            media_list = media_result.data or []

            # Delete from R2
            for media in media_list:
                try:
                    self.r2_client.delete_object(
                        Bucket=self.bucket_name,
                        Key=media["file_path"]
                    )

                    if media.get("thumbnail_path"):
                        self.r2_client.delete_object(
                            Bucket=self.bucket_name,
                            Key=media["thumbnail_path"]
                        )
                except ClientError as e:
                    logger.warning(f"Failed to delete media from R2: {str(e)}")

            # Delete from database (CASCADE will handle this, but explicit is better)
            self.supabase_client.service_client.table("message_media").delete().eq(
                "message_id", message_id
            ).execute()

            return {"success": True, "deleted_count": len(media_list)}

        except Exception as e:
            logger.error(f"Failed to cleanup message media: {str(e)}")
            return {"success": False, "error": str(e)}


# Global instance
_message_media_service = None

def get_message_media_service() -> MessageMediaService:
    """Get or create global MessageMediaService instance"""
    global _message_media_service
    if _message_media_service is None:
        _message_media_service = MessageMediaService()
    return _message_media_service
