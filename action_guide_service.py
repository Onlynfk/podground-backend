"""
Action Guide Service - Handles downloadable PDF action guides for articles
"""

import os
import boto3
from typing import Dict, Optional
import logging
from botocore.client import Config

from signed_url_cache_service import get_signed_url_cache_service

logger = logging.getLogger(__name__)

class ActionGuideService:
    """Service for managing downloadable action guide PDFs in R2"""
    
    def __init__(self):
        self.r2_account_id = os.getenv('R2_ACCOUNT_ID')
        self.r2_access_key_id = os.getenv('R2_ACCESS_KEY_ID')
        self.r2_secret_access_key = os.getenv('R2_SECRET_ACCESS_KEY')
        self.r2_bucket_name = os.getenv('R2_BUCKET_NAME')

        if not self.r2_bucket_name:
            raise ValueError("R2_BUCKET_NAME environment variable is required")

        if not all([self.r2_account_id, self.r2_access_key_id, self.r2_secret_access_key]):
            logger.warning("R2 credentials not found. Action guide downloads will not work.")
            self.s3_client = None
        else:
            # Initialize S3 client for R2
            self.s3_client = boto3.client(
                's3',
                endpoint_url=f'https://{self.r2_account_id}.r2.cloudflarestorage.com',
                aws_access_key_id=self.r2_access_key_id,
                aws_secret_access_key=self.r2_secret_access_key,
                config=Config(signature_version='s3v4')
            )
    
    def generate_action_guide_key(self, resource_id: str, category: str = 'general') -> str:
        """Generate the S3 key for an action guide PDF"""
        return f"action-guides/{category}/{resource_id}_action_guide.pdf"
    
    def generate_download_url(
        self,
        resource_id: str,
        category: str = 'general',
        expiry_seconds: int = 3600  # 1 hour default
    ) -> Optional[str]:
        """
        Generate a presigned URL for downloading an action guide PDF
        The URL will force download rather than display in browser
        Uses in-memory caching to avoid regenerating URLs
        """
        if not self.s3_client:
            logger.error("R2 client not initialized")
            return None

        try:
            key = self.generate_action_guide_key(resource_id, category)

            # Create cache key with bucket name
            cache_key = f"{self.r2_bucket_name}/{key}"

            # Check cache first
            cache_service = get_signed_url_cache_service()
            cached_url = cache_service.get(cache_key, expiry_seconds)
            if cached_url:
                return cached_url

            # Generate presigned URL with Content-Disposition header for download
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.r2_bucket_name,
                    'Key': key,
                    'ResponseContentDisposition': f'attachment; filename="{resource_id}_action_guide.pdf"'
                },
                ExpiresIn=expiry_seconds
            )

            # Cache the generated URL
            cache_service.set(cache_key, url, expiry_seconds)

            return url

        except Exception as e:
            logger.error(f"Error generating download URL for resource {resource_id}: {str(e)}")
            return None
    
    def upload_action_guide(
        self,
        resource_id: str,
        file_content: bytes,
        category: str = 'general',
        content_type: str = 'application/pdf'
    ) -> Dict[str, any]:
        """Upload an action guide PDF to R2"""
        if not self.s3_client:
            return {'success': False, 'error': 'R2 client not initialized'}
        
        try:
            key = self.generate_action_guide_key(resource_id, category)
            
            # Upload with proper content type and disposition
            self.s3_client.put_object(
                Bucket=self.r2_bucket_name,
                Key=key,
                Body=file_content,
                ContentType=content_type,
                ContentDisposition=f'attachment; filename="{resource_id}_action_guide.pdf"'
            )
            
            logger.info(f"Uploaded action guide for resource {resource_id}")
            
            # Generate a download URL
            download_url = self.generate_download_url(resource_id, category)
            
            return {
                'success': True,
                'key': key,
                'download_url': download_url
            }
            
        except Exception as e:
            logger.error(f"Error uploading action guide: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def check_action_guide_exists(self, resource_id: str, category: str = 'general') -> bool:
        """Check if an action guide exists in R2"""
        if not self.s3_client:
            return False
        
        try:
            key = self.generate_action_guide_key(resource_id, category)
            self.s3_client.head_object(Bucket=self.r2_bucket_name, Key=key)
            return True
        except:
            return False
    
    def delete_action_guide(self, resource_id: str, category: str = 'general') -> Dict[str, any]:
        """Delete an action guide from R2"""
        if not self.s3_client:
            return {'success': False, 'error': 'R2 client not initialized'}
        
        try:
            key = self.generate_action_guide_key(resource_id, category)
            self.s3_client.delete_object(Bucket=self.r2_bucket_name, Key=key)
            
            logger.info(f"Deleted action guide for resource {resource_id}")
            return {'success': True}
            
        except Exception as e:
            logger.error(f"Error deleting action guide: {str(e)}")
            return {'success': False, 'error': str(e)}

# Global instance
action_guide_service = ActionGuideService()