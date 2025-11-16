"""
Media Upload Service
Handles file uploads, processing, and storage with security measures
"""
import os
import asyncio
import hashlib
import mimetypes
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import logging

import boto3
from botocore.config import Config
from fastapi import UploadFile, HTTPException
from PIL import Image
import ffmpeg

from supabase_client import SupabaseClient
from signed_url_cache_service import get_signed_url_cache_service

logger = logging.getLogger(__name__)

class MediaService:
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
        self.r2_bucket = os.getenv('R2_BUCKET_NAME')
        if not self.r2_bucket:
            raise ValueError("R2_BUCKET_NAME environment variable is required")
        self.r2_public_url = os.getenv('R2_PUBLIC_URL')
        if not self.r2_public_url:
            raise ValueError("R2_PUBLIC_URL environment variable is required")
        
        # File size limits (in bytes)
        self.MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
        self.MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100MB  
        self.MAX_AUDIO_SIZE = 50 * 1024 * 1024   # 50MB
        self.MAX_DOCUMENT_SIZE = 20 * 1024 * 1024  # 20MB
        
        # Allowed file types
        self.ALLOWED_IMAGE_TYPES = {
            'image/jpeg', 'image/png', 'image/webp', 'image/gif'
        }
        self.ALLOWED_VIDEO_TYPES = {
            'video/mp4', 'video/webm', 'video/quicktime', 'video/x-msvideo'
        }
        self.ALLOWED_AUDIO_TYPES = {
            'audio/mpeg', 'audio/mp4', 'audio/wav', 'audio/webm', 'audio/ogg'
        }
        self.ALLOWED_DOCUMENT_TYPES = {
            'application/pdf',
            'application/msword',  # .doc
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # .docx
            'text/plain',  # .txt
            'application/vnd.ms-excel',  # .xls
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'  # .xlsx
        }
        
        # Processing settings
        self.THUMBNAIL_SIZE = (400, 400)
        self.MAX_IMAGE_DIMENSION = 2048
    
    async def upload_media_files(self, files: List[UploadFile], user_id: str) -> Dict:
        """
        Upload and process multiple media files
        Returns URLs and metadata for uploaded files
        """
        if not files:
            return {"success": True, "media": []}
        
        if len(files) > 10:  # Limit number of files per upload
            raise HTTPException(400, "Maximum 10 files allowed per upload")
        
        uploaded_media = []
        
        try:
            for file in files:
                # Validate file
                file_info = await self._validate_file(file)
                
                # Generate secure storage path
                storage_path = await self._generate_storage_path(user_id, file.filename, file_info['type'])
                
                # Read file content as bytes (critical for binary integrity!)
                file.file.seek(0)  # Ensure we're at the start
                file_content = await file.read()
                
                # Verify we got bytes
                if not isinstance(file_content, bytes):
                    raise ValueError(f"File read did not return bytes: got {type(file_content)}")
                
                # Log for debugging
                if os.getenv('ENVIRONMENT') == 'dev':
                    logger.debug(f"Read {len(file_content)} bytes, first 8: {file_content[:8].hex()}")
                
                # Process file (resize, generate thumbnail, etc.)
                processed_data = await self._process_media_file(
                    file_content, file_info, storage_path
                )
                
                # Upload to storage
                file_url = await self._upload_to_storage(
                    file_content, storage_path, file_info['mime_type']
                )
                
                # Upload thumbnail if generated
                thumbnail_url = None
                if processed_data.get('thumbnail'):
                    thumbnail_path = storage_path.replace('.', '_thumb.')
                    thumbnail_url = await self._upload_to_storage(
                        processed_data['thumbnail'], thumbnail_path, 'image/jpeg'
                    )
                
                # Store in temporary uploads table
                # TEMPORARY WORKAROUND: Use 'image' type for documents until DB constraint is updated
                db_file_type = file_info['type']
                if db_file_type == 'document':
                    db_file_type = 'image'  # Temporary workaround
                    logger.info(f"Using 'image' type for document upload (workaround for DB constraint)")
                
                temp_media_record = await self._store_temp_media({
                    'user_id': user_id,
                    'original_filename': file.filename,
                    'file_url': file_url,
                    'thumbnail_url': thumbnail_url,
                    'file_type': db_file_type,
                    'file_size': file_info['size'],
                    'mime_type': file_info['mime_type'],
                    'width': processed_data.get('width'),
                    'height': processed_data.get('height'),
                    'duration': processed_data.get('duration'),
                    'storage_path': storage_path
                })
                
                uploaded_media.append({
                    'media_id': temp_media_record['id'],
                    'url': file_url,
                    'storage_path': storage_path,  # Include storage path for signed URL generation
                    'thumbnail_url': thumbnail_url,
                    'type': file_info['type'],
                    'filename': file.filename,
                    'size': file_info['size'],
                    'width': processed_data.get('width'),
                    'height': processed_data.get('height'),
                    'duration': processed_data.get('duration')
                })
                
        except Exception as e:
            logger.error(f"Media upload failed: {str(e)}")
            # TODO: Cleanup any partially uploaded files
            raise HTTPException(500, f"Upload failed: {str(e)}")
        
        return {
            "success": True,
            "media": uploaded_media
        }
    
    async def _validate_file(self, file: UploadFile) -> Dict:
        """Validate file type, size, and content"""
        
        # Check file size
        file.file.seek(0, 2)  # Seek to end
        size = file.file.tell()
        file.file.seek(0)  # Reset to beginning
        
        # Determine file type and validate
        mime_type = file.content_type or mimetypes.guess_type(file.filename)[0]
        
        if mime_type in self.ALLOWED_IMAGE_TYPES:
            file_type = 'image'
            max_size = self.MAX_IMAGE_SIZE
        elif mime_type in self.ALLOWED_VIDEO_TYPES:
            file_type = 'video'
            max_size = self.MAX_VIDEO_SIZE
        elif mime_type in self.ALLOWED_AUDIO_TYPES:
            file_type = 'audio'
            max_size = self.MAX_AUDIO_SIZE
        elif mime_type in self.ALLOWED_DOCUMENT_TYPES:
            file_type = 'document'
            max_size = self.MAX_DOCUMENT_SIZE
        else:
            raise HTTPException(400, f"Unsupported file type: {mime_type}")
        
        if size > max_size:
            max_mb = max_size / (1024 * 1024)
            raise HTTPException(400, f"File too large. Maximum size: {max_mb}MB")
        
        return {
            'type': file_type,
            'mime_type': mime_type,
            'size': size
        }
    
    async def _generate_storage_path(self, user_id: str, filename: str, file_type: str) -> str:
        """Generate secure, user-scoped storage path"""
        try:
            # Only try RPC function if user_id is a valid UUID format
            import re
            uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            
            if re.match(uuid_pattern, user_id):
                result = self.supabase_client.service_client.rpc(
                    'generate_secure_media_path',
                    {
                        'user_id': user_id,
                        'filename': filename,
                        'file_type': file_type
                    }
                ).execute()
                
                return result.data
            else:
                # User ID is not a UUID, skip RPC and use fallback
                raise Exception("User ID not in UUID format, using fallback")
                
        except Exception as e:
            logger.debug(f"Using fallback path generation: {str(e)}")
            # Fallback path generation
            file_extension = Path(filename).suffix.lower()
            unique_filename = f"{hashlib.md5(f'{user_id}{filename}{datetime.utcnow()}'.encode()).hexdigest()}{file_extension}"
            return f"media/{user_id}/{datetime.now().strftime('%Y/%m')}/{unique_filename}"
    
    async def _process_media_file(self, file_content: bytes, file_info: Dict, storage_path: str) -> Dict:
        """Process media file (resize images, extract video thumbnails, etc.)"""
        processed_data = {}
        
        try:
            if file_info['type'] == 'image':
                processed_data = await self._process_image(file_content)
            elif file_info['type'] == 'video':
                processed_data = await self._process_video(file_content, storage_path)
            elif file_info['type'] == 'audio':
                processed_data = await self._process_audio(file_content)
            elif file_info['type'] == 'document':
                # Documents don't need processing, just return empty data
                processed_data = {}
                
        except Exception as e:
            logger.warning(f"Media processing failed (non-fatal): {str(e)}")
            # Continue without processing if it fails
        
        return processed_data
    
    async def _process_image(self, image_content: bytes) -> Dict:
        """Process image: resize if needed, generate thumbnail"""
        try:
            # Open image
            from io import BytesIO
            image = Image.open(BytesIO(image_content))
            
            # Get original dimensions
            width, height = image.size
            
            # Resize if too large
            if width > self.MAX_IMAGE_DIMENSION or height > self.MAX_IMAGE_DIMENSION:
                image.thumbnail((self.MAX_IMAGE_DIMENSION, self.MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)
                width, height = image.size
            
            # Generate thumbnail
            thumbnail = image.copy()
            thumbnail.thumbnail(self.THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
            
            # Convert thumbnail to bytes
            thumbnail_io = BytesIO()
            thumbnail.save(thumbnail_io, format='JPEG', quality=85)
            thumbnail_bytes = thumbnail_io.getvalue()
            
            return {
                'width': width,
                'height': height,
                'thumbnail': thumbnail_bytes
            }
            
        except Exception as e:
            logger.error(f"Image processing failed: {str(e)}")
            return {}
    
    async def _process_video(self, video_content: bytes, storage_path: str) -> Dict:
        """Process video: extract thumbnail and duration"""
        try:
            # This would require ffmpeg-python or similar
            # For now, return empty dict
            # TODO: Implement video processing
            return {}
        except Exception as e:
            logger.error(f"Video processing failed: {str(e)}")
            return {}
    
    async def _process_audio(self, audio_content: bytes) -> Dict:
        """Process audio: extract duration"""
        try:
            # This would require ffmpeg-python or similar  
            # For now, return empty dict
            # TODO: Implement audio processing
            return {}
        except Exception as e:
            logger.error(f"Audio processing failed: {str(e)}")
            return {}
    
    async def _upload_to_storage(self, file_content: bytes, storage_path: str, mime_type: str) -> str:
        """Upload file to Cloudflare R2 with binary integrity protection"""
        try:
            # Verify input is bytes
            if not isinstance(file_content, bytes):
                raise ValueError(f"Expected bytes, got {type(file_content)}")
            
            # Log first few bytes for debugging (only in dev mode)
            if os.getenv('ENVIRONMENT') == 'dev':
                logger.debug(f"Upload debug - first 8 bytes: {file_content[:8].hex()}")
            
            # Upload to R2 with explicit binary handling
            upload_params = {
                'Bucket': self.r2_bucket,
                'Key': storage_path,
                'Body': file_content,  # Ensure this stays as bytes
                'ContentType': mime_type,
                # Add cache control headers for better performance
                'CacheControl': 'public, max-age=31536000'
            }
            
            # Don't set ContentEncoding at all for binary files to avoid parameter validation errors
            self.r2_client.put_object(**upload_params)
            
            # Generate public URL
            url_path = storage_path
            public_url = f"{self.r2_public_url}/{url_path}"
            
            # Verify upload integrity (optional, for debugging)
            if os.getenv('ENVIRONMENT') == 'dev' and mime_type.startswith('image/'):
                await self._verify_upload_integrity(file_content, public_url)
            
            return public_url
            
        except Exception as e:
            logger.error(f"R2 upload failed: {str(e)}")
            raise HTTPException(500, f"Failed to upload to storage: {str(e)}")
    
    async def _verify_upload_integrity(self, original_content: bytes, public_url: str):
        """Verify that uploaded content matches original (dev mode only)"""
        try:
            import requests
            response = requests.get(public_url, timeout=5)
            if response.status_code == 200:
                uploaded_content = response.content
                if len(uploaded_content) == len(original_content):
                    if uploaded_content[:8] == original_content[:8]:
                        logger.debug("✅ Upload integrity verified")
                    else:
                        logger.error(f"❌ Upload corruption detected - signature mismatch")
                        logger.error(f"Original: {original_content[:8].hex()}")
                        logger.error(f"Uploaded: {uploaded_content[:8].hex()}")
                else:
                    logger.error(f"❌ Upload size mismatch: {len(original_content)} vs {len(uploaded_content)}")
        except Exception as e:
            logger.warning(f"Upload verification failed: {e}")
    
    async def _store_temp_media(self, media_data: Dict) -> Dict:
        """Store temporary media record in database"""
        try:
            result = self.supabase_client.service_client.table("temp_media_uploads").insert(media_data).execute()
            
            if not result.data:
                raise Exception("Failed to store temp media record")
            
            return result.data[0]
            
        except Exception as e:
            logger.error(f"Failed to store temp media: {str(e)}")
            raise HTTPException(500, "Failed to store media record")
    
    async def mark_media_as_used(self, media_urls: List[str], user_id: str) -> bool:
        """Mark temporary media as used when creating a post"""
        try:
            result = self.supabase_client.service_client.rpc(
                'mark_temp_media_as_used',
                {
                    'media_urls': media_urls,
                    'p_user_id': user_id  # Pass user_id to function
                }
            ).execute()

            logger.info(f"Marked {len(media_urls)} media files as used for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to mark media as used: {str(e)}")
            return False
    
    async def delete_from_storage(self, storage_paths: List[str]) -> bool:
        """Delete files from R2 storage"""
        try:
            if not storage_paths:
                return True
                
            # Delete multiple objects
            objects = [{'Key': path} for path in storage_paths]
            response = self.r2_client.delete_objects(
                Bucket=self.r2_bucket,
                Delete={
                    'Objects': objects,
                    'Quiet': True
                }
            )
            
            # Check for errors
            if 'Errors' in response:
                logger.error(f"R2 deletion errors: {response['Errors']}")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"R2 deletion failed: {str(e)}")
            return False
    

    def generate_signed_url(self, storage_path: str, expiry: int = 3600, bucket: str = None) -> str:
        """
        Generate a signed URL for a file in R2 storage (synchronous method)
        Uses in-memory caching to avoid regenerating URLs

        Args:
            storage_path: The path to the file in R2 (e.g., 'partners/logo.png')
            expiry: URL expiration time in seconds (default: 3600 = 1 hour)
            bucket: Optional bucket name (defaults to self.r2_bucket)

        Returns:
            Signed URL string

        Note: This is a synchronous method because generate_presigned_url is not I/O bound
        """
        try:
            bucket_name = bucket or self.r2_bucket

            # Create a cache key that includes the bucket name for multi-bucket support
            cache_key = f"{bucket_name}/{storage_path}" if bucket_name != self.r2_bucket else storage_path

            # Check cache first
            cache_service = get_signed_url_cache_service()
            cached_url = cache_service.get(cache_key, expiry)
            if cached_url:
                return cached_url

            # Generate new signed URL if not in cache
            url = self.r2_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': bucket_name,
                    'Key': storage_path
                },
                ExpiresIn=expiry
            )

            # Cache the generated URL
            cache_service.set(cache_key, url, expiry)

            return url
        except Exception as e:
            logger.error(f"Failed to generate signed URL for {storage_path}: {str(e)}")
            raise