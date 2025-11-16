"""
Episode Import Service
Handles on-demand episode fetching from ListenNotes API with minimal storage
"""
import httpx
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from supabase import Client

logger = logging.getLogger(__name__)

class EpisodeImportService:
    def __init__(self, supabase: Client, listennotes_api_key: str):
        self.supabase = supabase
        self.listennotes_api_key = listennotes_api_key
        self.listennotes_base_url = "https://listen-api.listennotes.com/api/v2"
    
    async def import_recent_episodes(self, podcast_id: str, listennotes_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Import the most recent episodes for a podcast from ListenNotes API
        Stores minimal data in episodes table
        """
        try:
            # Fetch episodes from ListenNotes API
            episodes_data = await self._fetch_episodes_from_listennotes(listennotes_id, limit)
            
            if not episodes_data:
                logger.warning(f"No episodes found for podcast {listennotes_id}")
                return []
            
            # Transform and insert minimal episode data
            episodes_to_insert = []
            for episode_data in episodes_data:
                episode_record = self._transform_episode_to_minimal(episode_data, podcast_id)
                episodes_to_insert.append(episode_record)
            
            # Insert episodes into database (with conflict handling)
            if episodes_to_insert:
                inserted_episodes = await self._insert_episodes_batch(episodes_to_insert)
                logger.info(f"Imported {len(inserted_episodes)} episodes for podcast {podcast_id}")
                return inserted_episodes
            
            return []
            
        except Exception as e:
            logger.error(f"Error importing episodes for podcast {podcast_id}: {e}")
            return []
    
    async def _fetch_episodes_from_listennotes(self, listennotes_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Fetch episodes from ListenNotes API with pagination support"""
        try:
            all_episodes = []
            next_pub_date = None

            async with httpx.AsyncClient() as client:
                headers = {
                    'X-ListenAPI-Key': self.listennotes_api_key
                }

                # Fetch episodes in batches (API returns max ~10 per request)
                while len(all_episodes) < limit:
                    params = {
                        'sort': 'recent_first'
                    }

                    # Add pagination parameter if we have it
                    if next_pub_date is not None:
                        params['next_episode_pub_date'] = next_pub_date

                    # Get podcast episodes
                    response = await client.get(
                        f"{self.listennotes_base_url}/podcasts/{listennotes_id}",
                        headers=headers,
                        params=params
                    )

                    if response.status_code != 200:
                        logger.error(f"ListenNotes API error: {response.status_code} - {response.text}")
                        break

                    podcast_data = response.json()
                    episodes = podcast_data.get('episodes', [])

                    if not episodes:
                        # No more episodes available
                        logger.info(f"No more episodes available for {listennotes_id}, got {len(all_episodes)} total")
                        break

                    all_episodes.extend(episodes)

                    # Get next_episode_pub_date for pagination
                    next_pub_date = podcast_data.get('next_episode_pub_date')

                    if next_pub_date is None or next_pub_date == 0:
                        # No more pages
                        logger.info(f"Reached end of episodes for {listennotes_id}, got {len(all_episodes)} total")
                        break

                    logger.debug(f"Fetched {len(episodes)} episodes, total so far: {len(all_episodes)}")

                # Return up to the requested limit
                return all_episodes[:limit]

        except Exception as e:
            logger.error(f"Error fetching episodes from ListenNotes: {e}")
            return []
    
    def _transform_episode_to_minimal(self, episode_data: Dict[str, Any], podcast_id: str) -> Dict[str, Any]:
        """Transform ListenNotes episode data to minimal storage format"""
        
        # Convert timestamp to datetime
        published_at = None
        if episode_data.get('pub_date_ms'):
            published_at = datetime.fromtimestamp(
                episode_data['pub_date_ms'] / 1000, 
                tz=timezone.utc
            ).isoformat()
        
        return {
            'listennotes_id': episode_data.get('id'),  # ListenNotes episode ID
            'podcast_id': podcast_id,  # Our internal podcast UUID
            'title': episode_data.get('title', '').strip()[:500],  # Truncate title
            'description': episode_data.get('description', '').strip()[:1000],  # Truncated description
            'published_at': published_at,
            'duration_seconds': episode_data.get('audio_length_sec', 0),
            'image_url': episode_data.get('image'),
            'audio_url': episode_data.get('audio'),  # Include audio URL for playback
            # Store minimal metadata for on-demand loading
            'explicit_content': episode_data.get('explicit_content', False),
            # Don't store: transcript, full description, thumbnail_url (fetch on-demand)
        }
    
    async def _insert_episodes_batch(self, episodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Insert episodes with conflict resolution (upsert)"""
        try:
            # Use upsert to handle duplicates
            result = self.supabase.table('episodes') \
                .upsert(episodes, on_conflict='listennotes_id') \
                .execute()
            
            if result.data:
                return result.data
            else:
                logger.error("Failed to insert episodes - no data returned")
                return []
                
        except Exception as e:
            logger.error(f"Error inserting episodes batch: {e}")
            return []
    
    async def check_episodes_exist(self, podcast_id: str) -> bool:
        """Check if episodes already exist for a podcast"""
        try:
            result = self.supabase.table('episodes') \
                .select('id') \
                .eq('podcast_id', podcast_id) \
                .limit(1) \
                .execute()
            
            return len(result.data) > 0
            
        except Exception as e:
            logger.error(f"Error checking if episodes exist: {e}")
            return False
    
    async def get_episode_count(self, podcast_id: str) -> int:
        """Get the current number of episodes for a podcast"""
        try:
            result = self.supabase.table('episodes') \
                .select('id', count='exact') \
                .eq('podcast_id', podcast_id) \
                .execute()
            
            return result.count or 0
            
        except Exception as e:
            logger.error(f"Error getting episode count: {e}")
            return 0
    
    async def cleanup_old_episodes(self, podcast_id: str, keep_count: int = 20) -> int:
        """
        Remove old episodes, keeping only the most recent ones
        Returns number of episodes deleted
        """
        try:
            # Get all episodes for this podcast, ordered by published_at
            result = self.supabase.table('episodes') \
                .select('id, published_at') \
                .eq('podcast_id', podcast_id) \
                .order('published_at', desc=True) \
                .execute()
            
            episodes = result.data
            if len(episodes) <= keep_count:
                return 0  # Nothing to delete
            
            # Get episodes to delete (older than the most recent keep_count)
            episodes_to_delete = episodes[keep_count:]
            episode_ids_to_delete = [ep['id'] for ep in episodes_to_delete]
            
            # Delete old episodes
            delete_result = self.supabase.table('episodes') \
                .delete() \
                .in_('id', episode_ids_to_delete) \
                .execute()
            
            deleted_count = len(episode_ids_to_delete)
            logger.info(f"Deleted {deleted_count} old episodes for podcast {podcast_id}")
            
            # Also clean up related user data for deleted episodes
            await self._cleanup_user_data_for_deleted_episodes(episode_ids_to_delete)
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error cleaning up old episodes: {e}")
            return 0
    
    async def _cleanup_user_data_for_deleted_episodes(self, episode_ids: List[str]):
        """Clean up user listening progress and saves for deleted episodes"""
        try:
            if not episode_ids:
                return
            
            # Delete user listening progress
            self.supabase.table('user_listening_progress') \
                .delete() \
                .in_('episode_id', episode_ids) \
                .execute()
            
            # Delete user episode saves
            self.supabase.table('user_episode_saves') \
                .delete() \
                .in_('episode_id', episode_ids) \
                .execute()
            
            logger.info(f"Cleaned up user data for {len(episode_ids)} deleted episodes")
            
        except Exception as e:
            logger.error(f"Error cleaning up user data for deleted episodes: {e}")
    
    async def import_single_episode_by_id(self, listennotes_episode_id: str) -> Optional[Dict[str, Any]]:
        """Import a single episode by its ListenNotes ID"""
        try:
            # Fetch episode details from ListenNotes API
            episode_data = await self._fetch_single_episode_from_listennotes(listennotes_episode_id)
            
            if not episode_data:
                logger.warning(f"Episode {listennotes_episode_id} not found in ListenNotes")
                return None
            
            # We need the podcast ID to store this episode
            # First check if we have the podcast in our database
            podcast_listennotes_id = episode_data.get('podcast', {}).get('id')
            if not podcast_listennotes_id:
                logger.error(f"No podcast ID found for episode {listennotes_episode_id}")
                return None
            
            # Find the podcast in our database
            podcast_result = self.supabase.table('podcasts') \
                .select('id') \
                .eq('listennotes_id', podcast_listennotes_id) \
                .execute()
            
            if not podcast_result.data:
                # Podcast doesn't exist in our database yet, we need to import it first
                logger.warning(f"Podcast {podcast_listennotes_id} not found in database for episode {listennotes_episode_id}")
                
                # Try to import the podcast first
                from podcast_service import PodcastDiscoveryService
                podcast_service = PodcastDiscoveryService(self.supabase)
                imported_podcast = await podcast_service.import_podcast_from_listennotes(podcast_listennotes_id)
                
                if imported_podcast:
                    podcast_id = imported_podcast['id']
                    logger.info(f"Successfully imported podcast {podcast_listennotes_id} for episode {listennotes_episode_id}")
                else:
                    logger.error(f"Failed to import podcast {podcast_listennotes_id} for episode {listennotes_episode_id}")
                    return None
            else:
                podcast_id = podcast_result.data[0]['id']
            
            # Transform episode data and insert
            episode_record = self._transform_episode_to_minimal(episode_data, podcast_id)
            
            # Insert the single episode
            result = self.supabase.table('episodes') \
                .upsert([episode_record], on_conflict='listennotes_id') \
                .execute()
            
            if result.data:
                logger.info(f"Successfully imported episode {listennotes_episode_id}")
                return result.data[0]
            else:
                logger.error(f"Failed to insert episode {listennotes_episode_id}")
                return None
                
        except Exception as e:
            logger.error(f"Error importing single episode {listennotes_episode_id}: {e}")
            return None
    
    async def _fetch_single_episode_from_listennotes(self, episode_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single episode from ListenNotes API"""
        try:
            async with httpx.AsyncClient() as client:
                headers = {
                    'X-ListenAPI-Key': self.listennotes_api_key
                }
                
                # Get episode details
                response = await client.get(
                    f"{self.listennotes_base_url}/episodes/{episode_id}",
                    headers=headers
                )
                
                if response.status_code != 200:
                    logger.error(f"ListenNotes API error: {response.status_code} - {response.text}")
                    return None
                
                return response.json()
                
        except Exception as e:
            logger.error(f"Error fetching episode {episode_id} from ListenNotes: {e}")
            return None

# Singleton instance
episode_import_service = None

def get_episode_import_service(supabase: Client, listennotes_api_key: str) -> EpisodeImportService:
    """Get or create episode import service instance"""
    global episode_import_service
    if episode_import_service is None:
        episode_import_service = EpisodeImportService(supabase, listennotes_api_key)
    return episode_import_service