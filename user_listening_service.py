"""
User Listening Service
Handles user interactions with podcasts: follows, saves, listening progress, ratings
"""
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from supabase import Client
import logging
import os

logger = logging.getLogger(__name__)

class UserListeningService:
    def __init__(self, supabase: Client):
        self.supabase = supabase
    
    # PODCAST FOLLOWS
    async def follow_podcast(self, user_id: str, podcast_id: str, notification_enabled: bool = True) -> Dict[str, Any]:
        """Follow a podcast"""
        try:
            logger.info(f"User {user_id} attempting to follow podcast {podcast_id}")
            
            # Ensure podcast exists and get the correct podcast_id to use
            resolved_podcast_id = await self._resolve_podcast_id(podcast_id)
            
            if not resolved_podcast_id:
                logger.error(f"Cannot follow podcast {podcast_id} - podcast not found or could not be imported")
                return {"success": False, "message": "Podcast not found"}
            
            logger.info(f"Using resolved podcast ID {resolved_podcast_id} for follow (original: {podcast_id})")
            
            # Check if already following (using resolved ID)
            existing = self.supabase.table('user_podcast_follows') \
                .select('id') \
                .eq('user_id', user_id) \
                .eq('podcast_id', resolved_podcast_id) \
                .execute()
            
            if existing.data:
                logger.info(f"User {user_id} already following podcast {resolved_podcast_id}")
                return {"success": False, "message": "Already following this podcast"}
            
            logger.info(f"Creating follow record for user {user_id} and podcast {resolved_podcast_id}")
            
            # Create follow record with resolved podcast ID
            result = self.supabase.table('user_podcast_follows') \
                .insert({
                    'user_id': user_id,
                    'podcast_id': resolved_podcast_id,
                    'notification_enabled': notification_enabled
                }) \
                .execute()
            
            if result.data:
                logger.info(f"Successfully created follow record: User {user_id} followed podcast {resolved_podcast_id}")

                # Log activity
                try:
                    from user_activity_service import get_user_activity_service
                    activity_service = get_user_activity_service()
                    await activity_service.log_activity(user_id, "podcast_followed", {"podcast_id": resolved_podcast_id})
                except Exception as e:
                    logger.warning(f"Failed to log podcast_followed activity: {str(e)}")

                return {"success": True, "data": result.data[0]}
            
            logger.error(f"Failed to create follow record for user {user_id} and podcast {resolved_podcast_id}")
            return {"success": False, "message": "Failed to follow podcast"}
            
        except Exception as e:
            logger.error(f"Error following podcast: {e}")
            return {"success": False, "message": f"Internal error: {str(e)}"}
    
    async def unfollow_podcast(self, user_id: str, podcast_id: str) -> Dict[str, Any]:
        """Unfollow a podcast"""
        try:
            # Check if this is one of the auto-follow podcasts that cannot be unfollowed
            auto_follow_podcasts = self._get_auto_follow_podcast_ids()
            if podcast_id in auto_follow_podcasts:
                logger.warning(f"User {user_id} attempted to unfollow auto-follow podcast {podcast_id}")
                return {"success": False, "message": "Cannot unfollow this podcast as it's automatically added to all accounts"}
            
            result = self.supabase.table('user_podcast_follows') \
                .delete() \
                .eq('user_id', user_id) \
                .eq('podcast_id', podcast_id) \
                .execute()
            
            logger.info(f"User {user_id} unfollowed podcast {podcast_id}")
            return {"success": True}
            
        except Exception as e:
            logger.error(f"Error unfollowing podcast: {e}")
            return {"success": False, "message": "Internal error"}
    
    async def get_user_followed_podcasts(
        self, 
        user_id: str, 
        limit: int = 50, 
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get podcasts followed by user with most recent episode"""
        try:
            # First get the follows with podcast data
            result = self.supabase.table('user_podcast_follows') \
                .select('''
                    followed_at, 
                    notification_enabled, 
                    podcast:podcasts(
                        id, listennotes_id, rss_url, title, description, publisher, 
                        language, image_url, thumbnail_url, explicit_content, 
                        is_featured, featured_priority, latest_episode_id, created_at, updated_at,
                        categories:podcast_category_mappings(
                            category:podcast_categories(id, name, display_name, color)
                        )
                    )
                ''') \
                .eq('user_id', user_id) \
                .order('followed_at', desc=True) \
                .range(offset, offset + limit - 1) \
                .execute()
            
            follows = result.data or []
            
            # Now enrich each podcast with its most recent episode
            for follow in follows:
                if follow.get('podcast') and follow['podcast'].get('id'):
                    podcast_id = follow['podcast']['id']
                    
                    # Get most recent episode using latest_episode_id from podcast
                    if follow['podcast'].get('latest_episode_id'):
                        episode_result = self.supabase.table('episodes') \
                            .select('id, listennotes_id, guid, title, description, audio_url, image_url, duration_seconds, explicit_content, published_at, created_at') \
                            .eq('id', follow['podcast']['latest_episode_id']) \
                            .single() \
                            .execute()
                        
                        if episode_result.data:
                            episode = episode_result.data
                            # Add pub_date for consistency with other episode formats
                            if episode.get('published_at'):
                                episode['pub_date'] = episode['published_at']
                            else:
                                episode['pub_date'] = episode.get('created_at')
                            follow['podcast']['most_recent_episode'] = episode
                        else:
                            follow['podcast']['most_recent_episode'] = None
                    else:
                        follow['podcast']['most_recent_episode'] = None
            
            return follows
        except Exception as e:
            logger.error(f"Error getting followed podcasts: {e}")
            return []
    
    async def get_user_followed_podcasts_count(self, user_id: str) -> Dict[str, int]:
        """Get total count of user's followed podcasts"""
        try:
            result = self.supabase.table('user_podcast_follows') \
                .select('*', count='exact', head=True) \
                .eq('user_id', user_id) \
                .execute()
            
            return {'count': result.count or 0}
        except Exception as e:
            logger.error(f"Error getting followed podcasts count: {e}")
            return {'count': 0}
    
    async def update_follow_settings(
        self, 
        user_id: str, 
        podcast_id: str, 
        notification_enabled: bool
    ) -> Dict[str, Any]:
        """Update follow notification settings"""
        try:
            result = self.supabase.table('user_podcast_follows') \
                .update({'notification_enabled': notification_enabled}) \
                .eq('user_id', user_id) \
                .eq('podcast_id', podcast_id) \
                .execute()
            
            return {"success": True, "data": result.data}
        except Exception as e:
            logger.error(f"Error updating follow settings: {e}")
            return {"success": False, "message": "Internal error"}
    
    # EPISODE SAVES
    async def save_episode(self, user_id: str, episode_id: str, notes: Optional[str] = None) -> Dict[str, Any]:
        """Save/bookmark an episode"""
        try:
            # Validate UUID format
            import uuid
            try:
                uuid.UUID(episode_id)
            except ValueError:
                return {"success": False, "message": "Invalid episode ID format"}
            
            # Check if already saved
            existing = self.supabase.table('user_episode_saves') \
                .select('id') \
                .eq('user_id', user_id) \
                .eq('episode_id', episode_id) \
                .execute()
            
            if existing.data:
                return {"success": False, "message": "Episode already saved"}
            
            # Create save record
            result = self.supabase.table('user_episode_saves') \
                .insert({
                    'user_id': user_id,
                    'episode_id': episode_id,
                    'notes': notes
                }) \
                .execute()
            
            if result.data:
                logger.info(f"User {user_id} saved episode {episode_id}")

                # Log activity - get podcast_id from episode
                try:
                    from user_activity_service import get_user_activity_service
                    activity_service = get_user_activity_service()

                    # Get podcast_id for this episode
                    episode_result = self.supabase.table('episodes').select('podcast_id').eq('id', episode_id).single().execute()
                    if episode_result.data:
                        podcast_id = episode_result.data['podcast_id']
                        await activity_service.log_activity(user_id, "podcast_saved", {"podcast_id": podcast_id, "episode_id": episode_id})
                except Exception as e:
                    logger.warning(f"Failed to log podcast_saved activity: {str(e)}")

                return {"success": True, "data": result.data[0]}
            
            return {"success": False, "message": "Failed to save episode"}
            
        except Exception as e:
            logger.error(f"Error saving episode: {e}")
            return {"success": False, "message": "Internal error"}
    
    async def unsave_episode(self, user_id: str, episode_id: str) -> Dict[str, Any]:
        """Remove episode from saves"""
        try:
            # Validate UUID format
            import uuid
            try:
                uuid.UUID(episode_id)
            except ValueError:
                return {"success": False, "message": "Invalid episode ID format"}
            
            result = self.supabase.table('user_episode_saves') \
                .delete() \
                .eq('user_id', user_id) \
                .eq('episode_id', episode_id) \
                .execute()
            
            if result.data:
                logger.info(f"User {user_id} unsaved episode {episode_id}")
                return {"success": True}
            else:
                logger.warning(f"No saved episode found for user {user_id} and episode {episode_id}")
                return {"success": False, "message": "Episode was not saved or already removed"}
            
        except Exception as e:
            logger.error(f"Error unsaving episode: {e}")
            return {"success": False, "message": "Internal error"}
    
    async def get_user_saved_episodes(
        self, 
        user_id: str, 
        limit: int = 50, 
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get episodes saved by user"""
        try:
            result = self.supabase.table('user_episode_saves') \
                .select('''
                    *,
                    episodes(
                        id, podcast_id, listennotes_id, guid, title, description, audio_url, image_url, duration_seconds, explicit_content, published_at, created_at, updated_at,
                        podcasts!episodes_podcast_id_fkey(title, publisher, image_url, thumbnail_url)
                    )
                ''') \
                .eq('user_id', user_id) \
                .order('saved_at', desc=True) \
                .range(offset, offset + limit - 1) \
                .execute()
            
            return result.data or []
            
        except Exception as e:
            logger.error(f"Error getting saved episodes: {e}")
            return []
    
    async def get_user_saved_episodes_count(self, user_id: str) -> Dict[str, int]:
        """Get total count of user's saved episodes"""
        try:
            result = self.supabase.table('user_episode_saves') \
                .select('*', count='exact', head=True) \
                .eq('user_id', user_id) \
                .execute()
            
            return {'count': result.count or 0}
        except Exception as e:
            logger.error(f"Error getting saved episodes count: {e}")
            return {'count': 0}
    
    async def update_episode_notes(
        self, 
        user_id: str, 
        episode_id: str, 
        notes: str
    ) -> Dict[str, Any]:
        """Update notes for a saved episode"""
        try:
            result = self.supabase.table('user_episode_saves') \
                .update({'notes': notes}) \
                .eq('user_id', user_id) \
                .eq('episode_id', episode_id) \
                .execute()
            
            return {"success": True, "data": result.data}
        except Exception as e:
            logger.error(f"Error updating episode notes: {e}")
            return {"success": False, "message": "Internal error"}
    
    # LISTENING PROGRESS
    async def get_episode_progress(self, user_id: str, episode_id: str) -> Dict[str, Any]:
        """Get listening progress for a specific episode"""
        try:
            # Try to find by episode ID first
            result = self.supabase.table('user_listening_progress') \
                .select('*') \
                .eq('user_id', user_id) \
                .eq('episode_id', episode_id) \
                .execute()

            # If not found by ID, try to find by listennotes_id
            if not result.data:
                episode_check = self.supabase.table('episodes') \
                    .select('id') \
                    .eq('listennotes_id', episode_id) \
                    .execute()

                if episode_check.data:
                    db_episode_id = episode_check.data[0]['id']
                    result = self.supabase.table('user_listening_progress') \
                        .select('*') \
                        .eq('user_id', user_id) \
                        .eq('episode_id', db_episode_id) \
                        .execute()

            if result.data:
                progress = result.data[0]
                return {
                    "success": True,
                    "data": {
                        "episode_id": progress['episode_id'],
                        "progress_seconds": progress['progress_seconds'],
                        "last_position_seconds": progress['progress_seconds'],
                        "duration_seconds": progress.get('duration_seconds'),
                        "progress_percentage": progress['progress_percentage'],
                        "playback_speed": progress.get('playback_speed', 1.0),
                        "is_completed": progress['is_completed'],
                        "last_played_at": progress['last_played_at'],
                        "completed_at": progress.get('completed_at')
                    }
                }

            # No progress found - return default progress of 0%
            return {
                "success": True,
                "data": {
                    "episode_id": episode_id,
                    "progress_seconds": 0,
                    "last_position_seconds": 0,
                    "duration_seconds": None,
                    "progress_percentage": 0.0,
                    "playback_speed": 1.0,
                    "is_completed": False,
                    "last_played_at": None,
                    "completed_at": None
                }
            }

        except Exception as e:
            logger.error(f"Error getting episode progress: {e}")
            return {"success": False, "message": "Internal error"}

    async def update_listening_progress(
        self,
        user_id: str,
        episode_id: str,
        progress_seconds: int,
        duration_seconds: Optional[int] = None,
        playback_speed: float = 1.0,
        is_completed: bool = False
    ) -> Dict[str, Any]:
        """Update or create listening progress for an episode"""
        try:
            # First, let's determine what type of ID we're dealing with
            import uuid
            is_uuid_format = False
            try:
                uuid.UUID(episode_id)
                is_uuid_format = True
            except ValueError:
                # Not a valid UUID format, likely a ListenNotes ID
                pass
            
            # Check if episode exists in our database
            episode_check = self.supabase.table('episodes') \
                .select('id, podcast_id') \
                .eq('id', episode_id) \
                .execute()
            
            # If episode doesn't exist by ID, try to find it by listennotes_id
            if not episode_check.data:
                episode_ln_check = self.supabase.table('episodes') \
                    .select('id, podcast_id') \
                    .eq('listennotes_id', episode_id) \
                    .execute()
                
                if episode_ln_check.data:
                    # Use the database episode ID instead of the ListenNotes ID
                    episode_id = episode_ln_check.data[0]['id']
                    logger.info(f"Found episode by listennotes_id, using database ID: {episode_id}")
                else:
                    # Episode doesn't exist in our database at all
                    # Check if there's an existing progress record (episode might have been deleted)
                    progress_check = self.supabase.table('user_listening_progress') \
                        .select('id') \
                        .eq('user_id', user_id) \
                        .eq('episode_id', episode_id) \
                        .execute()

                    if progress_check.data:
                        # There's existing progress for a deleted episode
                        logger.warning(f"Episode {episode_id} has been deleted but progress record exists. Updating progress anyway.")
                        # Continue with the update - allow progress updates for deleted episodes
                    else:
                        # Try to import from ListenNotes (works for both UUID-formatted ListenNotes IDs and regular IDs)
                        logger.warning(f"Episode {episode_id} not found in local database. Attempting to import from ListenNotes...")

                        try:
                            imported_episode = await self._import_episode_on_demand(episode_id)
                            if imported_episode:
                                episode_id = imported_episode['id']  # Use the imported episode's database ID
                                logger.info(f"Successfully imported episode on-demand: {episode_id}")
                            else:
                                return {"success": False, "message": "Episode not found and could not be imported. Please refresh the episode list.", "error_code": "EPISODE_NOT_FOUND"}
                        except Exception as import_error:
                            logger.error(f"Failed to import episode on-demand: {import_error}")
                            return {"success": False, "message": "Episode not found in database and import failed. Please try refreshing the episode list.", "error_code": "EPISODE_NOT_FOUND"}
            
            # Calculate progress percentage
            progress_percentage = 0.0
            if duration_seconds and duration_seconds > 0:
                progress_percentage = min((progress_seconds / duration_seconds) * 100, 100.0)
            
            # Set completion status based on progress
            if progress_percentage >= 95.0:  # Consider 95%+ as completed
                is_completed = True
            
            # Prepare progress data
            progress_data = {
                'user_id': user_id,
                'episode_id': episode_id,
                'progress_seconds': progress_seconds,
                'progress_percentage': progress_percentage,
                'playback_speed': playback_speed,
                'is_completed': is_completed,
                'last_played_at': datetime.now(timezone.utc).isoformat()
            }
            
            if duration_seconds:
                progress_data['duration_seconds'] = duration_seconds
            
            if is_completed and not progress_data.get('completed_at'):
                progress_data['completed_at'] = datetime.now(timezone.utc).isoformat()
            
            # Use upsert to handle both insert and update
            result = self.supabase.table('user_listening_progress') \
                .upsert(progress_data, on_conflict='user_id,episode_id') \
                .execute()
            
            if result.data:
                logger.info(f"Updated progress for user {user_id}, episode {episode_id}: {progress_percentage:.1f}%")

                # Log activity when episode is completed
                if is_completed:
                    try:
                        from user_activity_service import get_user_activity_service
                        activity_service = get_user_activity_service()

                        # Get podcast_id for this episode
                        episode_check_result = self.supabase.table('episodes').select('podcast_id').eq('id', episode_id).execute()
                        if episode_check_result.data:
                            podcast_id = episode_check_result.data[0]['podcast_id']
                            await activity_service.log_activity(user_id, "episode_listened", {"episode_id": episode_id, "podcast_id": podcast_id})
                    except Exception as e:
                        logger.warning(f"Failed to log episode_listened activity: {str(e)}")

                return {"success": True, "data": result.data[0]}
            
            return {"success": False, "message": "Failed to update progress"}
            
        except Exception as e:
            error_str = str(e)
            logger.error(f"Error updating listening progress: {error_str}")
            
            # Check if this is the foreign key constraint error
            if "foreign key constraint" in error_str.lower() and "episode_id" in error_str.lower():
                # Extract the episode ID from the error message if possible
                if "Key (episode_id)=" in error_str:
                    try:
                        import re
                        match = re.search(r'Key \(episode_id\)=\(([^)]+)\)', error_str)
                        if match:
                            failed_episode_id = match.group(1)
                            logger.error(f"Foreign key constraint failed for episode ID: {failed_episode_id}")
                    except:
                        pass
                
                return {
                    "success": False, 
                    "message": "This episode is no longer available. Please refresh the episode list and try a different episode.",
                    "error_code": "EPISODE_NOT_FOUND"
                }
            
            return {"success": False, "message": "Internal error"}
    
    async def get_continue_listening(
        self, 
        user_id: str, 
        limit: int = 10,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get episodes user is currently listening to (in progress) with pagination"""
        try:
            result = self.supabase.table('user_listening_progress') \
                .select('''
                    *,
                    episode:episodes(
                        id, podcast_id, listennotes_id, title, description, audio_url, image_url, duration_seconds, explicit_content, published_at, created_at, updated_at,
                        podcast:podcasts!episodes_podcast_id_fkey(title, publisher, image_url, thumbnail_url)
                    )
                ''') \
                .eq('user_id', user_id) \
                .eq('is_completed', False) \
                .gt('progress_seconds', 30)  \
                .order('last_played_at', desc=True) \
                .range(offset, offset + limit - 1) \
                .execute()
            
            return result.data
        except Exception as e:
            logger.error(f"Error getting continue listening: {e}")
            return []
    
    async def get_continue_listening_count(self, user_id: str) -> Dict[str, int]:
        """Get total count of episodes user is currently listening to"""
        try:
            result = self.supabase.table('user_listening_progress') \
                .select('*', count='exact', head=True) \
                .eq('user_id', user_id) \
                .eq('is_completed', False) \
                .gt('progress_seconds', 30) \
                .execute()
            
            return {'count': result.count or 0}
        except Exception as e:
            logger.error(f"Error getting continue listening count: {e}")
            return {'count': 0}
    
    async def get_listening_history(
        self, 
        user_id: str, 
        limit: int = 50, 
        offset: int = 0,
        completed_only: bool = False
    ) -> List[Dict[str, Any]]:
        """Get user's listening history"""
        try:
            query = self.supabase.table('user_listening_progress') \
                .select('''
                    *,
                    episode:episodes(
                        id, podcast_id, listennotes_id, guid, title, description, audio_url, image_url, duration_seconds, explicit_content, published_at, created_at, updated_at,
                        podcast:podcasts!episodes_podcast_id_fkey(title, publisher, image_url, thumbnail_url)
                    )
                ''') \
                .eq('user_id', user_id)
            
            if completed_only:
                query = query.eq('is_completed', True)
            
            result = query \
                .order('last_played_at', desc=True) \
                .range(offset, offset + limit - 1) \
                .execute()
            
            return result.data or []
        except Exception as e:
            logger.error(f"Error getting listening history: {e}")
            return []
    
    async def get_listening_history_count(self, user_id: str, completed_only: bool = False) -> Dict[str, int]:
        """Get total count of user's listening history"""
        try:
            query = self.supabase.table('user_listening_progress') \
                .select('*', count='exact', head=True) \
                .eq('user_id', user_id)
            
            if completed_only:
                query = query.eq('is_completed', True)
            
            result = query.execute()
            
            return {'count': result.count or 0}
        except Exception as e:
            logger.error(f"Error getting listening history count: {e}")
            return {'count': 0}
    
    async def mark_episode_completed(self, user_id: str, episode_id: str) -> Dict[str, Any]:
        """Mark an episode as completed"""
        try:
            # Validate UUID format
            import uuid
            try:
                uuid.UUID(episode_id)
            except ValueError:
                return {"success": False, "message": "Invalid episode ID format"}
            
            result = self.supabase.table('user_listening_progress') \
                .update({
                    'is_completed': True,
                    'completed_at': datetime.now(timezone.utc).isoformat(),
                    'progress_percentage': 100.0
                }) \
                .eq('user_id', user_id) \
                .eq('episode_id', episode_id) \
                .execute()
            
            return {"success": True, "data": result.data}
        except Exception as e:
            logger.error(f"Error marking episode completed: {e}")
            return {"success": False, "message": "Internal error"}
    
    # PODCAST RATINGS
    async def rate_podcast(
        self,
        user_id: str,
        podcast_id: str,
        rating: int,
        review_text: Optional[str] = None,
        is_public: bool = True
    ) -> Dict[str, Any]:
        """Rate a podcast (1-5 stars) with optional review"""
        try:
            if rating < 1 or rating > 5:
                return {"success": False, "message": "Rating must be between 1 and 5"}
            
            rating_data = {
                'user_id': user_id,
                'podcast_id': podcast_id,
                'rating': rating,
                'review_text': review_text,
                'is_public': is_public
            }
            
            # Use upsert to handle both new ratings and updates
            result = self.supabase.table('user_podcast_ratings') \
                .upsert(rating_data, on_conflict='user_id,podcast_id') \
                .execute()
            
            if result.data:
                logger.info(f"User {user_id} rated podcast {podcast_id}: {rating} stars")
                
                # Update podcast listen_score (average rating)
                await self._update_podcast_listen_score(podcast_id)
                
                return {"success": True, "data": result.data[0]}
            
            return {"success": False, "message": "Failed to save rating"}
            
        except Exception as e:
            logger.error(f"Error rating podcast: {e}")
            return {"success": False, "message": "Internal error"}
    
    async def get_user_ratings(
        self, 
        user_id: str, 
        limit: int = 20, 
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get ratings given by user"""
        try:
            result = self.supabase.table('user_podcast_ratings') \
                .select('''
                    *,
                    podcast:podcasts(title, publisher, image_url, thumbnail_url)
                ''') \
                .eq('user_id', user_id) \
                .order('created_at', desc=True) \
                .range(offset, offset + limit - 1) \
                .execute()
            
            return result.data
        except Exception as e:
            logger.error(f"Error getting user ratings: {e}")
            return []
    
    async def get_podcast_ratings(
        self, 
        podcast_id: str, 
        limit: int = 20, 
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get public ratings for a podcast"""
        try:
            result = self.supabase.table('user_podcast_ratings') \
                .select('rating, review_text, created_at') \
                .eq('podcast_id', podcast_id) \
                .eq('is_public', True) \
                .order('created_at', desc=True) \
                .range(offset, offset + limit - 1) \
                .execute()
            
            return result.data
        except Exception as e:
            logger.error(f"Error getting podcast ratings: {e}")
            return []
    
    async def _update_podcast_listen_score(self, podcast_id: str):
        """Update podcast's average listen score based on ratings"""
        try:
            # Calculate average rating
            result = self.supabase.rpc('calculate_avg_rating', {'podcast_id': podcast_id}).execute()
            
            if result.data and len(result.data) > 0:
                avg_rating = result.data[0].get('avg_rating', 0.0)
                
                # Update podcast listen_score
                self.supabase.table('podcasts') \
                    .update({'listen_score': round(avg_rating, 2)}) \
                    .eq('id', podcast_id) \
                    .execute()
                
        except Exception as e:
            logger.error(f"Error updating podcast listen score: {e}")
    
    # USER STATS
    async def get_user_listening_stats(self, user_id: str) -> Dict[str, Any]:
        """Get user's listening statistics"""
        try:
            # Get total listening time
            progress_result = self.supabase.table('user_listening_progress') \
                .select('progress_seconds') \
                .eq('user_id', user_id) \
                .execute()
            
            total_seconds = sum(p['progress_seconds'] for p in progress_result.data)
            total_hours = total_seconds / 3600
            
            # Get completed episodes count
            completed_result = self.supabase.table('user_listening_progress') \
                .select('id', count='exact') \
                .eq('user_id', user_id) \
                .eq('is_completed', True) \
                .execute()
            
            completed_episodes = completed_result.count or 0
            
            # Get followed podcasts count
            follows_result = self.supabase.table('user_podcast_follows') \
                .select('id', count='exact') \
                .eq('user_id', user_id) \
                .execute()
            
            followed_podcasts = follows_result.count or 0
            
            # Get saved episodes count
            saves_result = self.supabase.table('user_episode_saves') \
                .select('id', count='exact') \
                .eq('user_id', user_id) \
                .execute()
            
            saved_episodes = saves_result.count or 0
            
            return {
                'total_listening_hours': round(total_hours, 1),
                'completed_episodes': completed_episodes,
                'followed_podcasts': followed_podcasts,
                'saved_episodes': saved_episodes
            }
            
        except Exception as e:
            logger.error(f"Error getting user listening stats: {e}")
            return {
                'total_listening_hours': 0,
                'completed_episodes': 0,
                'followed_podcasts': 0,
                'saved_episodes': 0
            }
    
    async def _resolve_podcast_id(self, podcast_id: str) -> Optional[str]:
        """Resolve podcast ID to the correct ID in main podcasts table"""
        try:
            logger.info(f"Resolving podcast ID: {podcast_id}")
            
            # First check if podcast exists in main table by ID
            existing = self.supabase.table('podcasts') \
                .select('id') \
                .eq('id', podcast_id) \
                .execute()
            
            if existing.data:
                logger.info(f"Podcast {podcast_id} found directly in main table")
                return podcast_id
            
            # Check if it's a featured podcast that needs to be mapped to main table
            featured = self.supabase.table('featured_podcasts') \
                .select('podcast_id') \
                .eq('id', podcast_id) \
                .execute()
            
            if featured.data:
                listennotes_id = featured.data[0]['podcast_id']
                logger.info(f"Featured podcast {podcast_id} has listennotes_id: {listennotes_id}")
                
                # Check if main table has a podcast with this listennotes_id
                main_podcast = self.supabase.table('podcasts') \
                    .select('id') \
                    .eq('listennotes_id', listennotes_id) \
                    .execute()
                
                if main_podcast.data:
                    resolved_id = main_podcast.data[0]['id']
                    logger.info(f"Found existing main podcast with ID {resolved_id} for listennotes_id {listennotes_id}")
                    return resolved_id
                else:
                    # Import the featured podcast to main table
                    success = await self._ensure_podcast_exists(podcast_id)
                    if success:
                        # Return the original featured podcast ID since we imported it with same ID
                        return podcast_id
            
            # Check if podcast_id is actually a listennotes_id
            main_by_ln_id = self.supabase.table('podcasts') \
                .select('id') \
                .eq('listennotes_id', podcast_id) \
                .execute()
            
            if main_by_ln_id.data:
                resolved_id = main_by_ln_id.data[0]['id']
                logger.info(f"Found podcast by listennotes_id: {resolved_id}")
                return resolved_id
            
            logger.error(f"Could not resolve podcast ID {podcast_id}")
            return None
            
        except Exception as e:
            logger.error(f"Error resolving podcast ID: {e}")
            return None
    
    async def _ensure_podcast_exists(self, podcast_id: str) -> bool:
        """Ensure podcast exists in main podcasts table, import from featured_podcasts if needed"""
        try:
            logger.info(f"Ensuring podcast exists: {podcast_id}")
            
            # First check if podcast already exists in main table by ID
            existing = self.supabase.table('podcasts') \
                .select('id') \
                .eq('id', podcast_id) \
                .execute()
            
            if existing.data:
                logger.info(f"Podcast {podcast_id} already exists in main table")
                return True  # Already exists
            
            # Check if it exists in featured_podcasts table by ID
            featured = self.supabase.table('featured_podcasts') \
                .select('*') \
                .eq('id', podcast_id) \
                .execute()
            
            if featured.data:
                logger.info(f"Found podcast {podcast_id} in featured_podcasts, importing to main table")
                featured_podcast = featured.data[0]
                
                # Check if a podcast with this listennotes_id already exists in main table
                existing_by_ln_id = self.supabase.table('podcasts') \
                    .select('id') \
                    .eq('listennotes_id', featured_podcast['podcast_id']) \
                    .execute()
                
                if existing_by_ln_id.data:
                    logger.info(f"Podcast with listennotes_id {featured_podcast['podcast_id']} already exists in main table with ID {existing_by_ln_id.data[0]['id']}")
                    # The podcast already exists in main table, just return True
                    return True
                
                # Import from featured_podcasts to main podcasts table
                podcast_record = {
                    'id': featured_podcast['id'],  # Use the same UUID
                    'listennotes_id': featured_podcast['podcast_id'],  # ListenNotes ID
                    'title': featured_podcast['title'],
                    'description': featured_podcast['description'] or '',
                    'publisher': featured_podcast['publisher'] or 'Unknown Publisher',
                    'language': 'en',  # Default
                    'image_url': featured_podcast['image_url'] or '',
                    'thumbnail_url': featured_podcast['image_url'] or '',
                    'rss_url': '',  # Not available in featured_podcasts
                    'total_episodes': featured_podcast.get('total_episodes', 0),
                    'explicit_content': featured_podcast.get('explicit_content', False),
                    'created_at': 'now()',
                    'updated_at': 'now()'
                }
                
                # Insert into main podcasts table
                result = self.supabase.table('podcasts') \
                    .insert(podcast_record) \
                    .execute()
                
                if result.data:
                    logger.info(f"Successfully imported featured podcast to main table: {featured_podcast['title']}")
                    
                    # Also handle category mappings if the featured podcast has categories
                    try:
                        # Get category mappings from featured_podcast_category_mappings
                        category_mappings = self.supabase.table('featured_podcast_category_mappings') \
                            .select('category_id') \
                            .eq('featured_podcast_id', featured_podcast['id']) \
                            .execute()
                        
                        if category_mappings.data:
                            # Create mappings in podcast_category_mappings
                            mappings_to_insert = [
                                {
                                    'podcast_id': featured_podcast['id'],
                                    'category_id': mapping['category_id']
                                }
                                for mapping in category_mappings.data
                            ]
                            
                            category_result = self.supabase.table('podcast_category_mappings') \
                                .insert(mappings_to_insert) \
                                .execute()
                            
                            if category_result.data:
                                logger.info(f"Added {len(mappings_to_insert)} category mappings for imported podcast")
                    except Exception as cat_error:
                        logger.warning(f"Failed to import category mappings: {cat_error}")
                        # Don't fail the whole operation for category mappings
                    
                    return True
                else:
                    logger.error(f"Failed to import featured podcast {podcast_id} to main table")
                    return False
            
            # Check if podcast might exist by listennotes_id (in case podcast_id is actually a listennotes_id)
            listennotes_match = self.supabase.table('podcasts') \
                .select('id') \
                .eq('listennotes_id', podcast_id) \
                .execute()
            
            if listennotes_match.data:
                logger.info(f"Found podcast by listennotes_id {podcast_id}")
                return True
            
            # Check featured podcasts by podcast_id (listennotes_id)
            featured_by_ln_id = self.supabase.table('featured_podcasts') \
                .select('*') \
                .eq('podcast_id', podcast_id) \
                .execute()
            
            if featured_by_ln_id.data:
                logger.info(f"Found podcast by listennotes_id in featured_podcasts: {podcast_id}, importing to main table")
                featured_podcast = featured_by_ln_id.data[0]
                
                podcast_record = {
                    'listennotes_id': featured_podcast['podcast_id'],
                    'title': featured_podcast['title'],
                    'description': featured_podcast['description'] or '',
                    'publisher': featured_podcast['publisher'] or 'Unknown Publisher',
                    'language': 'en',
                    'image_url': featured_podcast['image_url'] or '',
                    'thumbnail_url': featured_podcast['image_url'] or '',
                    'rss_url': '',
                    'total_episodes': featured_podcast.get('total_episodes', 0),
                    'explicit_content': featured_podcast.get('explicit_content', False),
                    'created_at': 'now()',
                    'updated_at': 'now()'
                }
                
                result = self.supabase.table('podcasts') \
                    .insert(podcast_record) \
                    .execute()
                
                if result.data:
                    imported_id = result.data[0]['id']
                    logger.info(f"Successfully imported featured podcast by listennotes_id: {featured_podcast['title']}, new ID: {imported_id}")
                    return True
                else:
                    logger.error(f"Failed to import featured podcast by listennotes_id {podcast_id}")
                    return False
            
            # Podcast not found in either table
            logger.error(f"Podcast {podcast_id} not found in any table (checked by ID and listennotes_id)")
            return False
            
        except Exception as e:
            logger.error(f"Error ensuring podcast exists: {e}")
            return False
    
    def _get_auto_follow_podcast_ids(self) -> List[str]:
        """Get the list of auto-follow podcast IDs from environment variables"""
        auto_follow_ids = []
        
        # Get the two auto-follow podcast IDs from environment
        podcast_1_id = os.getenv("AUTO_FAVORITE_PODCAST_1_ID", "").strip()
        podcast_2_id = os.getenv("AUTO_FAVORITE_PODCAST_2_ID", "").strip()
        
        if podcast_1_id:
            auto_follow_ids.append(podcast_1_id)
        if podcast_2_id:
            auto_follow_ids.append(podcast_2_id)
        
        return auto_follow_ids
    
    async def _import_episode_on_demand(self, listennotes_episode_id: str) -> Optional[Dict[str, Any]]:
        """Import a single episode on-demand from ListenNotes API"""
        try:
            # Import the episode import service
            from episode_import_service import get_episode_import_service
            import os
            
            listennotes_api_key = os.getenv('LISTENNOTES_API_KEY')
            if not listennotes_api_key:
                logger.error("ListenNotes API key not configured")
                return None
            
            episode_service = get_episode_import_service(self.supabase, listennotes_api_key)
            
            # Import the specific episode
            imported_episode = await episode_service.import_single_episode_by_id(listennotes_episode_id)
            
            if imported_episode:
                logger.info(f"Successfully imported episode {listennotes_episode_id} on-demand")
                return imported_episode
            else:
                logger.warning(f"Could not import episode {listennotes_episode_id} from ListenNotes")
                return None
                
        except Exception as e:
            logger.error(f"Error importing episode on-demand: {e}")
            return None