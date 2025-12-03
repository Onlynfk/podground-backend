"""
Messages Service
Core messaging functionality for conversations, messages, and real-time communication
"""
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timezone
from supabase import Client
import logging
from datetime_utils import format_datetime_central

logger = logging.getLogger(__name__)

class MessagesService:
    def __init__(self, supabase_client):
        self.supabase_client = supabase_client  # SupabaseClient wrapper
        self.supabase = supabase_client.service_client  # Raw Supabase client for queries

    def _clean_message_response(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Remove internal fields from message response and format datetimes"""
        if isinstance(message, dict):
            # Remove search_vector field if present
            message.pop('search_vector', None)
            # Remove podcast sharing fields if null
            if message.get('shared_podcast_id') is None:
                message.pop('shared_podcast_id', None)
            if message.get('shared_episode_id') is None:
                message.pop('shared_episode_id', None)
            # Format datetime fields to Central Time
            if 'created_at' in message:
                message['created_at'] = format_datetime_central(message['created_at'])
            if 'edited_at' in message:
                message['edited_at'] = format_datetime_central(message['edited_at'])
            if 'updated_at' in message:
                message['updated_at'] = format_datetime_central(message['updated_at'])
        return message

    def _clean_conversation_response(self, conversation: Dict[str, Any]) -> Dict[str, Any]:
        """Format datetime fields in conversation response"""
        if isinstance(conversation, dict):
            if 'created_at' in conversation:
                conversation['created_at'] = format_datetime_central(conversation['created_at'])
            if 'updated_at' in conversation:
                conversation['updated_at'] = format_datetime_central(conversation['updated_at'])
            # Format last_message datetime if present
            if 'last_message' in conversation and isinstance(conversation['last_message'], dict):
                if 'created_at' in conversation['last_message']:
                    conversation['last_message']['created_at'] = format_datetime_central(conversation['last_message']['created_at'])
        return conversation

    def _clean_messages_response(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Clean multiple messages by removing internal fields"""
        return [self._clean_message_response(msg) for msg in messages]

    # CONVERSATIONS MANAGEMENT
    
    async def get_user_conversations(
        self, 
        user_id: str, 
        limit: int = 20, 
        offset: int = 0,
        include_archived: bool = False
    ) -> List[Dict[str, Any]]:
        """Get user's conversations with latest message and participant info"""
        try:
            logger.info(f"Getting conversations for user {user_id} with limit {limit}, offset {offset}")
            
            # First, get conversation IDs that the user participates in
            participant_result = self.supabase.table('conversation_participants') \
                .select('conversation_id') \
                .eq('user_id', user_id) \
                .is_('left_at', 'null') \
                .execute()
            
            if not participant_result.data:
                logger.info(f"No conversation participants found for user {user_id}")
                return []
            
            conversation_ids = [p['conversation_id'] for p in participant_result.data]
            logger.info(f"User {user_id} participates in conversations: {conversation_ids}")
            
            # Now get the conversations with all related data
            result = self.supabase.table('conversations') \
                .select('''
                    *,
                    participants:conversation_participants!inner(
                        user_id, joined_at, left_at
                    ),
                    messages(id, content, message_type, created_at, sender_id, is_deleted, edited_at)
                ''') \
                .in_('id', conversation_ids) \
                .order('created_at', desc=True) \
                .range(offset, offset + limit - 1) \
                .execute()

            conversations = result.data
            logger.info(f"Raw conversations query returned {len(conversations) if conversations else 0} results")

            # Batch fetch all participant user IDs for display info
            other_user_ids = []
            for conversation in conversations:
                all_participants = conversation.get('participants', [])
                active_participants = [p for p in all_participants if p.get('left_at') is None]
                for participant in active_participants:
                    if participant['user_id'] != user_id:
                        other_user_ids.append(participant['user_id'])

            # Remove duplicates
            other_user_ids = list(set(other_user_ids))

            # Batch fetch user info from user_signup_tracking
            users_info_map = {}
            if other_user_ids:
                users_result = self.supabase.table('user_signup_tracking') \
                    .select('user_id, email, name') \
                    .in_('user_id', other_user_ids) \
                    .execute()

                for user_data in (users_result.data or []):
                    users_info_map[user_data['user_id']] = user_data

            # Batch fetch avatars from user_profiles
            avatars_map = {}
            if other_user_ids:
                profiles_result = self.supabase.table('user_profiles') \
                    .select('user_id, avatar_url') \
                    .in_('user_id', other_user_ids) \
                    .execute()

                for profile_data in (profiles_result.data or []):
                    if profile_data.get('avatar_url'):
                        avatars_map[profile_data['user_id']] = profile_data['avatar_url']

            # Generate signed URLs for all avatars
            signed_avatars_map = {}
            if avatars_map:
                try:
                    from user_profile_service import UserProfileService
                    profile_service = UserProfileService()
                    for uid, avatar_url in avatars_map.items():
                        signed_avatars_map[uid] = profile_service._generate_signed_avatar_url(avatar_url)
                except Exception as e:
                    logger.warning(f"Failed to generate signed avatar URLs: {e}")

            # Get current user's podcast_id once
            current_user_podcast_id = self.supabase_client.get_user_claimed_podcast_id(user_id)

            # Enhance conversations with additional info
            for conversation in conversations:
                conversation_id = conversation['id']

                # Calculate actual active participant count (excluding those who left)
                # Only count participants where left_at is NULL
                all_participants = conversation.get('participants', [])
                active_participants = [p for p in all_participants if p.get('left_at') is None]
                conversation['participant_count'] = len(active_participants)

                # Find the latest message from the joined messages
                messages = conversation.get('messages', [])
                latest_message = None
                if messages:
                    # Filter out deleted messages and sort by created_at to get the latest
                    non_deleted_messages = [m for m in messages if not m.get('is_deleted', False)]
                    if non_deleted_messages:
                        sorted_messages = sorted(non_deleted_messages, key=lambda m: m.get('created_at', ''), reverse=True)
                        latest_message = sorted_messages[0]
                        # Remove is_deleted field from the response
                        if latest_message:
                            latest_message.pop('is_deleted', None)
                            # Clean up message response
                            latest_message = self._clean_message_response(latest_message)

                conversation['last_message'] = latest_message

                # Build display_info from pre-fetched data
                display_info = {
                    'name': None,
                    'image_url': None,
                    'user_id': None
                }

                # Find other participant
                for participant in active_participants:
                    if participant['user_id'] != user_id:
                        other_user_id = participant['user_id']
                        display_info['user_id'] = other_user_id

                        # Get name from pre-fetched data
                        if other_user_id in users_info_map:
                            user_data = users_info_map[other_user_id]
                            user_name = user_data.get('name', '')
                            user_email = user_data.get('email', '')
                            display_info['name'] = user_name or (user_email.split('@')[0] if user_email else 'Unknown User')
                        else:
                            display_info['name'] = 'Unknown User'

                        # Get avatar from pre-fetched data
                        if other_user_id in signed_avatars_map:
                            display_info['image_url'] = signed_avatars_map[other_user_id]

                        break

                conversation['display_info'] = display_info

                # Add current user's podcast_id (already fetched once)
                conversation['current_user_podcast_id'] = current_user_podcast_id

                # Remove the full messages array to avoid bloating the response
                conversation.pop('messages', None)

                # Remove the participants field entirely
                conversation.pop('participants', None)

                # Remove fields as requested
                conversation.pop('podcast_id', None)
                conversation.pop('episode_id', None)
                conversation.pop('settings', None)
                conversation.pop('user_settings', None)
                conversation.pop('title', None)
                conversation.pop('last_message_at', None)
                conversation.pop('last_message_id', None)

                # Format datetime fields
                self._clean_conversation_response(conversation)

            return conversations
            
        except Exception as e:
            logger.error(f"Error getting user conversations: {e}")
            return []
    
    async def create_conversation(
        self,
        creator_id: str,
        participant_ids: List[str]
    ) -> Dict[str, Any]:
        """Create a new direct conversation between two users"""
        try:
            # Only support direct messages between 2 users
            if len(participant_ids) != 1:
                return {"success": False, "error": "Direct messages must be between exactly 2 users"}

            recipient_id = participant_ids[0]

            # Validate both users are platform ready (completed onboarding + verified podcast claim)
            from supabase_client import get_supabase_client
            supabase_client = get_supabase_client()

            # Check creator
            creator_ready = supabase_client.is_user_platform_ready(creator_id)
            if not creator_ready.get("success") or not creator_ready.get("is_ready"):
                reason = creator_ready.get("reason", "unknown")
                return {
                    "success": False,
                    "error": "You must complete onboarding and verify your podcast claim before messaging other users"
                }

            # Check recipient
            recipient_ready = supabase_client.is_user_platform_ready(recipient_id)
            if not recipient_ready.get("success") or not recipient_ready.get("is_ready"):
                reason = recipient_ready.get("reason", "unknown")
                return {
                    "success": False,
                    "error": "This user hasn't completed their profile setup yet and cannot receive messages"
                }

            # Check if conversation already exists
            existing = await self._find_direct_conversation(creator_id, recipient_id)
            if existing:
                # Remove unwanted fields from existing conversation
                existing.pop('podcast_id', None)
                existing.pop('episode_id', None)
                existing.pop('settings', None)
                existing.pop('user_settings', None)
                existing.pop('title', None)
                existing.pop('last_message_at', None)
                existing.pop('last_message_id', None)
                return {"success": True, "data": existing, "existing": True}
            
            # Create direct conversation
            conversation_data = {
                'conversation_type': 'direct',
                'participant_count': 2,  # Always 2 for direct messages
                'last_message_at': 'now()'  # Set to creation time so it appears in queries
            }
            
            conversation_result = self.supabase.table('conversations') \
                .insert(conversation_data) \
                .execute()
            
            if not conversation_result.data:
                return {"success": False, "error": "Failed to create conversation"}
            
            conversation = conversation_result.data[0]
            conversation_id = conversation['id']
            
            # Add both participants
            participants_data = [
                {
                    'conversation_id': conversation_id,
                    'user_id': creator_id,
                    'is_admin': False  # No admins in direct messages
                },
                {
                    'conversation_id': conversation_id,
                    'user_id': recipient_id,
                    'is_admin': False
                }
            ]

            participants_result = self.supabase.table('conversation_participants') \
                .insert(participants_data) \
                .execute()

            if participants_result.data:
                logger.info(f"Created direct conversation {conversation_id} between {creator_id} and {recipient_id}")
                
                # Remove unwanted fields before returning
                conversation.pop('podcast_id', None)
                conversation.pop('episode_id', None)
                conversation.pop('settings', None)
                conversation.pop('user_settings', None)
                conversation.pop('title', None)
                conversation.pop('last_message_at', None)
                conversation.pop('last_message_id', None)
                
                return {
                    "success": True, 
                    "data": conversation,
                    "participants": participants_result.data,
                    "existing": False
                }
            else:
                return {"success": False, "error": "Failed to add participants"}
                
        except Exception as e:
            logger.error(f"Error creating conversation: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_conversation_details(
        self, 
        conversation_id: str, 
        user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get detailed conversation information"""
        try:
            # Verify user has access to conversation
            access_check = self.supabase.table('conversation_participants') \
                .select('id') \
                .eq('conversation_id', conversation_id) \
                .eq('user_id', user_id) \
                .is_('left_at', 'null') \
                .execute()
            
            if not access_check.data:
                return None
            
            # Get conversation with related data
            result = self.supabase.table('conversations') \
                .select('''
                    *,
                    participants:conversation_participants(
                        user_id, joined_at, is_admin
                    )
                ''') \
                .eq('id', conversation_id) \
                .single() \
                .execute()
            
            if result.data:
                conversation = result.data
                
                # Remove left_at from participants
                for participant in conversation.get('participants', []):
                    participant.pop('left_at', None)
                
                # Remove fields as requested
                conversation.pop('podcast_id', None)
                conversation.pop('episode_id', None)
                conversation.pop('settings', None)
                conversation.pop('user_settings', None)
                conversation.pop('title', None)
                conversation.pop('last_message_at', None)
                conversation.pop('last_message_id', None)
                
                return conversation
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting conversation details: {e}")
            return None
    
    async def get_messageable_users(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get list of users that current user can message"""
        try:
            # Get users from user_signup_tracking which has email and name info
            result = self.supabase.table('user_signup_tracking') \
                .select('user_id, email, name') \
                .neq('user_id', user_id) \
                .eq('signup_confirmed', True) \
                .range(offset, offset + limit - 1) \
                .execute()

            if not result.data:
                return []

            # Batch fetch all existing conversations for current user
            user_conversations_result = self.supabase.table('conversation_participants') \
                .select('conversation_id') \
                .eq('user_id', user_id) \
                .is_('left_at', 'null') \
                .execute()

            user_conversation_ids = [c['conversation_id'] for c in (user_conversations_result.data or [])]

            # Build a map of other_user_id -> conversation_id for quick lookup
            conversations_map = {}
            if user_conversation_ids:
                # Get all participants for these conversations
                all_participants = self.supabase.table('conversation_participants') \
                    .select('conversation_id, user_id') \
                    .in_('conversation_id', user_conversation_ids) \
                    .is_('left_at', 'null') \
                    .execute()

                # Group participants by conversation_id
                conv_participants = {}
                for participant in (all_participants.data or []):
                    conv_id = participant['conversation_id']
                    if conv_id not in conv_participants:
                        conv_participants[conv_id] = []
                    conv_participants[conv_id].append(participant['user_id'])

                # Build map of other_user_id -> conversation_id
                for conv_id, participant_ids in conv_participants.items():
                    # Only for direct conversations (2 participants)
                    if len(participant_ids) == 2 and user_id in participant_ids:
                        other_user_id = [uid for uid in participant_ids if uid != user_id][0]
                        conversations_map[other_user_id] = conv_id

            # Batch fetch user profiles (already returns signed avatar URLs)
            user_ids = [signup_user['user_id'] for signup_user in result.data]
            from user_profile_service import UserProfileService
            profile_service = UserProfileService()
            user_profiles = await profile_service.get_users_by_ids(user_ids)
            profiles_map = {u['id']: u for u in user_profiles}

            users = []
            for signup_user in result.data:
                user_uuid = signup_user['user_id']
                email = signup_user.get('email', '')
                name = signup_user.get('name', '')

                # Check if conversation exists using pre-fetched map
                conversation_id = conversations_map.get(user_uuid)

                # Get user profile data (includes pre-signed avatar URL)
                profile = profiles_map.get(user_uuid, {})

                # Parse name into first/last name
                name_parts = name.split(' ', 1) if name else []
                first_name = name_parts[0] if name_parts else ''
                last_name = name_parts[1] if len(name_parts) > 1 else ''

                # Format user info
                user_info = {
                    'user_id': user_uuid,
                    'email': email,
                    'first_name': first_name,
                    'last_name': last_name,
                    'display_name': profile.get('name') or name or email.split('@')[0] if email else 'Unknown User',
                    'avatar_url': profile.get('avatar_url') or '',
                    'bio': profile.get('bio') or '',
                    'has_conversation': conversation_id is not None,
                    'conversation_id': conversation_id
                }

                users.append(user_info)

            return users

        except Exception as e:
            logger.error(f"Error getting messageable users: {e}")
            return []
    
    async def delete_conversation(
        self,
        conversation_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """Delete a conversation for a user (removes them as participant)"""
        try:
            # First verify the user is a participant in the conversation
            access_check = self.supabase.table('conversation_participants') \
                .select('id') \
                .eq('conversation_id', conversation_id) \
                .eq('user_id', user_id) \
                .is_('left_at', 'null') \
                .execute()
            
            if not access_check.data:
                return {"success": False, "error": "User not in conversation"}
            
            # For direct messages, we'll mark the user as having left the conversation
            # This preserves the conversation for the other user
            result = self.supabase.table('conversation_participants') \
                .update({
                    'left_at': datetime.now(timezone.utc).isoformat()
                }) \
                .eq('conversation_id', conversation_id) \
                .eq('user_id', user_id) \
                .execute()
            
            if result.data:
                logger.info(f"User {user_id} left conversation {conversation_id}")
                
                # Check if this leaves the conversation empty (all participants have left)
                remaining_participants = self.supabase.table('conversation_participants') \
                    .select('id') \
                    .eq('conversation_id', conversation_id) \
                    .is_('left_at', 'null') \
                    .execute()
                
                if not remaining_participants.data:
                    # Mark conversation as inactive if no participants remain
                    self.supabase.table('conversations') \
                        .update({'is_active': False}) \
                        .eq('id', conversation_id) \
                        .execute()
                    logger.info(f"Conversation {conversation_id} marked as inactive (no participants)")
                
                return {"success": True, "message": "Successfully left conversation"}
            else:
                return {"success": False, "error": "Failed to leave conversation"}
                
        except Exception as e:
            logger.error(f"Error deleting conversation: {e}")
            return {"success": False, "error": str(e)}
    
    # MESSAGES MANAGEMENT
    
    async def get_conversation_messages(
        self,
        conversation_id: str,
        user_id: str,
        limit: int = 50,
        before_message_id: Optional[str] = None,
        after_message_id: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """Get messages for a conversation with pagination and media attachments"""
        try:
            # Verify user has access
            access_check = self.supabase.table('conversation_participants') \
                .select('id') \
                .eq('conversation_id', conversation_id) \
                .eq('user_id', user_id) \
                .is_('left_at', 'null') \
                .execute()

            if not access_check.data:
                return [], False

            # Build message query
            query = self.supabase.table('messages') \
                .select('''
                    *,
                    delivery_status:message_delivery_status(
                        user_id, delivered_at, read_at
                    )
                ''') \
                .eq('conversation_id', conversation_id) \
                .eq('is_deleted', False)

            # Apply pagination
            if before_message_id:
                # Get messages before a specific message (older messages)
                before_message = self.supabase.table('messages') \
                    .select('created_at') \
                    .eq('id', before_message_id) \
                    .single() \
                    .execute()

                if before_message.data:
                    query = query.lt('created_at', before_message.data['created_at'])

            elif after_message_id:
                # Get messages after a specific message (newer messages)
                after_message = self.supabase.table('messages') \
                    .select('created_at') \
                    .eq('id', after_message_id) \
                    .single() \
                    .execute()

                if after_message.data:
                    query = query.gt('created_at', after_message.data['created_at'])

            result = query \
                .order('created_at', desc=True) \
                .limit(limit + 1) \
                .execute()

            messages = result.data or []
            has_more = len(messages) > limit

            if has_more:
                messages = messages[:limit]

            # Reverse to show oldest first
            messages.reverse()

            # Attach media to each message
            messages = await self._attach_media_to_messages(messages, user_id)

            # Attach reactions to each message
            messages = await self._attach_reactions_to_messages(messages, user_id)

            # Clean up message responses
            messages = self._clean_messages_response(messages)

            return messages, has_more

        except Exception as e:
            logger.error(f"Error getting conversation messages: {e}")
            return [], False
    
    async def send_message(
        self,
        conversation_id: str,
        sender_id: str,
        content: Optional[str] = None,
        message_type: str = 'text',
        attachment_data: Optional[Dict[str, Any]] = None,
        voice_data: Optional[Dict[str, Any]] = None,
        podcast_share_data: Optional[Dict[str, Any]] = None,
        reply_to_message_id: Optional[str] = None,
        media_files: Optional[List] = None  # New parameter for multiple media files
    ) -> Dict[str, Any]:
        """Send a message in a conversation with optional multiple media attachments"""
        try:
            # Verify user is participant
            access_check = self.supabase.table('conversation_participants') \
                .select('id') \
                .eq('conversation_id', conversation_id) \
                .eq('user_id', sender_id) \
                .is_('left_at', 'null') \
                .execute()

            if not access_check.data:
                return {"success": False, "error": "User not in conversation"}

            # Validate that message has either content or media
            has_content = content and content.strip()
            has_media = media_files and len(media_files) > 0
            has_legacy_attachment = attachment_data is not None
            has_voice = voice_data is not None
            has_podcast_share = podcast_share_data is not None

            if not (has_content or has_media or has_legacy_attachment or has_voice or has_podcast_share):
                return {"success": False, "error": "Message must have content, media, or other attachment"}

            # Prepare message data
            message_data = {
                'conversation_id': conversation_id,
                'sender_id': sender_id,
                'content': content,
                'message_type': message_type,
                'reply_to_message_id': reply_to_message_id
            }

            # Add attachment data if provided (legacy single attachment support)
            if attachment_data:
                message_data.update({
                    'attachment_url': attachment_data.get('url'),
                    'attachment_type': attachment_data.get('type'),
                    'attachment_filename': attachment_data.get('filename'),
                    'attachment_size': attachment_data.get('size'),
                    'attachment_mime_type': attachment_data.get('mime_type')
                })

            # Add voice message data if provided
            if voice_data:
                message_data.update({
                    'voice_duration_seconds': voice_data.get('duration_seconds'),
                    'voice_waveform': voice_data.get('waveform'),
                    'attachment_url': voice_data.get('audio_url')  # Voice file URL
                })

            # Add podcast sharing data if provided
            if podcast_share_data:
                message_data.update({
                    'shared_podcast_id': podcast_share_data.get('podcast_id'),
                    'shared_episode_id': podcast_share_data.get('episode_id')
                })

            # Insert message
            result = self.supabase.table('messages') \
                .insert(message_data) \
                .execute()

            if result.data:
                message = result.data[0]
                message_id = message['id']

                # Upload media files if provided
                uploaded_media = []
                if media_files and len(media_files) > 0:
                    from message_media_service import get_message_media_service
                    media_service = get_message_media_service()

                    try:
                        uploaded_media = await media_service.upload_message_media(
                            user_id=sender_id,
                            message_id=message_id,
                            conversation_id=conversation_id,
                            files=media_files
                        )
                        logger.info(f"Uploaded {len(uploaded_media)} media files for message {message_id}")
                    except Exception as e:
                        logger.error(f"Failed to upload media for message {message_id}: {str(e)}")
                        # Continue even if media upload fails, message was created

                # Create delivery status entries for all participants (except sender)
                await self._create_delivery_status_entries(conversation_id, message_id, sender_id)

                # Update user's last read timestamp
                await self._update_user_last_read(conversation_id, sender_id, message_id)

                logger.info(f"Message {message_id} sent in conversation {conversation_id}")

                # Clean up message response
                cleaned_message = self._clean_message_response(message)

                # Add media info to response if uploaded
                if uploaded_media:
                    cleaned_message['media'] = uploaded_media
                else:
                    cleaned_message['media'] = []

                # Add empty reactions for new message
                cleaned_message['reactions'] = {}

                return {"success": True, "data": cleaned_message}
            else:
                return {"success": False, "error": "Failed to send message"}

        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return {"success": False, "error": str(e)}
    
    
    async def edit_message(
        self,
        message_id: str,
        user_id: str,
        new_content: str
    ) -> Dict[str, Any]:
        """Edit a message's content"""
        try:
            # Validate that content is provided and not empty
            if not new_content or new_content.strip() == '':
                return {"success": False, "error": "Content cannot be empty"}
            
            # Update the message content and set edited timestamp
            result = self.supabase.table('messages') \
                .update({
                    'content': new_content.strip(),
                    'edited_at': datetime.now(timezone.utc).isoformat()
                }) \
                .eq('id', message_id) \
                .eq('sender_id', user_id) \
                .eq('is_deleted', False) \
                .execute()
            
            if result.data:
                # Clean up message response
                cleaned_message = self._clean_message_response(result.data[0])
                return {"success": True, "data": cleaned_message}
            else:
                return {"success": False, "error": "Message not found, unauthorized, or already deleted"}
                
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            return {"success": False, "error": str(e)}
    
    async def delete_message(
        self,
        message_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """Delete a message (soft delete)"""
        try:
            result = self.supabase.table('messages') \
                .update({
                    'is_deleted': True,
                    'deleted_at': datetime.now(timezone.utc).isoformat(),
                    'content': None  # Clear content for privacy
                }) \
                .eq('id', message_id) \
                .eq('sender_id', user_id) \
                .execute()
            
            if result.data:
                return {"success": True}
            else:
                return {"success": False, "error": "Message not found or unauthorized"}
                
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
            return {"success": False, "error": str(e)}
    
    
    # USER PRESENCE
    
    async def update_user_online_status(
        self,
        user_id: str,
        is_online: bool,
        device_type: Optional[str] = None,
        user_agent: Optional[str] = None,
        status_message: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update user's online status"""
        try:
            status_data = {
                'user_id': user_id,
                'is_online': is_online,
                'last_seen_at': datetime.now(timezone.utc).isoformat(),
                'device_type': device_type,
                'user_agent': user_agent,
                'status_message': status_message
            }
            
            result = self.supabase.table('user_online_status') \
                .upsert(status_data, on_conflict='user_id') \
                .execute()
            
            if result.data:
                return {"success": True, "data": result.data[0]}
            else:
                return {"success": False, "error": "Failed to update status"}
                
        except Exception as e:
            logger.error(f"Error updating online status: {e}")
            return {"success": False, "error": str(e)}
    
    async def mark_messages_as_read(
        self,
        conversation_id: str,
        user_id: str,
        up_to_message_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Mark messages as read up to a specific message"""
        try:
            # Update conversation participant's last read info
            update_data = {
                'last_read_at': datetime.now(timezone.utc).isoformat()
            }
            
            if up_to_message_id:
                update_data['last_read_message_id'] = up_to_message_id
            
            result = self.supabase.table('conversation_participants') \
                .update(update_data) \
                .eq('conversation_id', conversation_id) \
                .eq('user_id', user_id) \
                .execute()
            
            # Update delivery status for messages
            if up_to_message_id:
                # Get the timestamp of the message being marked as read
                message_result = self.supabase.table('messages') \
                    .select('created_at') \
                    .eq('id', up_to_message_id) \
                    .single() \
                    .execute()
                
                if message_result.data:
                    # Mark all messages up to this timestamp as read
                    self.supabase.table('message_delivery_status') \
                        .update({'read_at': datetime.now(timezone.utc).isoformat()}) \
                        .eq('user_id', user_id) \
                        .is_('read_at', 'null') \
                        .execute()
            
            return {"success": True}
            
        except Exception as e:
            logger.error(f"Error marking messages as read: {e}")
            return {"success": False, "error": str(e)}
    
    async def mark_message_as_read(
        self,
        message_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """Mark a specific message as read by user"""
        try:
            # Verify user has access to this message's conversation
            message_result = self.supabase.table('messages') \
                .select('conversation_id') \
                .eq('id', message_id) \
                .single() \
                .execute()
            
            if not message_result.data:
                return {"success": False, "error": "Message not found"}
            
            conversation_id = message_result.data['conversation_id']
            
            # Verify user is participant in conversation
            access_check = self.supabase.table('conversation_participants') \
                .select('id') \
                .eq('conversation_id', conversation_id) \
                .eq('user_id', user_id) \
                .is_('left_at', 'null') \
                .execute()
            
            if not access_check.data:
                return {"success": False, "error": "User not in conversation"}
            
            # Update or insert delivery status
            now = datetime.now(timezone.utc).isoformat()
            
            # Try to update existing delivery status record
            update_result = self.supabase.table('message_delivery_status') \
                .update({'read_at': now}) \
                .eq('message_id', message_id) \
                .eq('user_id', user_id) \
                .is_('read_at', 'null') \
                .execute()
            
            # If no existing record was updated, create a new one
            if not update_result.data:
                self.supabase.table('message_delivery_status') \
                    .upsert({
                        'message_id': message_id,
                        'user_id': user_id,
                        'delivered_at': now,
                        'read_at': now
                    }, on_conflict='message_id,user_id') \
                    .execute()
            
            # Update conversation participant's last read info
            self.supabase.table('conversation_participants') \
                .update({
                    'last_read_at': now,
                    'last_read_message_id': message_id
                }) \
                .eq('conversation_id', conversation_id) \
                .eq('user_id', user_id) \
                .execute()
            
            logger.info(f"User {user_id} marked message {message_id} as read")
            return {"success": True}
            
        except Exception as e:
            logger.error(f"Error marking message as read: {e}")
            return {"success": False, "error": str(e)}
    
    async def mark_messages_as_read_up_to(
        self,
        conversation_id: str,
        user_id: str,
        up_to_message_id: str
    ) -> Dict[str, Any]:
        """Mark all messages up to a specific message as read"""
        try:
            # Verify user is participant in conversation
            access_check = self.supabase.table('conversation_participants') \
                .select('id') \
                .eq('conversation_id', conversation_id) \
                .eq('user_id', user_id) \
                .is_('left_at', 'null') \
                .execute()
            
            if not access_check.data:
                return {"success": False, "error": "User not in conversation"}
            
            # Get the timestamp of the message being marked as read
            message_result = self.supabase.table('messages') \
                .select('created_at') \
                .eq('id', up_to_message_id) \
                .eq('conversation_id', conversation_id) \
                .single() \
                .execute()
            
            if not message_result.data:
                return {"success": False, "error": "Message not found in conversation"}
            
            message_timestamp = message_result.data['created_at']
            now = datetime.now(timezone.utc).isoformat()
            
            # Get all messages up to the specified timestamp that user hasn't read
            messages_to_mark = self.supabase.table('messages') \
                .select('id') \
                .eq('conversation_id', conversation_id) \
                .lte('created_at', message_timestamp) \
                .eq('is_deleted', False) \
                .execute()
            
            if messages_to_mark.data:
                message_ids = [msg['id'] for msg in messages_to_mark.data]
                
                # Update existing delivery status records
                self.supabase.table('message_delivery_status') \
                    .update({'read_at': now}) \
                    .eq('user_id', user_id) \
                    .in_('message_id', message_ids) \
                    .is_('read_at', 'null') \
                    .execute()
                
                # Create delivery status records for messages that don't have them
                for message_id in message_ids:
                    self.supabase.table('message_delivery_status') \
                        .upsert({
                            'message_id': message_id,
                            'user_id': user_id,
                            'delivered_at': now,
                            'read_at': now
                        }, on_conflict='message_id,user_id') \
                        .execute()
            
            # Update conversation participant's last read info
            self.supabase.table('conversation_participants') \
                .update({
                    'last_read_at': now,
                    'last_read_message_id': up_to_message_id
                }) \
                .eq('conversation_id', conversation_id) \
                .eq('user_id', user_id) \
                .execute()
            
            logger.info(f"User {user_id} marked messages up to {up_to_message_id} as read in conversation {conversation_id}")
            return {"success": True, "messages_marked": len(messages_to_mark.data) if messages_to_mark.data else 0}
            
        except Exception as e:
            logger.error(f"Error marking messages as read up to: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_message_read_receipts(
        self,
        message_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """Get read receipts for a specific message"""
        try:
            # Verify user has access to this message's conversation
            message_result = self.supabase.table('messages') \
                .select('conversation_id, sender_id') \
                .eq('id', message_id) \
                .single() \
                .execute()
            
            if not message_result.data:
                return {"success": False, "error": "Message not found"}
            
            conversation_id = message_result.data['conversation_id']
            
            # Verify user is participant in conversation
            access_check = self.supabase.table('conversation_participants') \
                .select('id') \
                .eq('conversation_id', conversation_id) \
                .eq('user_id', user_id) \
                .is_('left_at', 'null') \
                .execute()
            
            if not access_check.data:
                return {"success": False, "error": "User not in conversation"}
            
            # Get all participants in the conversation
            participants_result = self.supabase.table('conversation_participants') \
                .select('user_id') \
                .eq('conversation_id', conversation_id) \
                .is_('left_at', 'null') \
                .execute()
            
            total_participants = len(participants_result.data) if participants_result.data else 0
            
            # Get read receipts for the message
            receipts_result = self.supabase.table('message_delivery_status') \
                .select('user_id, read_at') \
                .eq('message_id', message_id) \
                .not_.is_('read_at', 'null') \
                .execute()
            
            read_by = []
            if receipts_result.data:
                # Get user names for the receipts
                user_ids = [receipt['user_id'] for receipt in receipts_result.data]
                
                if user_ids:
                    users_result = self.supabase.table('user_signup_tracking') \
                        .select('user_id, name, email') \
                        .in_('user_id', user_ids) \
                        .execute()
                    
                    user_names = {}
                    if users_result.data:
                        for user in users_result.data:
                            user_names[user['user_id']] = user.get('name') or user.get('email', 'Unknown User')
                    
                    # Build read_by list
                    for receipt in receipts_result.data:
                        read_by.append({
                            'user_id': receipt['user_id'],
                            'user_name': user_names.get(receipt['user_id'], 'Unknown User'),
                            'read_at': receipt['read_at']
                        })
            
            return {
                "success": True,
                "data": {
                    "message_id": message_id,
                    "read_by": read_by,
                    "total_participants": total_participants,
                    "read_count": len(read_by)
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting message read receipts: {e}")
            return {"success": False, "error": str(e)}
    
    # MESSAGE REACTIONS
    
    async def toggle_message_reaction(
        self,
        message_id: str,
        user_id: str,
        reaction_type: str
    ) -> Dict[str, Any]:
        """Add, update or remove a reaction from a message"""
        try:
            # Verify user has access to this message's conversation
            message_result = self.supabase.table('messages') \
                .select('conversation_id') \
                .eq('id', message_id) \
                .execute()

            if not message_result.data or len(message_result.data) == 0:
                return {"success": False, "error": "Message not found"}

            conversation_id = message_result.data[0]['conversation_id']
            
            # Verify user is participant in conversation
            access_check = self.supabase.table('conversation_participants') \
                .select('id') \
                .eq('conversation_id', conversation_id) \
                .eq('user_id', user_id) \
                .is_('left_at', 'null') \
                .execute()
            
            if not access_check.data:
                return {"success": False, "error": "User not in conversation"}
            
            # If reaction_type is empty, remove the reaction
            if not reaction_type or reaction_type.strip() == '':
                # Remove reaction
                result = self.supabase.table('message_reactions') \
                    .delete() \
                    .eq('message_id', message_id) \
                    .eq('user_id', user_id) \
                    .execute()
                
                logger.info(f"User {user_id} removed reaction from message {message_id}")
                return {"success": True, "action": "removed"}
            
            # Validate reaction type (allow common emojis and reaction names)
            allowed_reactions = {
                '👍', '👎', '❤️', '😂', '😢', '😡', '😮', '🔥', '💯', '🎉',
                '😍', '🤔', '👏', '😅', '😊', '🙏', '💪', '👌', '🤝', '✨',
                'like', 'love', 'laugh', 'sad', 'angry', 'wow', 'fire', 'hundred', 'party'
            }
            
            if reaction_type not in allowed_reactions:
                return {"success": False, "error": f"Invalid reaction type. Allowed: {', '.join(sorted(allowed_reactions))}"}
            
            # Check if reaction already exists
            existing_reaction = self.supabase.table('message_reactions') \
                .select('id') \
                .eq('message_id', message_id) \
                .eq('user_id', user_id) \
                .execute()

            if existing_reaction.data and len(existing_reaction.data) > 0:
                # Update existing reaction
                result = self.supabase.table('message_reactions') \
                    .update({'reaction_type': reaction_type}) \
                    .eq('message_id', message_id) \
                    .eq('user_id', user_id) \
                    .execute()
            else:
                # Insert new reaction
                result = self.supabase.table('message_reactions') \
                    .insert({
                        'message_id': message_id,
                        'user_id': user_id,
                        'reaction_type': reaction_type
                    }) \
                    .execute()

            if result.data:
                logger.info(f"User {user_id} set reaction '{reaction_type}' on message {message_id}")
                return {"success": True, "reaction_type": reaction_type}
            else:
                return {"success": False, "error": "Failed to save reaction"}
                
        except Exception as e:
            logger.error(f"Error toggling message reaction: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_message_reactions(
        self,
        message_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """Get all reactions for a message"""
        try:
            # Verify user has access to this message's conversation
            message_result = self.supabase.table('messages') \
                .select('conversation_id') \
                .eq('id', message_id) \
                .execute()

            if not message_result.data or len(message_result.data) == 0:
                return {"success": False, "error": "Message not found"}

            message = message_result.data[0]
            conversation_id = message['conversation_id']
            
            # Verify user is participant in conversation
            access_check = self.supabase.table('conversation_participants') \
                .select('id') \
                .eq('conversation_id', conversation_id) \
                .eq('user_id', user_id) \
                .is_('left_at', 'null') \
                .execute()
            
            if not access_check.data:
                return {"success": False, "error": "User not in conversation"}
            
            # Get all reactions for the message
            reactions_result = self.supabase.table('message_reactions') \
                .select('user_id, reaction_type, created_at') \
                .eq('message_id', message_id) \
                .execute()
            
            # Process reactions into grouped format
            reactions_grouped = {}

            if reactions_result.data:
                for reaction in reactions_result.data:
                    reaction_type = reaction['reaction_type']
                    reactor_id = reaction['user_id']

                    if reaction_type not in reactions_grouped:
                        reactions_grouped[reaction_type] = {
                            'count': 0,
                            'users': [],
                            'user_reacted': False
                        }

                    reactions_grouped[reaction_type]['count'] += 1
                    reactions_grouped[reaction_type]['users'].append(reactor_id)

                    if reactor_id == user_id:
                        reactions_grouped[reaction_type]['user_reacted'] = True

            return {
                "success": True,
                "data": {
                    "message_id": message_id,
                    "reactions": reactions_grouped
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting message reactions: {e}")
            return {"success": False, "error": str(e)}
    
    # SEARCH FUNCTIONALITY
    
    async def search_messages(
        self,
        user_id: str,
        query: str,
        conversation_id: Optional[str] = None,
        message_type: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Search messages across user's conversations"""
        try:
            # Filter by conversation if specified
            if conversation_id:
                # Single specific conversation - basic query without text search due to Supabase issues
                query_builder = self.supabase.table('messages')
                query_builder = query_builder.select('*')
                query_builder = query_builder.eq('conversation_id', conversation_id)
                query_builder = query_builder.eq('is_deleted', False)
                
                if message_type:
                    query_builder = query_builder.eq('message_type', message_type)
                
                query_builder = query_builder.order('created_at', desc=True)
                query_builder = query_builder.range(offset, offset + limit - 1)
                
                result = query_builder.execute()
                messages = result.data or []
                
                # Apply text search filtering in Python if query provided
                if query and messages:
                    # Get unique sender IDs from messages
                    sender_ids = list(set(msg['sender_id'] for msg in messages if msg.get('sender_id')))
                    
                    # Fetch sender names from signup tracking
                    sender_names = {}
                    if sender_ids:
                        senders_result = self.supabase.table('user_signup_tracking') \
                            .select('user_id, email, name') \
                            .in_('user_id', sender_ids) \
                            .execute()
                        
                        for sender in senders_result.data or []:
                            sender_names[sender['user_id']] = {
                                'name': sender.get('name', ''),
                                'email': sender.get('email', '')
                            }
                    
                    # Filter messages by content OR sender name
                    query_lower = query.lower()
                    filtered_messages = []
                    
                    for msg in messages:
                        # Check message content
                        content_match = msg.get('content') and query_lower in msg['content'].lower()
                        
                        # Check sender name/email
                        sender_match = False
                        if msg.get('sender_id') in sender_names:
                            sender_info = sender_names[msg['sender_id']]
                            sender_name = sender_info['name'].lower() if sender_info['name'] else ''
                            sender_email = sender_info['email'].lower() if sender_info['email'] else ''
                            sender_match = query_lower in sender_name or query_lower in sender_email
                        
                        # Include message if either matches
                        if content_match or sender_match:
                            # Add sender info to message for display
                            msg['sender_info'] = sender_names.get(msg['sender_id'], {'name': 'Unknown', 'email': ''})
                            filtered_messages.append(msg)
                    
                    messages = filtered_messages

                # Attach reactions to messages
                messages = await self._attach_reactions_to_messages(messages, user_id)

                total_count = len(messages)
                # Clean up message responses
                messages = self._clean_messages_response(messages)
                return messages, total_count
            else:
                # Only search in conversations user participates in
                user_conversations = self.supabase.table('conversation_participants') \
                    .select('conversation_id') \
                    .eq('user_id', user_id) \
                    .is_('left_at', 'null') \
                    .execute()
                
                if user_conversations.data:
                    conversation_ids = [c['conversation_id'] for c in user_conversations.data]
                    if len(conversation_ids) == 1:
                        # Simple case: only one conversation
                        single_builder = self.supabase.table('messages')
                        single_builder = single_builder.select('*')
                        single_builder = single_builder.eq('conversation_id', conversation_ids[0])
                        single_builder = single_builder.eq('is_deleted', False)
                        
                        if message_type:
                            single_builder = single_builder.eq('message_type', message_type)
                        
                        single_builder = single_builder.order('created_at', desc=True)
                        single_builder = single_builder.range(offset, offset + limit - 1)
                        
                        result = single_builder.execute()
                        messages = result.data or []
                        
                        # Apply text search filtering in Python if query provided
                        if query and messages:
                            # Get unique sender IDs from messages
                            sender_ids = list(set(msg['sender_id'] for msg in messages if msg.get('sender_id')))
                            
                            # Fetch sender names from signup tracking
                            sender_names = {}
                            if sender_ids:
                                senders_result = self.supabase.table('user_signup_tracking') \
                                    .select('user_id, email, name') \
                                    .in_('user_id', sender_ids) \
                                    .execute()
                                
                                for sender in senders_result.data or []:
                                    sender_names[sender['user_id']] = {
                                        'name': sender.get('name', ''),
                                        'email': sender.get('email', '')
                                    }
                            
                            # Filter messages by content OR sender name
                            query_lower = query.lower()
                            filtered_messages = []
                            
                            for msg in messages:
                                # Check message content
                                content_match = msg.get('content') and query_lower in msg['content'].lower()
                                
                                # Check sender name/email
                                sender_match = False
                                if msg.get('sender_id') in sender_names:
                                    sender_info = sender_names[msg['sender_id']]
                                    sender_name = sender_info['name'].lower() if sender_info['name'] else ''
                                    sender_email = sender_info['email'].lower() if sender_info['email'] else ''
                                    sender_match = query_lower in sender_name or query_lower in sender_email
                                
                                # Include message if either matches
                                if content_match or sender_match:
                                    # Add sender info to message for display
                                    msg['sender_info'] = sender_names.get(msg['sender_id'], {'name': 'Unknown', 'email': ''})
                                    filtered_messages.append(msg)
                            
                            messages = filtered_messages

                        # Attach reactions to messages
                        messages = await self._attach_reactions_to_messages(messages, user_id)

                        total_count = len(messages)
                        # Clean up message responses
                        messages = self._clean_messages_response(messages)
                        return messages, total_count
                    elif len(conversation_ids) > 1:
                        # Multiple conversations: search each separately and combine results
                        all_messages = []
                        for conv_id in conversation_ids:
                            try:
                                # Build query step by step - simplified without text search
                                conv_builder = self.supabase.table('messages')
                                conv_builder = conv_builder.select('*')
                                conv_builder = conv_builder.eq('conversation_id', conv_id)
                                conv_builder = conv_builder.eq('is_deleted', False)
                                
                                if message_type:
                                    conv_builder = conv_builder.eq('message_type', message_type)
                                
                                conv_builder = conv_builder.order('created_at', desc=True)
                                conv_builder = conv_builder.limit(limit)
                                
                                conv_result = conv_builder.execute()
                                
                                if conv_result.data:
                                    all_messages.extend(conv_result.data)
                            except Exception as e:
                                logger.error(f"Error searching conversation {conv_id}: {e}")
                                continue
                        
                        # Apply text search filtering in Python if query provided
                        if query and all_messages:
                            # Get unique sender IDs from all messages
                            sender_ids = list(set(msg['sender_id'] for msg in all_messages if msg.get('sender_id')))
                            
                            # Fetch sender names from signup tracking
                            sender_names = {}
                            if sender_ids:
                                senders_result = self.supabase.table('user_signup_tracking') \
                                    .select('user_id, email, name') \
                                    .in_('user_id', sender_ids) \
                                    .execute()
                                
                                for sender in senders_result.data or []:
                                    sender_names[sender['user_id']] = {
                                        'name': sender.get('name', ''),
                                        'email': sender.get('email', '')
                                    }
                            
                            # Filter messages by content OR sender name
                            query_lower = query.lower()
                            filtered_messages = []
                            
                            for msg in all_messages:
                                # Check message content
                                content_match = msg.get('content') and query_lower in msg['content'].lower()
                                
                                # Check sender name/email
                                sender_match = False
                                if msg.get('sender_id') in sender_names:
                                    sender_info = sender_names[msg['sender_id']]
                                    sender_name = sender_info['name'].lower() if sender_info['name'] else ''
                                    sender_email = sender_info['email'].lower() if sender_info['email'] else ''
                                    sender_match = query_lower in sender_name or query_lower in sender_email
                                
                                # Include message if either matches
                                if content_match or sender_match:
                                    # Add sender info to message for display
                                    msg['sender_info'] = sender_names.get(msg['sender_id'], {'name': 'Unknown', 'email': ''})
                                    filtered_messages.append(msg)
                            
                            all_messages = filtered_messages
                        
                        # Sort combined results and apply offset/limit
                        all_messages.sort(key=lambda m: m.get('created_at', ''), reverse=True)
                        start_idx = offset
                        end_idx = offset + limit
                        paginated_messages = all_messages[start_idx:end_idx]

                        # Attach reactions to messages
                        paginated_messages = await self._attach_reactions_to_messages(paginated_messages, user_id)

                        # Clean up message responses
                        paginated_messages = self._clean_messages_response(paginated_messages)
                        return paginated_messages, len(all_messages)
                    else:
                        return [], 0
                else:
                    return [], 0
            
        except Exception as e:
            logger.error(f"Error searching messages: {e}")
            return [], 0
    
    # HELPER METHODS
    
    async def _get_unread_message_count(self, user_id: str, conversation_id: str) -> int:
        """Get number of unread messages in a conversation for a user"""
        try:
            # Get user's last read message timestamp
            participant_result = self.supabase.table('conversation_participants') \
                .select('last_read_at, last_read_message_id') \
                .eq('user_id', user_id) \
                .eq('conversation_id', conversation_id) \
                .single() \
                .execute()
            
            if not participant_result.data:
                return 0
            
            last_read_at = participant_result.data.get('last_read_at')
            if not last_read_at:
                # User has never read messages, count all messages
                count_result = self.supabase.table('messages') \
                    .select('id', count='exact') \
                    .eq('conversation_id', conversation_id) \
                    .neq('sender_id', user_id) \
                    .eq('is_deleted', False) \
                    .execute()
                
                return count_result.count or 0
            
            # Count messages after last read timestamp
            count_result = self.supabase.table('messages') \
                .select('id', count='exact') \
                .eq('conversation_id', conversation_id) \
                .neq('sender_id', user_id) \
                .gt('created_at', last_read_at) \
                .eq('is_deleted', False) \
                .execute()
            
            return count_result.count or 0
            
        except Exception as e:
            logger.error(f"Error getting unread count: {e}")
            return 0
    
    async def _find_direct_conversation(self, user1_id: str, user2_id: str) -> Optional[Dict[str, Any]]:
        """Find existing direct conversation between two users"""
        try:
            # First, get conversation IDs where user1 is a participant
            user1_convs = self.supabase.table('conversation_participants') \
                .select('conversation_id') \
                .eq('user_id', user1_id) \
                .is_('left_at', 'null') \
                .execute()

            if not user1_convs.data:
                return None

            user1_conv_ids = [c['conversation_id'] for c in user1_convs.data]

            # Then, get conversation IDs where user2 is a participant
            user2_convs = self.supabase.table('conversation_participants') \
                .select('conversation_id') \
                .eq('user_id', user2_id) \
                .is_('left_at', 'null') \
                .execute()

            if not user2_convs.data:
                return None

            user2_conv_ids = [c['conversation_id'] for c in user2_convs.data]

            # Find common conversation IDs
            common_conv_ids = set(user1_conv_ids) & set(user2_conv_ids)

            if not common_conv_ids:
                return None

            # Get the conversation details for direct conversations with 2 participants
            for conv_id in common_conv_ids:
                conversation_result = self.supabase.table('conversations') \
                    .select('*') \
                    .eq('id', conv_id) \
                    .eq('conversation_type', 'direct') \
                    .eq('participant_count', 2) \
                    .execute()

                if conversation_result.data:
                    return conversation_result.data[0]

            return None

        except Exception as e:
            logger.error(f"Error finding direct conversation: {e}")
            return None
    
    async def _get_conversation_display_info(self, conversation: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        """Get display information for a direct conversation"""
        try:
            display_info = {
                'name': None,
                'image_url': None,
                'user_id': None  # Added user_id of other participant
            }

            # Get participants directly from the conversation_participants table since we removed the field
            conversation_id = conversation['id']
            participants_result = self.supabase.table('conversation_participants') \
                .select('user_id') \
                .eq('conversation_id', conversation_id) \
                .neq('user_id', user_id) \
                .is_('left_at', 'null') \
                .execute()

            if participants_result.data:
                other_user_id = participants_result.data[0]['user_id']
                display_info['user_id'] = other_user_id  # Add the other user's user_id

                # Get user info from signup tracking
                try:
                    user_info_result = self.supabase.table('user_signup_tracking') \
                        .select('email, name') \
                        .eq('user_id', other_user_id) \
                        .single() \
                        .execute()

                    if user_info_result.data:
                        user_name = user_info_result.data.get('name', '')
                        user_email = user_info_result.data.get('email', '')
                        fullname = user_name or user_email.split('@')[0] if user_email else 'Unknown User'
                        display_info['name'] = fullname
                    else:
                        display_info['name'] = 'Unknown User'
                except Exception:
                    display_info['name'] = 'Unknown User'

                # Get user avatar from user_profiles table
                try:
                    profile_result = self.supabase.table('user_profiles') \
                        .select('avatar_url') \
                        .eq('user_id', other_user_id) \
                        .execute()

                    if profile_result.data and profile_result.data[0].get('avatar_url'):
                        avatar_url = profile_result.data[0]['avatar_url']
                        # Generate signed URL for avatar
                        from user_profile_service import UserProfileService
                        profile_service = UserProfileService()
                        signed_avatar_url = profile_service._generate_signed_avatar_url(avatar_url)
                        display_info['image_url'] = signed_avatar_url
                except Exception as e:
                    logger.warning(f"Failed to get avatar for user {other_user_id}: {e}")

            return display_info

        except Exception as e:
            logger.error(f"Error getting display info: {e}")
            return {'name': 'Unknown', 'image_url': None, 'user_id': None}
    
    async def _get_users_online_status(self, user_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Get online status for multiple users"""
        try:
            result = self.supabase.table('user_online_status') \
                .select('user_id, is_online, last_seen_at, status_message') \
                .in_('user_id', user_ids) \
                .execute()
            
            status_map = {}
            for status in result.data:
                status_map[status['user_id']] = status
            
            # Fill in missing users with offline status
            for user_id in user_ids:
                if user_id not in status_map:
                    status_map[user_id] = {
                        'is_online': False,
                        'last_seen_at': None,
                        'status_message': None
                    }
            
            return status_map
            
        except Exception as e:
            logger.error(f"Error getting users online status: {e}")
            return {}
    
    async def _attach_media_to_messages(self, messages: List[Dict[str, Any]], user_id: str) -> List[Dict[str, Any]]:
        """Attach media attachments to messages with signed URLs"""
        if not messages:
            return messages

        try:
            from message_media_service import get_message_media_service
            media_service = get_message_media_service()

            # Get all message IDs
            message_ids = [msg['id'] for msg in messages]

            # Get all media for these messages
            media_result = self.supabase.table('message_media').select(
                '*'
            ).in_('message_id', message_ids).order('display_order').execute()

            # Group media by message_id
            media_by_message = {}
            for media_item in (media_result.data or []):
                msg_id = media_item['message_id']
                if msg_id not in media_by_message:
                    media_by_message[msg_id] = []

                # Generate signed URL for this media item
                media_item['url'] = media_service._generate_signed_url(media_item['file_path'])

                # Generate thumbnail URL if exists
                if media_item.get('thumbnail_path'):
                    media_item['thumbnail_url'] = media_service._generate_signed_url(media_item['thumbnail_path'])

                media_by_message[msg_id].append(media_item)

            # Attach media to each message
            for message in messages:
                message['media'] = media_by_message.get(message['id'], [])

            return messages

        except Exception as e:
            logger.warning(f"Failed to attach media to messages: {str(e)}")
            # Return messages without media if attachment fails
            for message in messages:
                message['media'] = []
            return messages

    async def _attach_reactions_to_messages(self, messages: List[Dict[str, Any]], user_id: str) -> List[Dict[str, Any]]:
        """Attach reactions to messages with grouped format"""
        if not messages:
            return messages

        try:
            # Get all message IDs
            message_ids = [msg['id'] for msg in messages]

            # Get all reactions for these messages
            reactions_result = self.supabase.table('message_reactions') \
                .select('message_id, user_id, reaction_type, created_at') \
                .in_('message_id', message_ids) \
                .execute()

            # Group reactions by message_id
            reactions_by_message = {}
            for reaction in (reactions_result.data or []):
                msg_id = reaction['message_id']
                reaction_type = reaction['reaction_type']
                reactor_id = reaction['user_id']

                if msg_id not in reactions_by_message:
                    reactions_by_message[msg_id] = {}

                if reaction_type not in reactions_by_message[msg_id]:
                    reactions_by_message[msg_id][reaction_type] = {
                        'count': 0,
                        'users': [],
                        'user_reacted': False
                    }

                reactions_by_message[msg_id][reaction_type]['count'] += 1
                reactions_by_message[msg_id][reaction_type]['users'].append(reactor_id)

                if reactor_id == user_id:
                    reactions_by_message[msg_id][reaction_type]['user_reacted'] = True

            # Attach reactions to each message
            for message in messages:
                msg_id = message['id']
                message['reactions'] = reactions_by_message.get(msg_id, {})

            return messages

        except Exception as e:
            logger.warning(f"Failed to attach reactions to messages: {str(e)}")
            # Return messages without reactions if attachment fails
            for message in messages:
                message['reactions'] = {}
            return messages

    async def _create_delivery_status_entries(self, conversation_id: str, message_id: str, sender_id: str):
        """Create delivery status entries for all conversation participants except sender"""
        try:
            # Get all participants except sender
            participants_result = self.supabase.table('conversation_participants') \
                .select('user_id') \
                .eq('conversation_id', conversation_id) \
                .neq('user_id', sender_id) \
                .is_('left_at', 'null') \
                .execute()

            if participants_result.data:
                delivery_entries = [
                    {
                        'message_id': message_id,
                        'user_id': participant['user_id']
                    }
                    for participant in participants_result.data
                ]

                self.supabase.table('message_delivery_status') \
                    .insert(delivery_entries) \
                    .execute()

        except Exception as e:
            logger.error(f"Error creating delivery status entries: {e}")
    
    async def _update_user_last_read(self, conversation_id: str, user_id: str, message_id: str):
        """Update user's last read message in conversation"""
        try:
            self.supabase.table('conversation_participants') \
                .update({
                    'last_read_at': datetime.now(timezone.utc).isoformat(),
                    'last_read_message_id': message_id
                }) \
                .eq('conversation_id', conversation_id) \
                .eq('user_id', user_id) \
                .execute()
                
        except Exception as e:
            logger.error(f"Error updating user last read: {e}")