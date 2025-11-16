"""
Resource PDF Guide Service - Handles PDF guide uploads for articles and videos
"""

import os
import uuid
import boto3
from typing import Dict, Optional
import logging
from botocore.client import Config
from fastapi import UploadFile
import mimetypes

from signed_url_cache_service import get_signed_url_cache_service

logger = logging.getLogger(__name__)

class ResourcePDFService:
    """Service for managing PDF guides for resources (articles/videos)"""
    
    def __init__(self):
        self.r2_account_id = os.getenv('R2_ACCOUNT_ID')
        self.r2_access_key_id = os.getenv('R2_ACCESS_KEY_ID')
        self.r2_secret_access_key = os.getenv('R2_SECRET_ACCESS_KEY')
        self.r2_bucket_name = os.getenv('R2_BUCKET_NAME')

        if not self.r2_bucket_name:
            raise ValueError("R2_BUCKET_NAME environment variable is required")

        if not all([self.r2_account_id, self.r2_access_key_id, self.r2_secret_access_key]):
            logger.warning("R2 credentials not found. PDF uploads will not work.")
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
    
    def generate_pdf_key(self, resource_id: str, resource_type: str) -> str:
        """Generate the S3 key for a resource PDF guide"""
        return f"resource-guides/{resource_type}s/{resource_id}/guide.pdf"
    
    async def upload_pdf_guide(
        self, 
        resource_id: str,
        resource_type: str,
        pdf_file: UploadFile
    ) -> Dict[str, any]:
        """
        Upload a PDF guide for a resource
        
        Args:
            resource_id: The resource ID
            resource_type: 'article' or 'video'
            pdf_file: The uploaded PDF file
        
        Returns:
            Dict with success status and URL
        """
        if not self.s3_client:
            return {
                "success": False,
                "error": "Storage service not configured"
            }
        
        try:
            # Validate file type
            if not pdf_file.filename.lower().endswith('.pdf'):
                return {
                    "success": False,
                    "error": "File must be a PDF"
                }
            
            # Check file size (max 10MB for PDFs)
            content = await pdf_file.read()
            if len(content) > 10 * 1024 * 1024:
                return {
                    "success": False,
                    "error": "PDF file size must be less than 10MB"
                }
            
            # Generate S3 key
            s3_key = self.generate_pdf_key(resource_id, resource_type)
            
            # Upload to R2
            self.s3_client.put_object(
                Bucket=self.r2_bucket_name,
                Key=s3_key,
                Body=content,
                ContentType='application/pdf',
                ContentDisposition='attachment',
                Metadata={
                    'resource_id': resource_id,
                    'resource_type': resource_type,
                    'original_filename': pdf_file.filename
                }
            )
            
            # Generate public URL
            public_url = f"https://{self.r2_bucket_name}.{self.r2_account_id}.r2.cloudflarestorage.com/{s3_key}"
            
            logger.info(f"Successfully uploaded PDF guide for {resource_type} {resource_id}")
            
            return {
                "success": True,
                "url": public_url,
                "key": s3_key
            }
            
        except Exception as e:
            logger.error(f"Error uploading PDF guide: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def generate_download_url(
        self,
        resource_id: str,
        resource_type: str,
        expiry_seconds: int = 3600  # 1 hour default
    ) -> Optional[str]:
        """
        Generate a presigned URL for downloading a resource PDF guide
        Uses in-memory caching to avoid regenerating URLs
        """
        if not self.s3_client:
            logger.error("R2 client not initialized")
            return None

        try:
            s3_key = self.generate_pdf_key(resource_id, resource_type)

            # Create cache key with bucket name
            cache_key = f"{self.r2_bucket_name}/{s3_key}"

            # Check cache first
            cache_service = get_signed_url_cache_service()
            cached_url = cache_service.get(cache_key, expiry_seconds)
            if cached_url:
                return cached_url

            # Check if file exists
            try:
                self.s3_client.head_object(Bucket=self.r2_bucket_name, Key=s3_key)
            except:
                logger.warning(f"PDF guide not found for {resource_type} {resource_id}")
                return None

            # Generate presigned URL with download headers
            download_url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.r2_bucket_name,
                    'Key': s3_key,
                    'ResponseContentDisposition': 'attachment; filename="guide.pdf"'
                },
                ExpiresIn=expiry_seconds
            )

            # Cache the generated URL
            cache_service.set(cache_key, download_url, expiry_seconds)

            return download_url

        except Exception as e:
            logger.error(f"Error generating download URL: {str(e)}")
            return None
    
    async def delete_pdf_guide(
        self,
        resource_id: str,
        resource_type: str
    ) -> Dict[str, any]:
        """Delete a PDF guide for a resource"""
        if not self.s3_client:
            return {
                "success": False,
                "error": "Storage service not configured"
            }
        
        try:
            s3_key = self.generate_pdf_key(resource_id, resource_type)
            
            self.s3_client.delete_object(
                Bucket=self.r2_bucket_name,
                Key=s3_key
            )
            
            logger.info(f"Deleted PDF guide for {resource_type} {resource_id}")
            
            return {"success": True}
            
        except Exception as e:
            logger.error(f"Error deleting PDF guide: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

# Global instance
resource_pdf_service = ResourcePDFService()