"""
File Attachments Service
Handle image, video, and document attachments for messages
"""
from typing import Dict, List, Any, Optional, Tuple
import os
import mimetypes
from datetime import datetime, timezone
from supabase import Client
import logging

logger = logging.getLogger(__name__)

class FileAttachmentsService:
    def __init__(self, supabase: Client):
        self.supabase = supabase
        
        # File size limits (in bytes)
        self.max_file_sizes = {
            'image': 10 * 1024 * 1024,    # 10MB for images
            'video': 100 * 1024 * 1024,   # 100MB for videos
            'document': 25 * 1024 * 1024  # 25MB for documents
        }
        
        # Supported MIME types
        self.supported_types = {
            'image': [
                'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 
                'image/webp', 'image/svg+xml'
            ],
            'video': [
                'video/mp4', 'video/webm', 'video/quicktime', 'video/x-msvideo',
                'video/mpeg', 'video/ogg'
            ],
            'document': [
                'application/pdf', 'text/plain', 'text/csv',
                'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'application/vnd.ms-powerpoint', 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                'application/zip', 'application/x-zip-compressed'
            ]
        }
        
        # Storage buckets
        self.storage_buckets = {
            'image': 'message-images',
            'video': 'message-videos',
            'document': 'message-documents'
        }
    
    async def upload_attachment(
        self,
        user_id: str,
        file_data: bytes,
        filename: str,
        mime_type: str,
        conversation_id: str
    ) -> Dict[str, Any]:
        """Upload a file attachment and return attachment info"""
        try:
            # Validate file
            validation_result = await self._validate_file(file_data, filename, mime_type)
            if not validation_result["success"]:
                return validation_result
            
            attachment_type = validation_result["data"]["attachment_type"]
            file_size = len(file_data)
            
            # Generate unique filename
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            safe_filename = self._sanitize_filename(filename)
            unique_filename = f"{user_id}_{timestamp}_{safe_filename}"
            
            # Determine storage bucket and path
            bucket = self.storage_buckets[attachment_type]
            file_path = f"{conversation_id}/{unique_filename}"
            
            # Upload to storage
            upload_result = self.supabase.storage \
                .from_(bucket) \
                .upload(file_path, file_data, {"content-type": mime_type})
            
            if upload_result.get('error'):
                logger.error(f"Storage upload error: {upload_result['error']}")
                return {"success": False, "error": "Failed to upload file"}
            
            # Get public URL
            public_url_result = self.supabase.storage \
                .from_(bucket) \
                .get_public_url(file_path)
            
            file_url = public_url_result.get('publicURL') or public_url_result.get('publicUrl')
            
            # Generate additional metadata based on file type
            metadata = await self._generate_file_metadata(file_data, attachment_type, mime_type)
            
            return {
                "success": True,
                "data": {
                    "url": file_url,
                    "type": attachment_type,
                    "filename": filename,
                    "unique_filename": unique_filename,
                    "size": file_size,
                    "mime_type": mime_type,
                    "metadata": metadata
                }
            }
            
        except Exception as e:
            logger.error(f"Error uploading attachment: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_attachment_info(
        self,
        message_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """Get attachment information for a message"""
        try:
            # Get message with attachment info
            result = self.supabase.table('messages') \
                .select('''
                    id, attachment_url, attachment_type, attachment_filename,
                    attachment_size, attachment_mime_type,
                    conversation_id,
                    conversation:conversations!inner(
                        id,
                        participants:conversation_participants!inner(user_id)
                    )
                ''') \
                .eq('id', message_id) \
                .in_('message_type', ['image', 'video', 'file']) \
                .single() \
                .execute()
            
            if not result.data:
                return {"success": False, "error": "Attachment not found"}
            
            message = result.data
            
            # Verify user has access to this conversation
            participant_ids = [
                p['user_id'] for p in message['conversation']['participants']
            ]
            
            if user_id not in participant_ids:
                return {"success": False, "error": "Unauthorized access"}
            
            return {
                "success": True,
                "data": {
                    "url": message['attachment_url'],
                    "type": message['attachment_type'],
                    "filename": message['attachment_filename'],
                    "size": message['attachment_size'],
                    "mime_type": message['attachment_mime_type']
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting attachment info: {e}")
            return {"success": False, "error": str(e)}
    
    async def delete_attachment(
        self,
        message_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """Delete an attachment file from storage"""
        try:
            # Get message details and verify ownership
            result = self.supabase.table('messages') \
                .select('id, attachment_url, attachment_type, sender_id, conversation_id') \
                .eq('id', message_id) \
                .eq('sender_id', user_id) \
                .single() \
                .execute()
            
            if not result.data:
                return {"success": False, "error": "Attachment not found or unauthorized"}
            
            message = result.data
            attachment_url = message['attachment_url']
            attachment_type = message['attachment_type']
            
            # Extract file path and delete from storage
            if attachment_url and attachment_type:
                file_path = self._extract_file_path_from_url(attachment_url, attachment_type)
                
                if file_path:
                    bucket = self.storage_buckets[attachment_type]
                    delete_result = self.supabase.storage \
                        .from_(bucket) \
                        .remove([file_path])
                    
                    if delete_result.get('error'):
                        logger.warning(f"Failed to delete attachment file: {delete_result['error']}")
            
            return {"success": True}
            
        except Exception as e:
            logger.error(f"Error deleting attachment: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_conversation_attachments(
        self,
        conversation_id: str,
        user_id: str,
        attachment_type: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Get all attachments in a conversation"""
        try:
            # Verify user has access to conversation
            access_check = self.supabase.table('conversation_participants') \
                .select('id') \
                .eq('conversation_id', conversation_id) \
                .eq('user_id', user_id) \
                .is_('left_at', 'null') \
                .execute()
            
            if not access_check.data:
                return {"success": False, "error": "Unauthorized access"}
            
            # Build query for messages with attachments
            query = self.supabase.table('messages') \
                .select('''
                    id, attachment_url, attachment_type, attachment_filename,
                    attachment_size, attachment_mime_type, created_at,
                    sender:auth.users(id, email)
                ''') \
                .eq('conversation_id', conversation_id) \
                .eq('is_deleted', False) \
                .not_.is_('attachment_url', 'null')
            
            # Filter by attachment type if specified
            if attachment_type:
                query = query.eq('attachment_type', attachment_type)
            
            result = query \
                .order('created_at', desc=True) \
                .range(offset, offset + limit - 1) \
                .execute()
            
            attachments = result.data or []
            
            # Group by type for summary
            type_counts = {}
            total_size = 0
            
            for attachment in attachments:
                att_type = attachment['attachment_type']
                if att_type:
                    type_counts[att_type] = type_counts.get(att_type, 0) + 1
                    total_size += attachment['attachment_size'] or 0
            
            return {
                "success": True,
                "data": {
                    "attachments": attachments,
                    "summary": {
                        "total_count": len(attachments),
                        "type_counts": type_counts,
                        "total_size_bytes": total_size,
                        "total_size_mb": round(total_size / (1024 * 1024), 2)
                    }
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting conversation attachments: {e}")
            return {"success": False, "error": str(e)}
    
    async def generate_image_thumbnail(
        self,
        image_url: str,
        size: Tuple[int, int] = (300, 300)
    ) -> Dict[str, Any]:
        """Generate thumbnail for an image (future feature)"""
        try:
            # This would integrate with image processing services like:
            # - PIL/Pillow for Python
            # - ImageMagick
            # - Cloud services (AWS Lambda, Cloudinary, etc.)
            
            # For now, return the original URL
            return {
                "success": True,
                "data": {
                    "thumbnail_url": image_url,
                    "original_url": image_url,
                    "width": size[0],
                    "height": size[1]
                }
            }
            
        except Exception as e:
            logger.error(f"Error generating thumbnail: {e}")
            return {"success": False, "error": str(e)}
    
    async def scan_file_for_security(
        self,
        file_data: bytes,
        filename: str,
        mime_type: str
    ) -> Dict[str, Any]:
        """Scan file for security threats (future feature)"""
        try:
            # This would integrate with security scanning services like:
            # - ClamAV for virus scanning
            # - Cloud security APIs
            # - Custom malware detection
            
            # Basic checks
            if len(file_data) == 0:
                return {"success": False, "error": "Empty file"}
            
            # Check for suspicious file extensions
            dangerous_extensions = ['.exe', '.bat', '.scr', '.com', '.cmd', '.pif']
            if any(filename.lower().endswith(ext) for ext in dangerous_extensions):
                return {"success": False, "error": "Potentially dangerous file type"}
            
            return {
                "success": True,
                "data": {
                    "clean": True,
                    "scan_result": "File appears safe",
                    "threats_found": []
                }
            }
            
        except Exception as e:
            logger.error(f"Error scanning file: {e}")
            return {"success": False, "error": str(e)}
    
    # VALIDATION AND HELPER METHODS
    
    async def _validate_file(
        self,
        file_data: bytes,
        filename: str,
        mime_type: str
    ) -> Dict[str, Any]:
        """Validate file before upload"""
        try:
            file_size = len(file_data)
            
            if file_size == 0:
                return {"success": False, "error": "Empty file"}
            
            # Determine attachment type
            attachment_type = self._get_attachment_type(mime_type, filename)
            
            if not attachment_type:
                return {"success": False, "error": f"Unsupported file type: {mime_type}"}
            
            # Check file size limits
            max_size = self.max_file_sizes[attachment_type]
            if file_size > max_size:
                max_size_mb = max_size / (1024 * 1024)
                return {
                    "success": False, 
                    "error": f"File too large. Maximum size for {attachment_type} files: {max_size_mb}MB"
                }
            
            # Security scan
            security_result = await self.scan_file_for_security(file_data, filename, mime_type)
            if not security_result["success"]:
                return security_result
            
            return {
                "success": True,
                "data": {
                    "attachment_type": attachment_type,
                    "file_size": file_size,
                    "security_scan": security_result["data"]
                }
            }
            
        except Exception as e:
            logger.error(f"Error validating file: {e}")
            return {"success": False, "error": str(e)}
    
    def _get_attachment_type(self, mime_type: str, filename: str) -> Optional[str]:
        """Determine attachment type from MIME type and filename"""
        # First check MIME type
        for attachment_type, mime_types in self.supported_types.items():
            if mime_type in mime_types:
                return attachment_type
        
        # Fallback to file extension
        file_extension = os.path.splitext(filename)[1].lower()
        
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg']
        video_extensions = ['.mp4', '.webm', '.mov', '.avi', '.mpeg', '.ogg']
        
        if file_extension in image_extensions:
            return 'image'
        elif file_extension in video_extensions:
            return 'video'
        else:
            return 'document'
    
    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for safe storage"""
        # Remove or replace dangerous characters
        import re
        
        # Keep only alphanumeric, dots, dashes, and underscores
        safe_filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
        
        # Ensure filename isn't too long
        if len(safe_filename) > 100:
            name, ext = os.path.splitext(safe_filename)
            safe_filename = name[:90] + ext
        
        return safe_filename
    
    def _extract_file_path_from_url(self, url: str, attachment_type: str) -> Optional[str]:
        """Extract storage file path from public URL"""
        try:
            bucket_path = f'/{self.storage_buckets[attachment_type]}/'
            if bucket_path in url:
                return url.split(bucket_path)[-1].split('?')[0]
            return None
        except Exception as e:
            logger.error(f"Error extracting file path: {e}")
            return None
    
    async def _generate_file_metadata(
        self,
        file_data: bytes,
        attachment_type: str,
        mime_type: str
    ) -> Dict[str, Any]:
        """Generate metadata based on file type"""
        try:
            metadata = {
                "file_size_formatted": self._format_file_size(len(file_data)),
                "upload_timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            if attachment_type == 'image':
                # For images, you could extract dimensions, color info, etc.
                metadata.update({
                    "width": None,  # Would be extracted using PIL
                    "height": None,
                    "has_transparency": None,
                    "color_mode": None
                })
            
            elif attachment_type == 'video':
                # For videos, you could extract duration, resolution, etc.
                metadata.update({
                    "duration_seconds": None,  # Would be extracted using ffmpeg
                    "width": None,
                    "height": None,
                    "fps": None,
                    "codec": None
                })
            
            elif attachment_type == 'document':
                # For documents, you could extract page count, text content, etc.
                metadata.update({
                    "page_count": None,  # Would be extracted using appropriate library
                    "word_count": None,
                    "has_images": None,
                    "is_encrypted": None
                })
            
            return metadata
            
        except Exception as e:
            logger.error(f"Error generating metadata: {e}")
            return {}
    
    def _format_file_size(self, size_bytes: int) -> str:
        """Format file size in human readable format"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    
    # STORAGE MANAGEMENT
    
    async def cleanup_orphaned_files(self, conversation_id: str) -> Dict[str, Any]:
        """Clean up files that are no longer referenced by messages"""
        try:
            # Get all file URLs from messages in conversation
            messages_result = self.supabase.table('messages') \
                .select('attachment_url, attachment_type') \
                .eq('conversation_id', conversation_id) \
                .not_.is_('attachment_url', 'null') \
                .execute()
            
            referenced_files = set()
            for message in messages_result.data or []:
                if message['attachment_url'] and message['attachment_type']:
                    file_path = self._extract_file_path_from_url(
                        message['attachment_url'], 
                        message['attachment_type']
                    )
                    if file_path:
                        referenced_files.add((message['attachment_type'], file_path))
            
            # This is a placeholder for actual cleanup logic
            # In production, you'd list all files in the conversation folder
            # and delete those not in referenced_files
            
            return {
                "success": True,
                "data": {
                    "referenced_files_count": len(referenced_files),
                    "cleanup_performed": False,  # Would be True after actual cleanup
                    "files_removed": 0
                }
            }
            
        except Exception as e:
            logger.error(f"Error cleaning up orphaned files: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_storage_usage_stats(self, user_id: str) -> Dict[str, Any]:
        """Get user's storage usage statistics"""
        try:
            # Get user's attachment usage
            result = self.supabase.table('messages') \
                .select('attachment_type, attachment_size') \
                .eq('sender_id', user_id) \
                .eq('is_deleted', False) \
                .not_.is_('attachment_url', 'null') \
                .execute()
            
            attachments = result.data or []
            
            # Calculate usage by type
            usage_by_type = {}
            total_size = 0
            
            for attachment in attachments:
                att_type = attachment['attachment_type']
                size = attachment['attachment_size'] or 0
                
                if att_type not in usage_by_type:
                    usage_by_type[att_type] = {'count': 0, 'size_bytes': 0}
                
                usage_by_type[att_type]['count'] += 1
                usage_by_type[att_type]['size_bytes'] += size
                total_size += size
            
            # Format sizes
            for att_type in usage_by_type:
                usage_by_type[att_type]['size_formatted'] = self._format_file_size(
                    usage_by_type[att_type]['size_bytes']
                )
            
            return {
                "success": True,
                "data": {
                    "total_attachments": len(attachments),
                    "total_size_bytes": total_size,
                    "total_size_formatted": self._format_file_size(total_size),
                    "usage_by_type": usage_by_type,
                    "storage_limit_bytes": 1024 * 1024 * 1024,  # 1GB example limit
                    "usage_percentage": (total_size / (1024 * 1024 * 1024)) * 100
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting storage usage stats: {e}")
            return {"success": False, "error": str(e)}