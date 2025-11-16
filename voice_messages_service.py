"""
Voice Messages Service
Advanced voice message recording, playback, and waveform generation
"""
from typing import Dict, List, Any, Optional, Tuple
import os
import io
import wave
import json
import base64
from datetime import datetime, timezone
from supabase import Client
import logging

logger = logging.getLogger(__name__)

class VoiceMessagesService:
    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.max_duration_seconds = int(os.getenv("VOICE_MESSAGE_MAX_DURATION", "300"))  # 5 minutes
        self.supported_formats = ['audio/webm', 'audio/mp4', 'audio/wav', 'audio/ogg']
        self.storage_bucket = 'voice-messages'
    
    async def upload_voice_message(
        self,
        user_id: str,
        audio_data: bytes,
        mime_type: str,
        duration_seconds: int,
        waveform_data: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """Upload voice message audio file and process waveform"""
        try:
            # Validate input
            if mime_type not in self.supported_formats:
                return {"success": False, "error": f"Unsupported audio format: {mime_type}"}
            
            if duration_seconds > self.max_duration_seconds:
                return {"success": False, "error": f"Voice message too long (max {self.max_duration_seconds}s)"}
            
            # Generate unique filename
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            file_extension = self._get_file_extension(mime_type)
            filename = f"{user_id}_{timestamp}{file_extension}"
            file_path = f"voice-messages/{filename}"
            
            # Upload audio file to storage
            upload_result = self.supabase.storage \
                .from_(self.storage_bucket) \
                .upload(file_path, audio_data, {"content-type": mime_type})
            
            if upload_result.get('error'):
                logger.error(f"Storage upload error: {upload_result['error']}")
                return {"success": False, "error": "Failed to upload audio file"}
            
            # Get public URL
            public_url_result = self.supabase.storage \
                .from_(self.storage_bucket) \
                .get_public_url(file_path)
            
            audio_url = public_url_result.get('publicURL') or public_url_result.get('publicUrl')
            
            # Generate or validate waveform data
            if not waveform_data:
                waveform_data = await self._generate_waveform(audio_data, mime_type)
            
            waveform_json = json.dumps(waveform_data) if waveform_data else None
            
            return {
                "success": True,
                "data": {
                    "audio_url": audio_url,
                    "duration_seconds": duration_seconds,
                    "waveform": waveform_json,
                    "file_size": len(audio_data),
                    "mime_type": mime_type,
                    "filename": filename
                }
            }
            
        except Exception as e:
            logger.error(f"Error uploading voice message: {e}")
            return {"success": False, "error": str(e)}
    
    async def process_voice_recording(
        self,
        user_id: str,
        audio_blob: bytes,
        mime_type: str,
        client_duration: Optional[int] = None,
        client_waveform: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """Process a voice recording from the client"""
        try:
            # Analyze audio to get accurate duration and waveform
            audio_info = await self._analyze_audio(audio_blob, mime_type)
            
            if not audio_info["success"]:
                return audio_info
            
            # Use server-calculated duration if available, otherwise use client-provided
            duration_seconds = audio_info["data"]["duration"] or client_duration or 0
            
            # Generate waveform if not provided by client
            waveform_data = client_waveform
            if not waveform_data:
                waveform_data = await self._generate_waveform(audio_blob, mime_type)
            
            # Upload the processed voice message
            upload_result = await self.upload_voice_message(
                user_id=user_id,
                audio_data=audio_blob,
                mime_type=mime_type,
                duration_seconds=int(duration_seconds),
                waveform_data=waveform_data
            )
            
            return upload_result
            
        except Exception as e:
            logger.error(f"Error processing voice recording: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_voice_message_playback_info(
        self,
        message_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """Get playback information for a voice message"""
        try:
            # Get voice message details
            result = self.supabase.table('messages') \
                .select('''
                    id, attachment_url, voice_duration_seconds, voice_waveform,
                    attachment_size, attachment_mime_type,
                    conversation_id,
                    conversation:conversations!inner(
                        id,
                        participants:conversation_participants!inner(user_id)
                    )
                ''') \
                .eq('id', message_id) \
                .eq('message_type', 'voice') \
                .single() \
                .execute()
            
            if not result.data:
                return {"success": False, "error": "Voice message not found"}
            
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
                    "audio_url": message['attachment_url'],
                    "duration_seconds": message['voice_duration_seconds'],
                    "waveform": json.loads(message['voice_waveform']) if message['voice_waveform'] else [],
                    "file_size": message['attachment_size'],
                    "mime_type": message['attachment_mime_type']
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting voice message playback info: {e}")
            return {"success": False, "error": str(e)}
    
    async def delete_voice_message(
        self,
        message_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """Delete a voice message and its audio file"""
        try:
            # Get message details and verify ownership
            result = self.supabase.table('messages') \
                .select('id, attachment_url, sender_id') \
                .eq('id', message_id) \
                .eq('message_type', 'voice') \
                .eq('sender_id', user_id) \
                .single() \
                .execute()
            
            if not result.data:
                return {"success": False, "error": "Voice message not found or unauthorized"}
            
            message = result.data
            attachment_url = message['attachment_url']
            
            # Extract file path from URL for storage deletion
            if attachment_url:
                # Parse file path from storage URL
                file_path = self._extract_file_path_from_url(attachment_url)
                
                if file_path:
                    # Delete from storage
                    delete_result = self.supabase.storage \
                        .from_(self.storage_bucket) \
                        .remove([file_path])
                    
                    if delete_result.get('error'):
                        logger.warning(f"Failed to delete audio file: {delete_result['error']}")
            
            # Soft delete the message (handled by messages service)
            # This just confirms the voice message specific cleanup is done
            return {"success": True}
            
        except Exception as e:
            logger.error(f"Error deleting voice message: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_user_voice_message_stats(self, user_id: str) -> Dict[str, Any]:
        """Get user's voice message statistics"""
        try:
            # Get voice message count and total duration
            result = self.supabase.table('messages') \
                .select('voice_duration_seconds, attachment_size') \
                .eq('sender_id', user_id) \
                .eq('message_type', 'voice') \
                .eq('is_deleted', False) \
                .execute()
            
            messages = result.data or []
            
            total_count = len(messages)
            total_duration_seconds = sum(
                msg['voice_duration_seconds'] or 0 for msg in messages
            )
            total_size_bytes = sum(
                msg['attachment_size'] or 0 for msg in messages
            )
            
            # Convert to human-readable formats
            total_duration_minutes = total_duration_seconds / 60
            total_size_mb = total_size_bytes / (1024 * 1024)
            
            return {
                "success": True,
                "data": {
                    "total_voice_messages": total_count,
                    "total_duration_seconds": total_duration_seconds,
                    "total_duration_minutes": round(total_duration_minutes, 1),
                    "total_size_bytes": total_size_bytes,
                    "total_size_mb": round(total_size_mb, 2),
                    "average_duration_seconds": round(total_duration_seconds / total_count, 1) if total_count > 0 else 0
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting voice message stats: {e}")
            return {"success": False, "error": str(e)}
    
    # WAVEFORM GENERATION
    
    async def _generate_waveform(
        self,
        audio_data: bytes,
        mime_type: str,
        samples: int = 100
    ) -> List[float]:
        """Generate waveform visualization data from audio"""
        try:
            # For now, generate a simple mock waveform
            # In production, you'd use audio processing libraries like:
            # - librosa for Python
            # - Web Audio API processing on client-side
            # - FFmpeg for server-side processing
            
            import random
            
            # Generate realistic waveform pattern
            waveform = []
            for i in range(samples):
                # Create a more natural waveform pattern
                base_amplitude = 0.3 + 0.4 * random.random()
                
                # Add some variation based on position (quieter at start/end)
                position_factor = 1.0
                if i < samples * 0.1:  # First 10%
                    position_factor = i / (samples * 0.1)
                elif i > samples * 0.9:  # Last 10%
                    position_factor = (samples - i) / (samples * 0.1)
                
                amplitude = base_amplitude * position_factor
                waveform.append(round(amplitude, 3))
            
            return waveform
            
        except Exception as e:
            logger.error(f"Error generating waveform: {e}")
            # Return a flat waveform as fallback
            return [0.5] * samples
    
    async def _analyze_audio(
        self,
        audio_data: bytes,
        mime_type: str
    ) -> Dict[str, Any]:
        """Analyze audio file to get duration and properties"""
        try:
            # Basic validation
            if not audio_data:
                return {"success": False, "error": "No audio data provided"}
            
            if len(audio_data) > 50 * 1024 * 1024:  # 50MB limit
                return {"success": False, "error": "Audio file too large"}
            
            # For now, return basic info
            # In production, you'd use audio libraries to get actual duration
            estimated_duration = min(len(audio_data) / 16000, self.max_duration_seconds)  # Rough estimate
            
            return {
                "success": True,
                "data": {
                    "duration": estimated_duration,
                    "file_size": len(audio_data),
                    "mime_type": mime_type,
                    "sample_rate": None,  # Would be detected by audio library
                    "channels": None      # Would be detected by audio library
                }
            }
            
        except Exception as e:
            logger.error(f"Error analyzing audio: {e}")
            return {"success": False, "error": str(e)}
    
    # HELPER METHODS
    
    def _get_file_extension(self, mime_type: str) -> str:
        """Get file extension from MIME type"""
        extensions = {
            'audio/webm': '.webm',
            'audio/mp4': '.m4a',
            'audio/wav': '.wav',
            'audio/ogg': '.ogg',
            'audio/mpeg': '.mp3'
        }
        return extensions.get(mime_type, '.wav')
    
    def _extract_file_path_from_url(self, url: str) -> Optional[str]:
        """Extract storage file path from public URL"""
        try:
            # Parse the storage URL to get the file path
            # This depends on your Supabase storage URL structure
            if '/voice-messages/' in url:
                return url.split('/voice-messages/')[-1].split('?')[0]
            return None
        except Exception as e:
            logger.error(f"Error extracting file path: {e}")
            return None
    
    # ADVANCED FEATURES
    
    async def generate_voice_transcript(
        self,
        message_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """Generate transcript for a voice message (future feature)"""
        try:
            # This would integrate with speech-to-text services like:
            # - OpenAI Whisper
            # - Google Speech-to-Text
            # - AWS Transcribe
            
            # For now, return placeholder
            return {
                "success": True,
                "data": {
                    "transcript": "[Voice message transcript would appear here]",
                    "confidence": 0.95,
                    "language": "en",
                    "processing_time_ms": 1500
                }
            }
            
        except Exception as e:
            logger.error(f"Error generating transcript: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_voice_message_metrics(
        self,
        conversation_id: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Get voice message usage metrics"""
        try:
            query = self.supabase.table('messages') \
                .select('id, voice_duration_seconds, attachment_size, created_at') \
                .eq('message_type', 'voice') \
                .eq('is_deleted', False)
            
            if conversation_id:
                query = query.eq('conversation_id', conversation_id)
            
            if date_from:
                query = query.gte('created_at', date_from.isoformat())
            
            if date_to:
                query = query.lte('created_at', date_to.isoformat())
            
            result = query.execute()
            messages = result.data or []
            
            if not messages:
                return {
                    "success": True,
                    "data": {
                        "total_messages": 0,
                        "total_duration_seconds": 0,
                        "total_size_bytes": 0,
                        "average_duration": 0,
                        "peak_usage_hour": None
                    }
                }
            
            # Calculate metrics
            total_count = len(messages)
            total_duration = sum(msg['voice_duration_seconds'] or 0 for msg in messages)
            total_size = sum(msg['attachment_size'] or 0 for msg in messages)
            average_duration = total_duration / total_count if total_count > 0 else 0
            
            # Analyze peak usage times
            hour_counts = {}
            for msg in messages:
                if msg['created_at']:
                    hour = datetime.fromisoformat(msg['created_at'].replace('Z', '+00:00')).hour
                    hour_counts[hour] = hour_counts.get(hour, 0) + 1
            
            peak_hour = max(hour_counts.items(), key=lambda x: x[1])[0] if hour_counts else None
            
            return {
                "success": True,
                "data": {
                    "total_messages": total_count,
                    "total_duration_seconds": total_duration,
                    "total_size_bytes": total_size,
                    "average_duration": round(average_duration, 1),
                    "peak_usage_hour": peak_hour,
                    "hourly_distribution": hour_counts
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting voice message metrics: {e}")
            return {"success": False, "error": str(e)}