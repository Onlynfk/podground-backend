"""
Article Content Service - Manages article content storage in R2
Stores and retrieves markdown content for resources
"""

import os
import uuid
from typing import Optional, Dict, Any
import logging
import boto3
from botocore.config import Config
from datetime import datetime
import unicodedata

logger = logging.getLogger(__name__)


class ArticleContentService:
    def __init__(self):
        """Initialize R2 client for article content storage"""
        self.r2_bucket = os.getenv("R2_BUCKET_NAME")
        if not self.r2_bucket:
            raise ValueError("R2_BUCKET_NAME environment variable is required")

        self.r2_account_id = os.getenv("R2_ACCOUNT_ID")

        # Initialize R2 client
        self.r2_client = boto3.client(
            "s3",
            endpoint_url=f"https://{self.r2_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )

        # Public URL pattern for R2
        self.r2_public_url = os.getenv(
            "R2_PUBLIC_URL", f"https://content.podground.com"
        )

    async def upload_article_content(
        self,
        resource_id: str,
        content: str,
        title: str,
        author: str = "PodGround Team",
    ) -> Dict[str, Any]:
        """
        Upload article content as markdown to R2

        Args:
            resource_id: The resource UUID
            content: The markdown content
            title: Article title for metadata
            author: Article author for metadata

        Returns:
            Dict with content_url and metadata
        """
        try:
            # Generate filename
            filename = f"articles/{resource_id}/content.md"

            # Add metadata header to markdown
            metadata_header = f"""---
title: {title}
author: {author}
resource_id: {resource_id}
created_at: {datetime.utcnow().isoformat()}
format: markdown
---

"""
            full_content = metadata_header + content

            # Upload to R2
            metadata = {
                "resource-id": resource_id,
                "title": self._sanitize_metadata_value(title),
                "author": self._sanitize_metadata_value(author),
            }

            self.r2_client.put_object(
                Bucket=self.r2_bucket,
                Key=filename,
                Body=full_content.encode("utf-8"),
                ContentType="text/markdown",
                Metadata=metadata,
            )

            # Generate URLs
            content_url = f"{self.r2_public_url}/{filename}"

            logger.info(
                f"Successfully uploaded article content for resource {resource_id}"
            )

            return {
                "success": True,
                "content_url": content_url,
                "storage_path": filename,
                "size_bytes": len(full_content.encode("utf-8")),
            }

        except Exception as e:
            logger.error(f"Error uploading article content: {str(e)}")
            return {"success": False, "error": str(e)}

    async def get_article_content(self, resource_id: str) -> Optional[str]:
        """
        Retrieve article content from R2

        Args:
            resource_id: The resource UUID

        Returns:
            The markdown content or None if not found
        """
        try:
            filename = f"articles/{resource_id}/content.md"

            response = self.r2_client.get_object(
                Bucket=self.r2_bucket, Key=filename
            )

            content = response["Body"].read().decode("utf-8")

            # Strip metadata header if present
            if content.startswith("---"):
                # Find the closing --- and skip to content
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    content = parts[2].strip()

            return content

        except self.r2_client.exceptions.NoSuchKey:
            logger.warning(
                f"Article content not found for resource {resource_id}"
            )
            return None
        except Exception as e:
            logger.error(f"Error retrieving article content: {str(e)}")
            return None

    async def update_article_content(
        self,
        resource_id: str,
        content: str,
        title: Optional[str] = None,
        author: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update existing article content

        Args:
            resource_id: The resource UUID
            content: The new markdown content
            title: Updated title (optional)
            author: Updated author (optional)

        Returns:
            Dict with update status
        """
        try:
            # Get existing metadata if not provided
            if not title or not author:
                existing = await self.get_article_metadata(resource_id)
                if existing:
                    title = title or existing.get("title", "Untitled")
                    author = author or existing.get("author", "PodGround Team")
                else:
                    title = title or "Untitled"
                    author = author or "PodGround Team"

            # Upload with updated content
            result = await self.upload_article_content(
                resource_id=resource_id,
                content=content,
                title=title,
                author=author,
            )

            if result["success"]:
                result["updated_at"] = datetime.utcnow().isoformat()

            return result

        except Exception as e:
            logger.error(f"Error updating article content: {str(e)}")
            return {"success": False, "error": str(e)}

    async def get_article_metadata(
        self, resource_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get article metadata from R2

        Args:
            resource_id: The resource UUID

        Returns:
            Metadata dict or None if not found
        """
        try:
            filename = f"articles/{resource_id}/content.md"

            response = self.r2_client.head_object(
                Bucket=self.r2_bucket, Key=filename
            )

            return {
                "size_bytes": response.get("ContentLength", 0),
                "content_type": response.get("ContentType", "text/markdown"),
                "last_modified": response.get("LastModified"),
                "metadata": response.get("Metadata", {}),
                "title": response.get("Metadata", {}).get("title"),
                "author": response.get("Metadata", {}).get("author"),
            }

        except self.r2_client.exceptions.NoSuchKey:
            return None
        except Exception as e:
            logger.error(f"Error getting article metadata: {str(e)}")
            return None

    async def delete_article_content(self, resource_id: str) -> bool:
        """
        Delete article content from R2

        Args:
            resource_id: The resource UUID

        Returns:
            True if deleted, False otherwise
        """
        try:
            filename = f"articles/{resource_id}/content.md"

            self.r2_client.delete_object(Bucket=self.r2_bucket, Key=filename)

            logger.info(f"Deleted article content for resource {resource_id}")
            return True

        except Exception as e:
            logger.error(f"Error deleting article content: {str(e)}")
            return False

    async def generate_article_url(self, resource_id: str) -> str:
        """
        Generate a public URL for article content

        Args:
            resource_id: The resource UUID

        Returns:
            The public URL for the article
        """
        filename = f"articles/{resource_id}/content.md"
        return f"{self.r2_public_url}/{filename}"

    def _sanitize_metadata_value(self, value: str) -> str:
        """
        Ensure metadata values contain only ASCII characters as required by S3.
        Non-ASCII characters are normalized and stripped.
        """
        normalized = unicodedata.normalize("NFKD", value or "")
        return normalized.encode("ascii", "ignore").decode("ascii")


# Create singleton instance
article_content_service = ArticleContentService()
