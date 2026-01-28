"""
Podcast Discovery Service
Handles podcast/episode discovery, featured content, and ListenNotes integration
"""
from typing import Dict, List, Any, Optional, Tuple
import asyncio
import httpx
import html
from datetime import datetime, timezone
from supabase import Client
import os
import logging
from episode_import_service import get_episode_import_service
from datetime_utils import format_datetime_central
from podcast_episode_cache_service import get_podcast_episode_cache_service

logger = logging.getLogger(__name__)

class PodcastDiscoveryService:
    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.listennotes_api_key = os.getenv('LISTENNOTES_API_KEY')
        self.listennotes_base_url = "https://listen-api.listennotes.com/api/v2"
        self.episode_cache = get_podcast_episode_cache_service()
        
    async def get_categories(self) -> List[Dict[str, Any]]:
        """Get all active podcast categories"""
        try:
            result = self.supabase.table('podcast_categories') \
                .select('*') \
                .eq('is_active', True) \
                .order('sort_order') \
                .execute()
            
            return result.data
        except Exception as e:
            logger.error(f"Error getting categories: {e}")
            return []
    
    async def get_most_recent_episode(self, podcast_id: str) -> Optional[Dict[str, Any]]:
        """Get the most recent episode for a podcast with smart in-memory + database caching and TTL"""
        try:
            from datetime import datetime, timezone, timedelta

            # Check in-memory cache first (fastest path)
            cached_episode = self.episode_cache.get_latest_episode(podcast_id)
            if cached_episode:
                logger.debug(f"Returning latest episode from in-memory cache for podcast {podcast_id[:8]}...")
                return cached_episode

            # Check if caching is enabled (default: True)
            cache_enabled = os.getenv('ENABLE_LATEST_EPISODE_CACHE', 'true').lower() in ('true', '1', 'yes')

            # Get TTL from environment variable (default: 360 minutes = 6 hours)
            ttl_minutes = int(os.getenv('LATEST_EPISODE_TTL_MINUTES', '360'))

            # First get the podcast's latest_episode_id and last update time
            # Handle missing latest_episode_updated_at column gracefully
            try:
                podcast_result = self.supabase.table('podcasts') \
                    .select('id, latest_episode_id, listennotes_id, latest_episode_updated_at, title') \
                    .eq('id', podcast_id) \
                    .single() \
                    .execute()
            except Exception as e:
                if 'latest_episode_updated_at' in str(e):
                    # Column doesn't exist yet, fall back to query without it
                    logger.warning(f"latest_episode_updated_at column not found, using fallback query")
                    podcast_result = self.supabase.table('podcasts') \
                        .select('id, latest_episode_id, listennotes_id, title') \
                        .eq('id', podcast_id) \
                        .single() \
                        .execute()
                else:
                    raise

            if not podcast_result.data:
                logger.warning(f"Podcast {podcast_id} not found")
                return None

            podcast_data = podcast_result.data
            latest_episode_id = podcast_data.get('latest_episode_id')
            latest_episode_updated_at = podcast_data.get('latest_episode_updated_at')
            listennotes_id = podcast_data.get('listennotes_id')

            # If caching is disabled, always fetch fresh data
            if not cache_enabled:
                logger.info(f"Latest episode cache is DISABLED, fetching fresh data for podcast {podcast_id}")
                if listennotes_id:
                    fresh_episode = await self._refresh_latest_episode_from_api(podcast_id, listennotes_id)
                    if fresh_episode:
                        # Cache in memory for faster subsequent access
                        self.episode_cache.set_latest_episode(podcast_id, fresh_episode)
                        return fresh_episode
                # Fallback to cached episode if API refresh failed
                if latest_episode_id:
                    logger.warning(f"API refresh failed for podcast {podcast_id}, falling back to cached episode")
                    episode_result = self.supabase.table('episodes') \
                        .select('id, podcast_id, listennotes_id, guid, title, description, audio_url, image_url, duration_seconds, explicit_content, published_at, created_at, updated_at') \
                        .eq('id', latest_episode_id) \
                        .single() \
                        .execute()

                    if episode_result.data:
                        episode = episode_result.data
                        if 'published_at' in episode and episode['published_at']:
                            episode['pub_date'] = episode['published_at']
                        else:
                            episode['pub_date'] = episode.get('created_at')
                        return episode
                return None

            # Caching is enabled - check if we need to refresh (TTL expired or no latest episode)
            needs_refresh = True
            if latest_episode_id:
                if latest_episode_updated_at:
                    # TTL checking is available
                    try:
                        updated_time = datetime.fromisoformat(latest_episode_updated_at.replace('Z', '+00:00'))
                        ttl_threshold = datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes)
                        needs_refresh = updated_time < ttl_threshold

                        if not needs_refresh:
                            logger.debug(f"Latest episode cache is fresh for podcast {podcast_id} (TTL: {ttl_minutes} minutes)")
                        else:
                            logger.info(f"Latest episode cache expired for podcast {podcast_id} (TTL: {ttl_minutes} minutes), refreshing...")
                    except Exception as e:
                        logger.warning(f"Error parsing latest_episode_updated_at: {e}")
                        needs_refresh = True
                else:
                    # No TTL column available, refresh periodically based on in-memory cache
                    # This ensures episodes eventually refresh even without the database column
                    logger.debug(f"No TTL column available, checking in-memory cache for podcast {podcast_id}")
                    # If in-memory cache is empty, trigger refresh (first access or cache expired)
                    needs_refresh = True
            else:
                logger.info(f"No cached latest episode for podcast {podcast_id}, fetching fresh...")

            # If cache is fresh, return cached episode
            if not needs_refresh and latest_episode_id:
                episode_result = self.supabase.table('episodes') \
                    .select('id, podcast_id, listennotes_id, guid, title, description, audio_url, image_url, duration_seconds, explicit_content, published_at, created_at, updated_at') \
                    .eq('id', latest_episode_id) \
                    .single() \
                    .execute()

                if episode_result.data:
                    episode = episode_result.data
                    # Convert published_at to pub_date for consistency
                    if 'published_at' in episode and episode['published_at']:
                        episode['pub_date'] = episode['published_at']
                    else:
                        episode['pub_date'] = episode.get('created_at')
                    return episode

            # Cache expired or no cached episode - refresh from ListenNotes API
            if listennotes_id:
                fresh_episode = await self._refresh_latest_episode_from_api(podcast_id, listennotes_id)
                if fresh_episode:
                    # Cache in memory for faster subsequent access
                    self.episode_cache.set_latest_episode(podcast_id, fresh_episode)
                    return fresh_episode

            # Fallback to cached episode if API refresh failed
            if latest_episode_id:
                logger.warning(f"API refresh failed for podcast {podcast_id}, falling back to cached episode")
                episode_result = self.supabase.table('episodes') \
                    .select('id, podcast_id, listennotes_id, guid, title, description, audio_url, image_url, duration_seconds, explicit_content, published_at, created_at, updated_at') \
                    .eq('id', latest_episode_id) \
                    .single() \
                    .execute()

                if episode_result.data:
                    episode = episode_result.data
                    if 'published_at' in episode and episode['published_at']:
                        episode['pub_date'] = episode['published_at']
                    else:
                        episode['pub_date'] = episode.get('created_at')
                    return episode

            return None
        except Exception as e:
            logger.error(f"Error getting most recent episode for podcast {podcast_id}: {e}")
            return None
    
    async def enrich_podcast_with_recent_episode(self, podcast: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich a podcast dict with its most recent episode using TTL-based caching"""
        # Use get_most_recent_episode which respects ENABLE_LATEST_EPISODE_CACHE and LATEST_EPISODE_TTL_MINUTES
        podcast_uuid = podcast.get('id')
        listennotes_id = podcast.get('listennotes_id')

        # For local database podcasts, use the smart caching with TTL
        if podcast_uuid:
            recent_episode = await self.get_most_recent_episode(podcast_uuid)
            if recent_episode:
                podcast['most_recent_episode'] = recent_episode
                return podcast

        # Fallback for ListenNotes-only podcasts (not yet in our DB)
        if podcast.get('source') == 'listennotes' and listennotes_id:
            recent_episode = await self._get_listennotes_latest_episode(listennotes_id)
            if recent_episode:
                podcast['most_recent_episode'] = recent_episode

        return podcast
    
    async def update_podcast_latest_episode_id(self, podcast_id: str) -> bool:
        """Update the latest_episode_id for a specific podcast"""
        try:
            # Call the database function to update latest_episode_id
            result = self.supabase.rpc('update_podcast_latest_episode', {'p_podcast_id': podcast_id}).execute()
            
            if result.data:
                # Also update the latest_episode_updated_at timestamp if column exists
                try:
                    from datetime import datetime, timezone
                    self.supabase.table('podcasts') \
                        .update({'latest_episode_updated_at': datetime.now(timezone.utc).isoformat()}) \
                        .eq('id', podcast_id) \
                        .execute()
                except Exception as e:
                    if 'latest_episode_updated_at' in str(e):
                        logger.debug(f"latest_episode_updated_at column not available, skipping timestamp update")
                    else:
                        logger.warning(f"Error updating latest_episode_updated_at: {e}")
                
                logger.info(f"Updated latest_episode_id for podcast {podcast_id}")
                return True
            else:
                logger.warning(f"No episode found to set as latest for podcast {podcast_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error updating latest_episode_id for podcast {podcast_id}: {e}")
            return False
    
    async def _refresh_latest_episode_from_api(self, podcast_id: str, listennotes_id: str) -> Optional[Dict[str, Any]]:
        """Refresh the latest episode from ListenNotes API and update cache"""
        try:
            from datetime import datetime, timezone
            
            if not self.listennotes_api_key:
                logger.error("ListenNotes API key not configured")
                return None
            
            # Fetch latest episode from ListenNotes API
            import httpx
            async with httpx.AsyncClient() as client:
                headers = {'X-ListenAPI-Key': self.listennotes_api_key}
                
                # Get podcast details which includes latest episode
                response = await client.get(
                    f"{self.listennotes_base_url}/podcasts/{listennotes_id}",
                    headers=headers,
                    params={'sort': 'recent_first'}
                )
                
                if response.status_code != 200:
                    logger.warning(f"Failed to fetch podcast from ListenNotes: {response.status_code}")
                    return None
                
                data = response.json()
                episodes = data.get('episodes', [])
                
                if not episodes:
                    logger.warning(f"No episodes found for podcast {listennotes_id}")
                    return None
                
                latest_episode_data = episodes[0]
                latest_episode_ln_id = latest_episode_data.get('id')
                
                if not latest_episode_ln_id:
                    logger.warning(f"No episode ID in API response for podcast {listennotes_id}")
                    return None
                
                # Check if this episode already exists in our database
                existing_episode = self.supabase.table('episodes') \
                    .select('id') \
                    .eq('listennotes_id', latest_episode_ln_id) \
                    .execute()
                
                episode_db_id = None
                
                if existing_episode.data:
                    # Episode exists, use its database ID
                    episode_db_id = existing_episode.data[0]['id']
                    logger.info(f"Latest episode {latest_episode_ln_id} already exists in database")
                else:
                    # Episode doesn't exist, import it
                    logger.info(f"Importing new latest episode {latest_episode_ln_id}")
                    
                    # Transform and insert the episode
                    published_at = None
                    if latest_episode_data.get('pub_date_ms'):
                        published_at = datetime.fromtimestamp(
                            latest_episode_data['pub_date_ms'] / 1000, 
                            tz=timezone.utc
                        ).isoformat()
                    
                    episode_record = {
                        'listennotes_id': latest_episode_ln_id,
                        'podcast_id': podcast_id,
                        'title': latest_episode_data.get('title', '').strip()[:500],
                        'description': latest_episode_data.get('description', '').strip()[:1000],
                        'published_at': published_at,
                        'duration_seconds': latest_episode_data.get('audio_length_sec', 0),
                        'image_url': latest_episode_data.get('image'),
                        'audio_url': latest_episode_data.get('audio'),
                        'explicit_content': latest_episode_data.get('explicit_content', False),
                    }
                    
                    insert_result = self.supabase.table('episodes') \
                        .upsert(episode_record, on_conflict='listennotes_id') \
                        .execute()
                    
                    if insert_result.data:
                        episode_db_id = insert_result.data[0]['id']
                        logger.info(f"Successfully imported episode: {latest_episode_data.get('title')}")
                    else:
                        logger.error(f"Failed to import episode {latest_episode_ln_id}")
                        return None
                
                # Update the podcast's latest_episode_id and timestamp
                if episode_db_id:
                    # Try to update with timestamp, fall back without it if column doesn't exist
                    try:
                        update_result = self.supabase.table('podcasts') \
                            .update({
                                'latest_episode_id': episode_db_id,
                                'latest_episode_updated_at': datetime.now(timezone.utc).isoformat()
                            }) \
                            .eq('id', podcast_id) \
                            .execute()
                    except Exception as e:
                        if 'latest_episode_updated_at' in str(e):
                            logger.debug(f"latest_episode_updated_at column not available, updating without timestamp")
                            update_result = self.supabase.table('podcasts') \
                                .update({'latest_episode_id': episode_db_id}) \
                                .eq('id', podcast_id) \
                                .execute()
                        else:
                            raise
                    
                    if update_result.data:
                        logger.info(f"✅ Updated latest episode cache for podcast {podcast_id}")
                        
                        # Return the episode details
                        episode_result = self.supabase.table('episodes') \
                            .select('id, podcast_id, listennotes_id, guid, title, description, audio_url, image_url, duration_seconds, explicit_content, published_at, created_at, updated_at') \
                            .eq('id', episode_db_id) \
                            .single() \
                            .execute()
                        
                        if episode_result.data:
                            episode = episode_result.data
                            if 'published_at' in episode and episode['published_at']:
                                episode['pub_date'] = episode['published_at']
                            else:
                                episode['pub_date'] = episode.get('created_at')
                            return episode
                    else:
                        logger.error(f"Failed to update podcast latest_episode_id")
                
                return None
                
        except Exception as e:
            logger.error(f"Error refreshing latest episode from API for podcast {podcast_id}: {e}")
            return None
    
    async def get_featured_podcasts(
        self,
        limit: int = 20,
        offset: int = 0,
        user_id: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get featured podcasts from podcasts table with pagination"""
        try:
            # First get total count of featured podcasts
            count_result = self.supabase.table('podcasts') \
                .select('id', count='exact') \
                .eq('is_featured', True) \
                .execute()

            total_count = count_result.count or 0

            # Query the podcasts table for featured podcasts with pagination, including latest_episode_id
            result = self.supabase.table('podcasts') \
                .select('id, listennotes_id, rss_url, title, description, publisher, language, image_url, thumbnail_url, explicit_content, is_featured, latest_episode_id, created_at, updated_at') \
                .eq('is_featured', True) \
                .order('featured_priority', desc=True) \
                .range(offset, offset + limit - 1) \
                .execute()

            featured_data = result.data or []

            # Batch fetch latest episodes for all podcasts
            episode_ids = [p['latest_episode_id'] for p in featured_data if p.get('latest_episode_id')]
            episodes_map = {}

            if episode_ids:
                episodes_result = self.supabase.table('episodes') \
                    .select('id, podcast_id, listennotes_id, guid, title, description, audio_url, image_url, duration_seconds, explicit_content, published_at, created_at, updated_at') \
                    .in_('id', episode_ids) \
                    .execute()

                # Create mapping of episode_id to episode data
                for episode in (episodes_result.data or []):
                    episodes_map[episode['id']] = episode

            # Attach episode data to podcasts
            enriched_podcasts = []
            for podcast in featured_data:
                episode_id = podcast.get('latest_episode_id')
                if episode_id and episode_id in episodes_map:
                    podcast['most_recent_episode'] = episodes_map[episode_id]
                # Remove latest_episode_id from response
                podcast.pop('latest_episode_id', None)
                enriched_podcasts.append(podcast)

            # Update claimed status for all podcasts
            await self._update_claimed_status_batch(enriched_podcasts)

            # Update following status if user_id provided
            if user_id:
                await self._update_following_status_batch(enriched_podcasts, user_id)
            else:
                # Set following to false for all podcasts, except featured ones
                for podcast in enriched_podcasts:
                    if podcast.get('is_featured'):
                        podcast['following'] = True
                    else:
                        podcast['following'] = False

            logger.info(f"Found {len(enriched_podcasts)} featured podcasts from {total_count} total")

            return enriched_podcasts, total_count
        except Exception as e:
            logger.error(f"Error getting featured podcasts paginated: {e}")
            return [], 0
    
    async def get_featured_podcasts_from_config(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get featured podcasts from configuration list using ListenNotes IDs"""
        try:
            from featured_podcasts_config import FEATURED_PODCAST_IDS
            
            if not FEATURED_PODCAST_IDS:
                return []
            
            # Get podcasts by ListenNotes ID in the specified order
            podcasts = []
            found_count = 0
            
            for listennotes_id in FEATURED_PODCAST_IDS[:limit]:
                result = self.supabase.table('podcasts') \
                    .select('*') \
                    .eq('listennotes_id', listennotes_id) \
                    .execute()
                
                if result.data:
                    podcasts.extend(result.data)
                    found_count += 1
                else:
                    logger.warning(f"Podcast with ListenNotes ID {listennotes_id} not found in database")
            
            # If no podcasts found from config, fallback to any featured podcasts in database
            if not podcasts:
                logger.info(f"No podcasts found from config list. Falling back to database featured podcasts.")
                fallback_result = self.supabase.table('podcasts') \
                    .select('*') \
                    .eq('is_featured', True) \
                    .order('featured_priority', desc=True) \
                    .order('created_at', desc=True) \
                    .limit(limit) \
                    .execute()
                
                podcasts = fallback_result.data or []
            
            logger.info(f"Returning {len(podcasts)} featured podcasts ({found_count} from config)")
            return podcasts
            
        except Exception as e:
            logger.error(f"Error getting featured podcasts from config: {e}")
            return []
    
    async def get_featured_networks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get featured podcast networks"""
        try:
            result = self.supabase.table('podcasts') \
                .select('*') \
                .eq('is_network', True) \
                .eq('is_featured', True) \
                .order('featured_priority', desc=True) \
                .limit(limit) \
                .execute()
            
            return result.data
        except Exception as e:
            logger.error(f"Error getting featured networks: {e}")
            return []
    
    async def get_podcasts_by_category(
        self, 
        category_id: str, 
        limit: int = 20, 
        offset: int = 0,
        user_id: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get podcasts in a specific category from ListenNotes API using genre mapping"""
        try:
            # 1. Get ListenNotes genre ID for this category
            genre_result = self.supabase.table('category_genre') \
                .select('genre_id') \
                .eq('category_id', category_id) \
                .limit(1) \
                .execute()
            
            if not genre_result.data:
                logger.warning(f"No genre mapping found for category {category_id}")
                return [], 0
            
            genre_id = genre_result.data[0]['genre_id']
            logger.info(f"Using ListenNotes genre {genre_id} for category {category_id}")
            
            # 2. Search ListenNotes API for podcasts in this genre
            if not self.listennotes_api_key:
                logger.error("ListenNotes API key not configured")
                return [], 0
            
            async with httpx.AsyncClient() as client:
                headers = {
                    'X-ListenAPI-Key': self.listennotes_api_key
                }
                
                # Use best_podcasts endpoint with genre filter and date filter
                # earliest_pub_date_ms for Jan 1, 2021 00:00:00 UTC
                earliest_date_ms = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
                
                params = {
                    'genre_id': genre_id,
                    'page': (offset // limit) + 1,  # ListenNotes uses 1-based pagination
                    'region': 'us',
                    'safe_mode': 0,
                    'earliest_pub_date_ms': earliest_date_ms
                }
                
                response = await client.get(
                    f"{self.listennotes_base_url}/best_podcasts",
                    headers=headers,
                    params=params
                )
                
                if response.status_code != 200:
                    logger.error(f"ListenNotes API error: {response.status_code} - {response.text}")
                    return [], 0
                
                data = response.json()
                
                # 3. Transform ListenNotes results to our format
                podcasts = []
                for ln_podcast in data.get('podcasts', []):
                    # Check if first episode is after 2021-01-01
                    earliest_pub_date = ln_podcast.get('earliest_pub_date_ms', 0)
                    if earliest_pub_date < earliest_date_ms:
                        continue  # Skip podcasts with episodes before 2021
                    
                    podcast = {
                        'id': ln_podcast.get('id'),  # Use ListenNotes ID as temporary ID
                        'listennotes_id': ln_podcast.get('id'),
                        'title': ln_podcast.get('title'),
                        'description': ln_podcast.get('description'),
                        'publisher': ln_podcast.get('publisher'),
                        'language': ln_podcast.get('language', 'en'),
                        'image_url': ln_podcast.get('image'),
                        'thumbnail_url': ln_podcast.get('thumbnail'),
                        'rss_url': ln_podcast.get('rss'),
                        'total_episodes': ln_podcast.get('total_episodes', 0),
                        'explicit_content': ln_podcast.get('explicit_content', False),
                        'is_featured': False,  # ListenNotes results are not featured by default
                        'source': 'listennotes',
                        'created_at': datetime.now(timezone.utc).isoformat(),
                        'updated_at': datetime.now(timezone.utc).isoformat()
                    }
                    
                    # Add category information
                    try:
                        category_result = self.supabase.table('podcast_categories') \
                            .select('id, name, display_name, color') \
                            .eq('id', category_id) \
                            .single() \
                            .execute()
                        
                        if category_result.data:
                            podcast['categories'] = [category_result.data]
                        else:
                            podcast['categories'] = []
                    except Exception as e:
                        logger.warning(f"Could not fetch category details for {category_id}: {e}")
                        podcast['categories'] = []
                    
                    podcasts.append(podcast)
                
                # 4. Enrich each podcast with most recent episode
                enriched_podcasts = []
                for podcast in podcasts:
                    # Check if this podcast exists in our database first
                    listennotes_id = podcast.get('listennotes_id')
                    if listennotes_id:
                        # Try to get from our database first
                        try:
                            db_podcast = self.supabase.table('podcasts') \
                                .select('id, latest_episode_id') \
                                .eq('listennotes_id', listennotes_id) \
                                .single() \
                                .execute()
                            
                            if db_podcast.data and db_podcast.data.get('latest_episode_id'):
                                # Use our database episode
                                episode_result = self.supabase.table('episodes') \
                                    .select('id, listennotes_id, guid, title, description, audio_url, image_url, duration_seconds, explicit_content, published_at, created_at') \
                                    .eq('id', db_podcast.data['latest_episode_id']) \
                                    .single() \
                                    .execute()
                                
                                if episode_result.data:
                                    episode = episode_result.data
                                    if episode.get('published_at'):
                                        episode['pub_date'] = episode['published_at']
                                    else:
                                        episode['pub_date'] = episode.get('created_at')
                                    podcast['most_recent_episode'] = episode
                                    podcast['id'] = db_podcast.data['id']  # Use database ID
                                else:
                                    # Fallback to ListenNotes if episode not found
                                    recent_episode = await self._get_listennotes_latest_episode(listennotes_id)
                                    if recent_episode:
                                        podcast['most_recent_episode'] = recent_episode
                            else:
                                # Podcast not in database or no latest_episode_id, use ListenNotes
                                recent_episode = await self._get_listennotes_latest_episode(listennotes_id)
                                if recent_episode:
                                    podcast['most_recent_episode'] = recent_episode
                        except Exception as e:
                            logger.warning(f"Error checking database for podcast {listennotes_id}: {e}")
                            # Fallback to ListenNotes
                            recent_episode = await self._get_listennotes_latest_episode(listennotes_id)
                            if recent_episode:
                                podcast['most_recent_episode'] = recent_episode
                    
                    enriched_podcasts.append(podcast)
                
                # 5. Update claimed status for all podcasts
                await self._update_claimed_status_batch(enriched_podcasts)
                
                # 6. Update following status if user_id provided
                if user_id:
                    await self._update_following_status_batch(enriched_podcasts, user_id)
                else:
                    # Set following to false for all podcasts, except featured ones
                    for podcast in enriched_podcasts:
                        if podcast.get('is_featured'):
                            podcast['following'] = True
                        else:
                            podcast['following'] = False
                
                # 7. Calculate total count from API response
                total_count = data.get('total', len(enriched_podcasts))
                
                return enriched_podcasts, total_count
                
        except Exception as e:
            logger.error(f"Error getting podcasts by category from ListenNotes: {e}")
            return [], 0
    
    async def get_podcast_details(self, podcast_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get detailed podcast information with user-specific data from local database or ListenNotes API"""
        try:
            podcast = None
            
            # First try to get from local podcasts table by ID
            try:
                podcast_query = self.supabase.table('podcasts') \
                    .select('id, listennotes_id, rss_url, title, description, publisher, language, image_url, thumbnail_url, explicit_content, is_featured, created_at, updated_at') \
                    .eq('id', podcast_id) \
                    .single()
                
                podcast_result = podcast_query.execute()
                if podcast_result.data:
                    podcast = podcast_result.data
                    podcast['source'] = 'podcasts'
                    
                    # Get categories separately using the many-to-many relationship
                    try:
                        categories_result = self.supabase.table('podcast_category_mappings') \
                            .select('category:podcast_categories(id, name, display_name, color)') \
                            .eq('podcast_id', podcast_id) \
                            .execute()
                        
                        if categories_result.data:
                            podcast['categories'] = [mapping['category'] for mapping in categories_result.data]
                        else:
                            podcast['categories'] = []
                    except Exception as e:
                        logger.warning(f"Could not fetch categories for podcast {podcast_id}: {e}")
                        podcast['categories'] = []
                        
            except Exception as e:
                logger.warning(f"Podcast {podcast_id} not found by ID: {e}")
            
            # If not found by ID, try searching by listennotes_id
            if not podcast:
                try:
                    ln_query = self.supabase.table('podcasts') \
                        .select('id, listennotes_id, rss_url, title, description, publisher, language, image_url, thumbnail_url, explicit_content, is_featured, created_at, updated_at') \
                        .eq('listennotes_id', podcast_id) \
                        .single()
                    
                    ln_result = ln_query.execute()
                    if ln_result.data:
                        podcast = ln_result.data
                        podcast['source'] = 'podcasts'
                        
                        # Get categories for the found podcast
                        try:
                            categories_result = self.supabase.table('podcast_category_mappings') \
                                .select('category:podcast_categories(id, name, display_name, color)') \
                                .eq('podcast_id', podcast['id']) \
                                .execute()
                            
                            if categories_result.data:
                                podcast['categories'] = [mapping['category'] for mapping in categories_result.data]
                            else:
                                podcast['categories'] = []
                        except Exception as e:
                            logger.warning(f"Could not fetch categories for podcast {podcast['id']}: {e}")
                            podcast['categories'] = []
                            
                except Exception as e:
                    logger.warning(f"Podcast {podcast_id} not found by listennotes_id: {e}")
            
            # If not found locally at all, fetch from ListenNotes API
            if not podcast:
                logger.info(f"Fetching podcast {podcast_id} from ListenNotes API")
                podcast = await self._get_podcast_from_listennotes(podcast_id)
            
            if not podcast:
                logger.error(f"Podcast {podcast_id} not found in local database or ListenNotes")
                return None
            
            # If user is provided, get user-specific data
            if user_id:
                # For user-specific data, use the appropriate ID
                lookup_id = podcast.get('id')  # Use the table's primary key
                
                # Check if user follows this podcast
                follow_result = self.supabase.table('user_podcast_follows') \
                    .select('followed_at, notification_enabled') \
                    .eq('user_id', user_id) \
                    .eq('podcast_id', lookup_id) \
                    .execute()
                
                podcast['user_follows'] = len(follow_result.data) > 0
                if follow_result.data:
                    podcast['user_follow_details'] = follow_result.data[0]
                
                # Get user rating if exists
                rating_result = self.supabase.table('user_podcast_ratings') \
                    .select('rating, review_text') \
                    .eq('user_id', user_id) \
                    .eq('podcast_id', lookup_id) \
                    .execute()
                
                if rating_result.data:
                    podcast['user_rating'] = rating_result.data[0]
            
            # Enrich with most recent episode
            podcast = await self.enrich_podcast_with_recent_episode(podcast)
            
            # Add claimed status
            await self._update_claimed_status_batch([podcast])
            
            # Add following status
            if user_id:
                await self._update_following_status_batch([podcast], user_id)
            else:
                if podcast.get('is_featured'):
                    podcast['following'] = True
                else:
                    podcast['following'] = False
            
            return podcast
        except Exception as e:
            logger.error(f"Error getting podcast details: {e}")
            return None
    
    async def get_podcast_episodes(
        self,
        podcast_id: str,
        limit: int = 50,
        offset: int = 0,
        user_id: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get episodes for a podcast with pagination support, with configurable TTL-based refresh"""
        try:
            from datetime import datetime, timezone, timedelta

            
            # Check in-memory cache first for episode list
            cached_result = self.episode_cache.get_episodes_list(podcast_id, limit, offset)
            if cached_result:
                logger.debug(f"Returning episodes list from in-memory cache for podcast {podcast_id[:8]}...")
                episodes, total_count = cached_result
                # Still need to enrich with user data if provided
                if user_id and episodes:
                    # ... user enrichment logic would go here ...
                    pass
                return episodes, total_count

# Get podcast details to determine the correct table and IDs
            podcast_details = await self.get_podcast_details(podcast_id)
            if not podcast_details:
                logger.error(f"Cannot find podcast details for {podcast_id}")
                return [], 0

            # Determine the correct podcast ID to use for episode queries
            # If podcast is from ListenNotes and not in our DB, we need to handle it differently
            if podcast_details.get('source') == 'listennotes':
                # This podcast came from ListenNotes API and may not be in our DB
                # We need to use the actual database ID if it exists
                try:
                    db_check = self.supabase.table('podcasts') \
                        .select('id') \
                        .eq('listennotes_id', podcast_details.get('listennotes_id')) \
                        .execute()

                    if db_check.data and len(db_check.data) > 0:
                        episode_query_podcast_id = db_check.data[0]['id']
                    else:
                        # Podcast not in DB, need to import it first
                        episode_query_podcast_id = None
                except Exception as e:
                    logger.warning(f"Error checking for podcast in DB: {e}")
                    episode_query_podcast_id = None
            else:
                episode_query_podcast_id = podcast_details.get('id')

            # Check if we should refresh based on TTL configuration
            should_refresh = False

            # Check if caching is enabled (default: True)
            cache_enabled = os.getenv('ENABLE_LATEST_EPISODE_CACHE', 'true').lower() in ('true', '1', 'yes')

            if not cache_enabled:
                # Caching disabled, always refresh
                should_refresh = True
                logger.info(f"Episode cache is DISABLED, will refresh episodes for podcast {podcast_id}")
            else:
                # Check if episodes exist and their last update time
                episodes_exist = False
                if episode_query_podcast_id:
                    episodes_exist = await self._check_episodes_exist(episode_query_podcast_id)

                if not episodes_exist:
                    # No episodes exist, need to import
                    should_refresh = True
                    logger.info(f"No episodes exist for podcast {podcast_id}, will import")
                else:
                    # Episodes exist, check TTL
                    ttl_minutes = int(os.getenv('LATEST_EPISODE_TTL_MINUTES', '360'))

                    # Check when episodes were last updated
                    try:
                        latest_episode_updated_at = podcast_details.get('latest_episode_updated_at')

                        if latest_episode_updated_at:
                            updated_time = datetime.fromisoformat(latest_episode_updated_at.replace('Z', '+00:00'))
                            ttl_threshold = datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes)

                            if updated_time < ttl_threshold:
                                should_refresh = True
                                logger.info(f"Episodes cache expired for podcast {podcast_id} (TTL: {ttl_minutes} min), will refresh")
                            else:
                                logger.info(f"Episodes cache is fresh for podcast {podcast_id} (TTL: {ttl_minutes} min)")
                        else:
                            # No timestamp column available, refresh periodically based on in-memory cache
                            # This ensures episodes eventually refresh even without the database column
                            logger.debug(f"No episode update timestamp for podcast {podcast_id}, checking in-memory cache")
                            # If in-memory cache was empty (cache miss at line 808), trigger refresh
                            # This happens on first access or after cache expiry
                            should_refresh = True
                    except Exception as e:
                        logger.warning(f"Error checking episode TTL: {e}, using cached episodes")

            # Refresh episodes if needed
            if should_refresh:
                logger.info(f"Refreshing episodes from ListenNotes for podcast {podcast_id}")
                success = await self._import_episodes_on_demand(podcast_id)

                # After import/refresh, get the real database ID if we didn't have it
                if success and not episode_query_podcast_id:
                    try:
                        db_check = self.supabase.table('podcasts') \
                            .select('id') \
                            .eq('listennotes_id', podcast_details.get('listennotes_id')) \
                            .execute()
                        if db_check.data and len(db_check.data) > 0:
                            episode_query_podcast_id = db_check.data[0]['id']
                    except Exception as e:
                        logger.warning(f"Error getting podcast ID after import: {e}")
            
            # If we still don't have a valid podcast ID, return empty results
            if not episode_query_podcast_id:
                logger.error(f"No valid database podcast ID found for {podcast_id}")
                return [], 0
            
            # Base episode query using the correct podcast ID
            episodes_query = self.supabase.table('episodes') \
                .select('id, podcast_id, listennotes_id, guid, title, description, audio_url, image_url, duration_seconds, explicit_content, published_at, created_at, updated_at', count='exact') \
                .eq('podcast_id', episode_query_podcast_id) \
                .order('published_at', desc=True) \
                .range(offset, offset + limit - 1)
            
            episodes_result = episodes_query.execute()
            episodes = episodes_result.data
            total_count = episodes_result.count or 0

            # Cache the episodes list in memory (before user enrichment)
            self.episode_cache.set_episodes_list(podcast_id, limit, offset, episodes, total_count)

            # If we have fewer episodes than expected and user is requesting later pages,
            # try to import more episodes
            if total_count > 0 and offset >= total_count and total_count < 1000:
                logger.info(f"User requesting episodes beyond imported count ({offset} >= {total_count}), importing more episodes")
                success = await self._import_episodes_on_demand(podcast_id)
                if success:
                    # Re-query after importing more episodes
                    episodes_result = episodes_query.execute()
                    episodes = episodes_result.data
                    total_count = episodes_result.count or 0
                    # Update cache with new results
                    self.episode_cache.set_episodes_list(podcast_id, limit, offset, episodes, total_count)
            
            # If user provided, get progress and saves data
            if user_id and episodes:
                episode_ids = [ep['id'] for ep in episodes]
                
                # Get listening progress
                progress_result = self.supabase.table('user_listening_progress') \
                    .select('episode_id, progress_seconds, duration_seconds, progress_percentage, is_completed, playback_speed') \
                    .eq('user_id', user_id) \
                    .in_('episode_id', episode_ids) \
                    .execute()
                
                # Get saved episodes
                saves_result = self.supabase.table('user_episode_saves') \
                    .select('episode_id, saved_at, notes') \
                    .eq('user_id', user_id) \
                    .in_('episode_id', episode_ids) \
                    .execute()
                
                # Create lookup dictionaries
                progress_lookup = {p['episode_id']: p for p in progress_result.data}
                saves_lookup = {s['episode_id']: s for s in saves_result.data}
                
                # Enhance episodes with user data
                for episode in episodes:
                    episode_id = episode['id']
                    episode['user_progress'] = progress_lookup.get(episode_id)
                    episode['user_saved'] = saves_lookup.get(episode_id)
                    episode['is_saved'] = episode_id in saves_lookup
            
            return episodes, total_count
        except Exception as e:
            logger.error(f"Error getting podcast episodes: {e}")
            return [], 0
    
    async def search_podcasts(
        self, 
        query: str, 
        category_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
        user_id: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Search podcasts from podcasts table"""
        try:
            # Search in podcasts table
            try:
                # If searching by category, get podcast IDs first
                podcast_ids_filter = None
                if category_id:
                    mappings_result = self.supabase.table('podcast_category_mappings') \
                        .select('podcast_id') \
                        .eq('category_id', category_id) \
                        .execute()
                    
                    if mappings_result.data:
                        podcast_ids_filter = [mapping['podcast_id'] for mapping in mappings_result.data]
                    else:
                        # No podcasts in this category
                        podcasts_result = type('obj', (object,), {'data': []})()  # Empty result
                        podcast_ids_filter = []
                
                if category_id and not podcast_ids_filter:
                    # No podcasts found for this category
                    podcasts_result = type('obj', (object,), {'data': []})()  # Empty result
                else:
                    podcasts_query = self.supabase.table('podcasts') \
                        .select('id, listennotes_id, rss_url, title, description, publisher, language, image_url, thumbnail_url, explicit_content, is_featured, created_at, updated_at')
                    
                    if query:
                        # Format query for PostgreSQL full-text search
                        # Replace spaces with & to search for all words
                        formatted_query = ' & '.join(query.split())
                        try:
                            # Use PostgreSQL full-text search on podcasts table
                            podcasts_query = podcasts_query.text_search('search_vector', formatted_query)
                        except Exception as e:
                            logger.warning(f"Full-text search failed with query '{formatted_query}', falling back to title search: {e}")
                            # Fallback to title search using ilike
                            podcasts_query = podcasts_query.ilike('title', f'%{query}%')
                    
                    if podcast_ids_filter:
                        podcasts_query = podcasts_query.in_('id', podcast_ids_filter)
                    
                    # Execute the query
                    podcasts_result = podcasts_query.execute()
                    
                    # Add category information to each podcast
                    if podcasts_result.data:
                        for podcast in podcasts_result.data:
                            try:
                                categories_result = self.supabase.table('podcast_category_mappings') \
                                    .select('category:podcast_categories(id, name, display_name, color)') \
                                    .eq('podcast_id', podcast['id']) \
                                    .execute()
                                
                                if categories_result.data:
                                    podcast['categories'] = [mapping['category'] for mapping in categories_result.data]
                                else:
                                    podcast['categories'] = []
                            except Exception as e:
                                logger.warning(f"Could not fetch categories for podcast {podcast['id']}: {e}")
                                podcast['categories'] = []
                
            except Exception as e:
                logger.error(f"Error searching podcasts table: {e}")
                podcasts_result = type('obj', (object,), {'data': []})()  # Empty result
            
            # Process local results
            local_podcasts = podcasts_result.data or []
            
            # Apply exact/fuzzy matching to local results if we have a query
            if local_podcasts and query:
                exact_matches = []
                fuzzy_matches = []
                query_lower = query.lower()
                query_words = set(query_lower.split())
                
                for podcast in local_podcasts:
                    title = podcast.get('title', '').lower()
                    title_words = set(title.split())
                    
                    # Exact match (case-insensitive)
                    if title == query_lower:
                        exact_matches.append(podcast)
                    # All query words present in title
                    elif query_words.issubset(title_words):
                        fuzzy_matches.append(podcast)
                
                # Prioritize exact matches, then fuzzy matches
                if exact_matches:
                    local_podcasts = exact_matches
                    logger.info(f"Found {len(exact_matches)} exact local matches")
                elif fuzzy_matches:
                    local_podcasts = fuzzy_matches
                    logger.info(f"Found {len(fuzzy_matches)} fuzzy local matches")
                else:
                    # No good matches in local results
                    local_podcasts = []
                    logger.info(f"No exact or fuzzy matches found in local results")
            
            # If no local results found and we have a query, search ListenNotes API
            listennotes_podcasts = []
            if not local_podcasts and query and self.listennotes_api_key:
                logger.info(f"No local results for '{query}', searching ListenNotes API...")
                listennotes_podcasts = await self._search_listennotes_api(query, limit)
                
                # Filter ListenNotes results for exact or close matches
                if listennotes_podcasts:
                    exact_matches = []
                    fuzzy_matches = []
                    query_lower = query.lower()
                    query_words = set(query_lower.split())
                    
                    for podcast in listennotes_podcasts:
                        title = podcast.get('title', '').lower()
                        title_words = set(title.split())
                        
                        # Exact match (case-insensitive)
                        if title == query_lower:
                            exact_matches.append(podcast)
                        # All query words present in title
                        elif query_words.issubset(title_words):
                            fuzzy_matches.append(podcast)
                    
                    # Prioritize exact matches, then fuzzy matches
                    if exact_matches:
                        listennotes_podcasts = exact_matches
                        logger.info(f"Found {len(exact_matches)} exact matches from ListenNotes")
                    elif fuzzy_matches:
                        listennotes_podcasts = fuzzy_matches
                        logger.info(f"Found {len(fuzzy_matches)} fuzzy matches from ListenNotes")
                    else:
                        # No good matches, return empty
                        listennotes_podcasts = []
                        logger.info(f"No exact or fuzzy matches found in ListenNotes results")
            
            # Combine results: local first, then ListenNotes
            all_podcasts = local_podcasts + listennotes_podcasts
            
            # Sort results: featured podcasts first, then by source (local first), then alphabetically
            all_podcasts.sort(key=lambda p: (
                -(1 if p.get('is_featured') else 0),  # Featured podcasts first
                -(1 if p.get('source') != 'listennotes' else 0),  # Local podcasts before ListenNotes
                p.get('title', '').lower()            # Then alphabetically by title
            ))
            
            # Apply pagination
            total_count = len(all_podcasts)
            paginated_podcasts = all_podcasts[offset:offset + limit]
            
            # Enrich each podcast with most recent episode
            enriched_podcasts = []
            for podcast in paginated_podcasts:
                # Skip episode enrichment for ListenNotes results that aren't in our database
                if podcast.get('source') == 'listennotes':
                    # For ListenNotes results, try to get latest episode from API
                    listennotes_id = podcast.get('listennotes_id')
                    if listennotes_id:
                        try:
                            latest_episode = await self._get_listennotes_latest_episode(listennotes_id)
                            if latest_episode:
                                podcast['most_recent_episode'] = latest_episode
                        except Exception as e:
                            logger.debug(f"Could not get latest episode for ListenNotes podcast {listennotes_id}: {e}")
                    enriched_podcasts.append(podcast)
                else:
                    # For local podcasts, use normal enrichment
                    enriched = await self.enrich_podcast_with_recent_episode(podcast)
                    enriched_podcasts.append(enriched)
            
            # Update claimed status for all podcasts
            await self._update_claimed_status_batch(enriched_podcasts)
            
            # Update following status if user_id provided
            if user_id:
                await self._update_following_status_batch(enriched_podcasts, user_id)
            else:
                # Set following to false for all podcasts, except featured ones
                for podcast in enriched_podcasts:
                    if podcast.get('is_featured'):
                        podcast['following'] = True
                    else:
                        podcast['following'] = False
            
            return enriched_podcasts, total_count
            
        except Exception as e:
            logger.error(f"Error searching podcasts: {e}")
            return [], 0
    
    async def search_episodes(
        self, 
        query: str, 
        podcast_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Search episodes using full-text search"""
        try:
            search_query = self.supabase.table('episodes') \
                .select('id, podcast_id, listennotes_id, guid, title, description, audio_url, image_url, duration_seconds, explicit_content, published_at, created_at, updated_at, podcast:podcasts!episodes_podcast_id_fkey(title, publisher, image_url)', count='exact')
            
            if query:
                # Format query for PostgreSQL full-text search
                formatted_query = ' & '.join(query.split())
                # For now, just use ilike for episode search until we fix the search_vector
                search_query = search_query.ilike('title', f'%{query}%')
            
            if podcast_id:
                search_query = search_query.eq('podcast_id', podcast_id)
            
            result = search_query \
                .order('published_at', desc=True) \
                .range(offset, offset + limit - 1) \
                .execute()
            
            total_count = result.count or 0
            return result.data, total_count
        except Exception as e:
            logger.error(f"Error searching episodes: {e}")
            return [], 0
    
    async def import_podcast_from_listennotes(self, listennotes_id: str) -> Optional[Dict[str, Any]]:
        """Import a podcast from ListenNotes API"""
        if not self.listennotes_api_key:
            logger.error("ListenNotes API key not configured")
            return None
        
        try:
            async with httpx.AsyncClient() as client:
                headers = {
                    'X-ListenAPI-Key': self.listennotes_api_key
                }
                
                # Get podcast details
                response = await client.get(
                    f"{self.listennotes_base_url}/podcasts/{listennotes_id}",
                    headers=headers
                )
                
                if response.status_code != 200:
                    logger.error(f"ListenNotes API error: {response.status_code}")
                    return None
                
                podcast_data = response.json()
                
                # Transform to our schema
                podcast_record = {
                    'listennotes_id': listennotes_id,
                    'title': podcast_data.get('title'),
                    'description': podcast_data.get('description'),
                    'publisher': podcast_data.get('publisher'),
                    'language': podcast_data.get('language', 'en'),
                    'image_url': podcast_data.get('image'),
                    'thumbnail_url': podcast_data.get('thumbnail'),
                    'rss_url': podcast_data.get('rss'),
                    'total_episodes': podcast_data.get('total_episodes', 0),
                    'explicit_content': podcast_data.get('explicit_content', False),
                    'last_episode_date': podcast_data.get('latest_episode_pub_date_ms'),
                }
                
                # Store categories for later mapping (removed category_id from podcast_record)
                listennotes_categories = []
                if 'categories' in podcast_data and podcast_data['categories']:
                    for cat in podcast_data['categories']:
                        category_name = cat.get('name', '').lower()
                        category_result = self.supabase.table('podcast_categories') \
                            .select('id') \
                            .ilike('name', f'%{category_name}%') \
                            .limit(1) \
                            .execute()
                        
                        if category_result.data:
                            listennotes_categories.append(category_result.data[0]['id'])
                
                # Insert podcast
                result = self.supabase.table('podcasts') \
                    .insert(podcast_record) \
                    .execute()
                
                if result.data:
                    podcast_id = result.data[0]['id']
                    logger.info(f"Successfully imported podcast: {podcast_record['title']}")
                    
                    # Add category mappings if we found any
                    if listennotes_categories:
                        await self.set_podcast_categories(podcast_id, listennotes_categories)
                        logger.info(f"Added {len(listennotes_categories)} categories to imported podcast")
                    
                    return result.data[0]
                
        except Exception as e:
            logger.error(f"Error importing podcast from ListenNotes: {e}")
            return None
    
    async def get_trending_podcasts(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get trending podcasts based on recent activity and scores"""
        try:
            result = self.supabase.table('podcasts') \
                .select('*') \
                .order('listen_score', desc=True) \
                .order('follower_count', desc=True) \
                .order('last_episode_date', desc=True) \
                .limit(limit) \
                .execute()
            
            # Enrich each podcast with most recent episode
            enriched_podcasts = []
            for podcast in result.data or []:
                enriched = await self.enrich_podcast_with_recent_episode(podcast)
                enriched_podcasts.append(enriched)
            
            return enriched_podcasts
        except Exception as e:
            logger.error(f"Error getting trending podcasts: {e}")
            return []
    
    async def _check_episodes_exist(self, podcast_id: str) -> bool:
        """Check if episodes already exist for a podcast"""
        try:
            # Get episode import service
            episode_service = get_episode_import_service(self.supabase, self.listennotes_api_key)
            return await episode_service.check_episodes_exist(podcast_id)
        except Exception as e:
            logger.error(f"Error checking if episodes exist: {e}")
            return False
    
    async def _import_episodes_on_demand(self, podcast_id: str) -> bool:
        """Import episodes on-demand from ListenNotes API"""
        try:
            # First, get the podcast details to find the ListenNotes ID
            podcast_details = await self.get_podcast_details(podcast_id)
            if not podcast_details:
                logger.error(f"Cannot find podcast details for {podcast_id}")
                return False
            
            listennotes_id = podcast_details.get('listennotes_id') or podcast_details.get('podcast_id')
            if not listennotes_id:
                logger.error(f"No ListenNotes ID found for podcast {podcast_id}")
                return False
            
            # If this podcast is from ListenNotes or featured_podcasts, we need to ensure 
            # it exists in the main podcasts table for episode imports
            main_table_podcast_id = podcast_id
            
            if podcast_details.get('source') in ['listennotes', 'featured_podcasts']:
                logger.info(f"{podcast_details.get('source')} podcast detected, ensuring it exists in main podcasts table")
                
                # Check if it already exists in main podcasts table by listennotes_id
                existing_main = self.supabase.table('podcasts') \
                    .select('id') \
                    .eq('listennotes_id', listennotes_id) \
                    .execute()
                
                if existing_main.data:
                    # Use the existing main table podcast ID
                    main_table_podcast_id = existing_main.data[0]['id']
                    logger.info(f"Found existing podcast in main table with ID: {main_table_podcast_id}")
                else:
                    # Import the featured podcast into main table
                    logger.info(f"Importing featured podcast into main table")
                    imported_podcast = await self.import_podcast_from_listennotes(listennotes_id)
                    
                    if imported_podcast:
                        main_table_podcast_id = imported_podcast['id']
                        logger.info(f"Successfully imported featured podcast to main table with ID: {main_table_podcast_id}")
                    else:
                        logger.error(f"Failed to import featured podcast to main table")
                        return False
            
            # Get episode import service
            episode_service = get_episode_import_service(self.supabase, self.listennotes_api_key)
            
            # Import recent episodes using the main table podcast ID
            # Import more episodes to support pagination (up to 100 episodes)
            imported_episodes = await episode_service.import_recent_episodes(
                podcast_id=main_table_podcast_id,
                listennotes_id=listennotes_id,
                limit=100
            )
            
            if imported_episodes:
                logger.info(f"Successfully imported {len(imported_episodes)} episodes for podcast {main_table_podcast_id}")
                
                # Explicitly update the latest_episode_id after episode import
                # This ensures the latest episode is correctly set even if triggers didn't fire properly
                try:
                    await self.update_podcast_latest_episode_id(main_table_podcast_id)
                    logger.info(f"Updated latest_episode_id for podcast {main_table_podcast_id} after episode import")
                except Exception as e:
                    logger.warning(f"Failed to update latest_episode_id after episode import: {e}")
                
                return True
            else:
                logger.warning(f"No episodes imported for podcast {main_table_podcast_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error importing episodes on-demand: {e}")
            return False
    
    # PODCAST-CATEGORY RELATIONSHIP MANAGEMENT
    
    async def add_podcast_to_category(self, podcast_id: str, category_id: str) -> bool:
        """Add a podcast to a category using the many-to-many relationship"""
        try:
            # Check if mapping already exists
            existing = self.supabase.table('podcast_category_mappings') \
                .select('id') \
                .eq('podcast_id', podcast_id) \
                .eq('category_id', category_id) \
                .execute()
            
            if existing.data:
                logger.info(f"Podcast {podcast_id} already in category {category_id}")
                return True
            
            # Create new mapping
            result = self.supabase.table('podcast_category_mappings') \
                .insert({
                    'podcast_id': podcast_id,
                    'category_id': category_id
                }) \
                .execute()
            
            if result.data:
                logger.info(f"Added podcast {podcast_id} to category {category_id}")
                return True
            
            return False
        except Exception as e:
            logger.error(f"Error adding podcast to category: {e}")
            return False
    
    async def remove_podcast_from_category(self, podcast_id: str, category_id: str) -> bool:
        """Remove a podcast from a category"""
        try:
            result = self.supabase.table('podcast_category_mappings') \
                .delete() \
                .eq('podcast_id', podcast_id) \
                .eq('category_id', category_id) \
                .execute()
            
            logger.info(f"Removed podcast {podcast_id} from category {category_id}")
            return True
        except Exception as e:
            logger.error(f"Error removing podcast from category: {e}")
            return False
    
    async def set_podcast_categories(self, podcast_id: str, category_ids: List[str]) -> bool:
        """Set all categories for a podcast (replaces existing categories)"""
        try:
            # Remove all existing mappings for this podcast
            self.supabase.table('podcast_category_mappings') \
                .delete() \
                .eq('podcast_id', podcast_id) \
                .execute()
            
            # Add new mappings
            if category_ids:
                mappings = [
                    {'podcast_id': podcast_id, 'category_id': category_id}
                    for category_id in category_ids
                ]
                
                result = self.supabase.table('podcast_category_mappings') \
                    .insert(mappings) \
                    .execute()
                
                if result.data:
                    logger.info(f"Set {len(category_ids)} categories for podcast {podcast_id}")
                    return True
            else:
                logger.info(f"Cleared all categories for podcast {podcast_id}")
                return True
            
            return False
        except Exception as e:
            logger.error(f"Error setting podcast categories: {e}")
            return False
    
    async def get_podcast_categories(self, podcast_id: str) -> List[Dict[str, Any]]:
        """Get all categories for a podcast"""
        try:
            result = self.supabase.table('podcast_category_mappings') \
                .select('category:podcast_categories(id, name, display_name, color)') \
                .eq('podcast_id', podcast_id) \
                .execute()
            
            if result.data:
                return [mapping['category'] for mapping in result.data]
            return []
        except Exception as e:
            logger.error(f"Error getting podcast categories: {e}")
            return []
    
    # FEATURED PODCAST-CATEGORY RELATIONSHIP MANAGEMENT
    
    async def add_featured_podcast_to_category(self, featured_podcast_id: str, category_id: str) -> bool:
        """Add a featured podcast to a category using the many-to-many relationship"""
        try:
            # Check if mapping already exists
            existing = self.supabase.table('featured_podcast_category_mappings') \
                .select('id') \
                .eq('featured_podcast_id', featured_podcast_id) \
                .eq('category_id', category_id) \
                .execute()
            
            if existing.data:
                logger.info(f"Featured podcast {featured_podcast_id} already in category {category_id}")
                return True
            
            # Create new mapping
            result = self.supabase.table('featured_podcast_category_mappings') \
                .insert({
                    'featured_podcast_id': featured_podcast_id,
                    'category_id': category_id
                }) \
                .execute()
            
            if result.data:
                logger.info(f"Added featured podcast {featured_podcast_id} to category {category_id}")
                return True
            
            return False
        except Exception as e:
            logger.error(f"Error adding featured podcast to category: {e}")
            return False
    
    async def remove_featured_podcast_from_category(self, featured_podcast_id: str, category_id: str) -> bool:
        """Remove a featured podcast from a category"""
        try:
            result = self.supabase.table('featured_podcast_category_mappings') \
                .delete() \
                .eq('featured_podcast_id', featured_podcast_id) \
                .eq('category_id', category_id) \
                .execute()
            
            logger.info(f"Removed featured podcast {featured_podcast_id} from category {category_id}")
            return True
        except Exception as e:
            logger.error(f"Error removing featured podcast from category: {e}")
            return False
    
    async def set_featured_podcast_categories(self, featured_podcast_id: str, category_ids: List[str]) -> bool:
        """Set all categories for a featured podcast (replaces existing categories)"""
        try:
            # Remove all existing mappings for this featured podcast
            self.supabase.table('featured_podcast_category_mappings') \
                .delete() \
                .eq('featured_podcast_id', featured_podcast_id) \
                .execute()
            
            # Add new mappings
            if category_ids:
                mappings = [
                    {'featured_podcast_id': featured_podcast_id, 'category_id': category_id}
                    for category_id in category_ids
                ]
                
                result = self.supabase.table('featured_podcast_category_mappings') \
                    .insert(mappings) \
                    .execute()
                
                if result.data:
                    logger.info(f"Set {len(category_ids)} categories for featured podcast {featured_podcast_id}")
                    return True
            else:
                logger.info(f"Cleared all categories for featured podcast {featured_podcast_id}")
                return True
            
            return False
        except Exception as e:
            logger.error(f"Error setting featured podcast categories: {e}")
            return False
    
    async def get_featured_podcast_categories(self, featured_podcast_id: str) -> List[Dict[str, Any]]:
        """Get all categories for a featured podcast"""
        try:
            result = self.supabase.table('featured_podcast_category_mappings') \
                .select('category:podcast_categories(id, name, display_name, color)') \
                .eq('featured_podcast_id', featured_podcast_id) \
                .execute()
            
            if result.data:
                return [mapping['category'] for mapping in result.data]
            return []
        except Exception as e:
            logger.error(f"Error getting featured podcast categories: {e}")
            return []
    
    async def _is_podcast_claimed(self, listennotes_id: str) -> bool:
        """Check if a podcast has been claimed by a user"""
        try:
            result = self.supabase.table('podcast_claims') \
                .select('id') \
                .eq('listennotes_id', listennotes_id) \
                .eq('is_verified', True) \
                .eq('claim_status', 'verified') \
                .single() \
                .execute()
            
            return bool(result.data)
        except Exception:
            return False
    
    async def _update_claimed_status_batch(self, podcasts: List[Dict[str, Any]]) -> None:
        """Update claimed status for a batch of podcasts"""
        try:
            # Extract all listennotes IDs
            listennotes_ids = [p['listennotes_id'] for p in podcasts if 'listennotes_id' in p]
            
            if not listennotes_ids:
                return
            
            # Query claimed podcasts in batch
            result = self.supabase.table('podcast_claims') \
                .select('listennotes_id') \
                .in_('listennotes_id', listennotes_ids) \
                .eq('is_verified', True) \
                .eq('claim_status', 'verified') \
                .execute()
            
            # Create set of claimed IDs
            claimed_ids = {p['listennotes_id'] for p in (result.data or [])}
            
            # Update claimed status in the podcast list
            for podcast in podcasts:
                if 'listennotes_id' in podcast:
                    podcast['claimed'] = podcast['listennotes_id'] in claimed_ids
                    
        except Exception as e:
            logger.error(f"Error updating claimed status batch: {e}")
    
    async def _update_following_status_batch(self, podcasts: List[Dict[str, Any]], user_id: str) -> None:
        """Update following status for a batch of podcasts for a specific user"""
        try:
            # Extract all podcast IDs (use internal UUID, not listennotes_id)
            podcast_ids = [p['id'] for p in podcasts if 'id' in p]
            
            if not podcast_ids:
                return
            
            # Query user follows for these podcasts
            follows_result = self.supabase.table('user_podcast_follows') \
                .select('podcast_id') \
                .eq('user_id', user_id) \
                .in_('podcast_id', podcast_ids) \
                .execute()
            
            # Create set of followed podcast IDs
            followed_podcast_ids = {f['podcast_id'] for f in (follows_result.data or [])}
            
            # Update following status in the podcast list
            for podcast in podcasts:
                if 'id' in podcast:
                    # Featured podcasts should always show as following
                    if podcast.get('is_featured'):
                        podcast['following'] = True
                    else:
                        podcast['following'] = podcast['id'] in followed_podcast_ids
                    
        except Exception as e:
            logger.error(f"Error updating following status batch: {e}")
            # Set all to false on error, except featured podcasts
            for podcast in podcasts:
                if podcast.get('is_featured'):
                    podcast['following'] = True
                else:
                    podcast['following'] = False
    
    async def get_user_favorite_podcasts(self, user_id: str) -> List[Dict[str, Any]]:
        """Get user's favorite podcasts from user_podcast_follows table with recent episode info"""
        try:
            # Get user's followed podcasts
            follows_result = self.supabase.table('user_podcast_follows') \
                .select('podcast_id, followed_at, notification_enabled') \
                .eq('user_id', user_id) \
                .order('followed_at') \
                .execute()
            
            if not follows_result.data:
                return []
            
            # Get podcast details for each followed podcast
            podcast_ids = [follow['podcast_id'] for follow in follows_result.data]
            
            # First try to get from podcasts table
            podcasts_result = self.supabase.table('podcasts') \
                .select('*') \
                .in_('id', podcast_ids) \
                .execute()
            
            podcasts_by_id = {p['id']: p for p in podcasts_result.data or []}
            
            # Also check featured_podcasts table for any missing podcasts
            missing_ids = [pid for pid in podcast_ids if pid not in podcasts_by_id]
            if missing_ids:
                featured_result = self.supabase.table('featured_podcasts') \
                    .select('*') \
                    .in_('id', missing_ids) \
                    .execute()
                
                # Normalize featured podcasts to match podcasts table structure
                for featured in featured_result.data or []:
                    normalized = {
                        'id': featured['id'],
                        'podcast_id': featured['podcast_id'],
                        'listennotes_id': featured['podcast_id'],
                        'title': featured['title'],
                        'description': featured['description'],
                        'publisher': featured['publisher'],
                        'image_url': featured['image_url'],
                        'thumbnail_url': featured.get('image_url'),
                        'total_episodes': featured.get('total_episodes', 0),
                        'explicit_content': featured.get('explicit_content', False),
                        'is_featured': True,
                        'featured_priority': featured.get('priority', 0),
                        'source': 'featured_podcasts'
                    }
                    podcasts_by_id[featured['id']] = normalized
            
            # Build the response with user follow data and recent episodes
            favorite_podcasts = []
            for follow in follows_result.data:
                podcast_id = follow['podcast_id']
                podcast = podcasts_by_id.get(podcast_id)
                
                if podcast:
                    # Add user follow information
                    podcast['followed_at'] = follow['followed_at']
                    podcast['notification_enabled'] = follow['notification_enabled']
                    
                    # Enrich with most recent episode
                    enriched_podcast = await self.enrich_podcast_with_recent_episode(podcast)
                    favorite_podcasts.append(enriched_podcast)
                else:
                    logger.warning(f"Podcast {podcast_id} not found in either podcasts or featured_podcasts tables")
            
            return favorite_podcasts
            
        except Exception as e:
            logger.error(f"Error getting user favorite podcasts: {e}")
            return []
    
    async def get_all_podcasts_with_claims(self, limit: int = 100, offset: int = 0, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all podcasts from both tables with featured status and claim information"""
        try:
            all_podcasts = []
            
            # Get regular podcasts with claim information
            regular_podcasts_result = self.supabase.table('podcasts') \
                .select('*') \
                .range(offset, offset + limit - 1) \
                .execute()
            
            for podcast in regular_podcasts_result.data or []:
                # Get claim information for this podcast using listennotes_id
                claimed_by_name = None
                try:
                    listennotes_id = podcast.get('listennotes_id')
                    if listennotes_id:
                        claims_result = self.supabase.table('podcast_claims') \
                            .select('user_id, is_verified, claim_status') \
                            .eq('listennotes_id', listennotes_id) \
                            .eq('is_verified', True) \
                            .execute()
                        
                        if claims_result.data:
                            # Get user info for the claimant
                            user_id = claims_result.data[0]['user_id']
                            
                            # Try to get user profile for name
                            profile_result = self.supabase.table('user_profiles') \
                                .select('first_name, last_name, display_name') \
                                .eq('user_id', user_id) \
                                .execute()
                            
                            if profile_result.data:
                                profile = profile_result.data[0]
                                if profile.get('display_name'):
                                    claimed_by_name = profile['display_name']
                                elif profile.get('first_name') and profile.get('last_name'):
                                    claimed_by_name = f"{profile['first_name']} {profile['last_name']}"
                                elif profile.get('first_name'):
                                    claimed_by_name = profile['first_name']
                            
                            # Fallback to user ID if no name found
                            if not claimed_by_name:
                                claimed_by_name = f"User {user_id[:8]}"
                        else:
                            claimed_by_name = "Unclaimed"
                    else:
                        claimed_by_name = "No ListenNotes ID"
                        
                except Exception as e:
                    logger.warning(f"Error getting claim info for podcast {podcast['id']}: {e}")
                    claimed_by_name = "Claim lookup failed"
                
                all_podcasts.append({
                    "id": podcast['id'],
                    "name": podcast['title'],
                    "is_featured": podcast.get('is_featured', False),
                    "claimed": claimed_by_name not in ["Unclaimed", "No ListenNotes ID", "Claim lookup failed"],
                    "claimed_by": claimed_by_name,
                    "source": "podcasts",
                    "listennotes_id": podcast.get('listennotes_id'),
                    "publisher": podcast.get('publisher'),
                    "image_url": podcast.get('image_url'),
                    "thumbnail_url": podcast.get('thumbnail_url'),
                    "created_at": format_datetime_central(podcast.get('created_at'))
                })
            
            # Get featured podcasts
            featured_podcasts_result = self.supabase.table('featured_podcasts') \
                .select('*') \
                .range(offset, offset + limit - 1) \
                .execute()
            
            for podcast in featured_podcasts_result.data or []:
                all_podcasts.append({
                    "id": podcast['id'],
                    "name": podcast['title'],
                    "is_featured": True,
                    "claimed": False,  # Featured podcasts are not claimed by users
                    "claimed_by": None,  # Featured podcasts are not claimed by users
                    "source": "featured_podcasts",
                    "listennotes_id": podcast.get('podcast_id'),
                    "publisher": podcast.get('publisher'),
                    "image_url": podcast.get('image_url'),
                    "thumbnail_url": podcast.get('image_url'),  # Featured podcasts use same URL for both
                    "created_at": format_datetime_central(podcast.get('created_at'))
                })
            
            # Deduplicate podcasts based on listennotes_id
            # Prefer regular podcasts over featured ones because:
            # 1. They may have claim information
            # 2. They're in the main table which is the source of truth
            # 3. Featured status can still be determined from the 'is_featured' field
            seen_listennotes_ids = {}
            deduplicated_podcasts = []
            
            for podcast in all_podcasts:
                ln_id = podcast.get('listennotes_id')
                
                # If no listennotes_id, always include (can't deduplicate)
                if not ln_id:
                    deduplicated_podcasts.append(podcast)
                    continue
                
                # If we haven't seen this listennotes_id before, add it
                if ln_id not in seen_listennotes_ids:
                    seen_listennotes_ids[ln_id] = podcast
                    deduplicated_podcasts.append(podcast)
                else:
                    # We've seen this before - keep the one from 'podcasts' table if available
                    existing = seen_listennotes_ids[ln_id]
                    if existing['source'] == 'featured_podcasts' and podcast['source'] == 'podcasts':
                        # Replace with the regular podcast version (has claim info)
                        deduplicated_podcasts.remove(existing)
                        deduplicated_podcasts.append(podcast)
                        seen_listennotes_ids[ln_id] = podcast
            
            # Sort by name
            deduplicated_podcasts.sort(key=lambda x: x['name'].lower() if x['name'] else '')
            
            # Enrich each podcast with most recent episode
            enriched_podcasts = []
            for podcast in deduplicated_podcasts:
                # Create a proper podcast object for enrichment
                # Use the internal database ID for episode lookup, not the ListenNotes ID
                podcast_obj = {
                    'id': podcast['id'],  # This is the internal database UUID
                    'title': podcast['name'],
                    'publisher': podcast.get('publisher'),
                    'image_url': podcast.get('image_url'),
                    'thumbnail_url': podcast.get('thumbnail_url'),
                    'created_at': podcast.get('created_at'),
                    'is_featured': podcast['is_featured'],
                    'claimed': podcast['claimed'],  # Add the claimed boolean field
                    'claimed_by': podcast['claimed_by'],
                    'source': podcast['source'],
                    'listennotes_id': podcast.get('listennotes_id'),
                    'podcast_id': podcast.get('listennotes_id')  # Keep this for compatibility
                }
                enriched = await self.enrich_podcast_with_recent_episode(podcast_obj)
                enriched_podcasts.append(enriched)
            
            # Update following status if user_id provided
            if user_id:
                await self._update_following_status_batch(enriched_podcasts, user_id)
            else:
                # Set following to false for all podcasts, except featured ones
                for podcast in enriched_podcasts:
                    if podcast.get('is_featured'):
                        podcast['following'] = True
                    else:
                        podcast['following'] = False
            
            return enriched_podcasts
            
        except Exception as e:
            logger.error(f"Error getting all podcasts with claims: {e}")
            return []
    
    async def _get_listennotes_latest_episode(self, listennotes_id: str) -> Optional[Dict[str, Any]]:
        """Get the latest episode for a podcast from ListenNotes API"""
        try:
            if not self.listennotes_api_key:
                return None
            
            async with httpx.AsyncClient() as client:
                headers = {
                    'X-ListenAPI-Key': self.listennotes_api_key
                }
                
                # Get podcast details which includes latest episode
                response = await client.get(
                    f"{self.listennotes_base_url}/podcasts/{listennotes_id}",
                    headers=headers,
                    params={'sort': 'recent_first'}
                )
                
                if response.status_code != 200:
                    logger.warning(f"Failed to get episodes for podcast {listennotes_id}: {response.status_code}")
                    return None
                
                data = response.json()
                episodes = data.get('episodes', [])
                
                if episodes:
                    latest_episode = episodes[0]
                    return {
                        'id': latest_episode.get('id'),
                        'listennotes_id': latest_episode.get('id'),
                        'title': latest_episode.get('title'),
                        'description': latest_episode.get('description'),
                        'audio_url': latest_episode.get('audio'),
                        'image_url': latest_episode.get('image'),
                        'duration_seconds': latest_episode.get('audio_length_sec'),
                        'explicit_content': latest_episode.get('explicit_content', False),
                        'published_at': datetime.fromtimestamp(
                            latest_episode.get('pub_date_ms', 0) / 1000, 
                            tz=timezone.utc
                        ).isoformat() if latest_episode.get('pub_date_ms') else None,
                        'pub_date': datetime.fromtimestamp(
                            latest_episode.get('pub_date_ms', 0) / 1000, 
                            tz=timezone.utc
                        ).isoformat() if latest_episode.get('pub_date_ms') else None
                    }
                
                return None
                
        except Exception as e:
            logger.error(f"Error getting latest episode from ListenNotes: {e}")
            return None
    
    async def _get_podcast_from_listennotes(self, listennotes_id: str) -> Optional[Dict[str, Any]]:
        """Get podcast details from ListenNotes API"""
        try:
            if not self.listennotes_api_key:
                logger.error("ListenNotes API key not configured")
                return None
            
            async with httpx.AsyncClient() as client:
                headers = {
                    'X-ListenAPI-Key': self.listennotes_api_key
                }
                
                response = await client.get(
                    f"{self.listennotes_base_url}/podcasts/{listennotes_id}",
                    headers=headers
                )
                
                if response.status_code != 200:
                    logger.error(f"ListenNotes API error: {response.status_code} - {response.text}")
                    return None
                
                ln_podcast = response.json()
                
                # Transform to our format
                podcast = {
                    'id': listennotes_id,  # Use ListenNotes ID as the ID for consistency
                    'listennotes_id': listennotes_id,
                    'title': ln_podcast.get('title'),
                    'description': ln_podcast.get('description'),
                    'publisher': ln_podcast.get('publisher'),
                    'language': ln_podcast.get('language', 'en'),
                    'image_url': ln_podcast.get('image'),
                    'thumbnail_url': ln_podcast.get('thumbnail'),
                    'rss_url': ln_podcast.get('rss'),
                    'total_episodes': ln_podcast.get('total_episodes', 0),
                    'explicit_content': ln_podcast.get('explicit_content', False),
                    'is_featured': False,
                    'source': 'listennotes',
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'updated_at': datetime.now(timezone.utc).isoformat(),
                    'categories': []  # Categories from ListenNotes would need mapping
                }
                
                # Map ListenNotes genres to our categories if available
                if ln_podcast.get('genre_ids'):
                    categories = []
                    for genre_id in ln_podcast.get('genre_ids', []):
                        try:
                            # Look up our category ID from genre mapping
                            mapping_result = self.supabase.table('category_genre') \
                                .select('category_id') \
                                .eq('genre_id', genre_id) \
                                .limit(1) \
                                .execute()
                            
                            if mapping_result.data:
                                category_id = mapping_result.data[0]['category_id']
                                # Get category details
                                cat_result = self.supabase.table('podcast_categories') \
                                    .select('id, name, display_name, color') \
                                    .eq('id', category_id) \
                                    .single() \
                                    .execute()
                                
                                if cat_result.data:
                                    categories.append(cat_result.data)
                        except Exception as e:
                            logger.warning(f"Could not map genre {genre_id} to category: {e}")
                    
                    podcast['categories'] = categories
                
                return podcast
                
        except Exception as e:
            logger.error(f"Error getting podcast from ListenNotes: {e}")
            return None
    
    async def get_all_podcasts_from_listennotes(
        self, 
        limit: int = 100, 
        offset: int = 0,
        user_id: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get all podcasts from ListenNotes API that were created after Jan 1, 2021"""
        try:
            if not self.listennotes_api_key:
                logger.error("ListenNotes API key not configured")
                return [], 0
            
            async with httpx.AsyncClient() as client:
                headers = {
                    'X-ListenAPI-Key': self.listennotes_api_key
                }
                
                # Use best_podcasts endpoint without genre filter to get all podcasts
                # earliest_pub_date_ms for Jan 1, 2021 00:00:00 UTC
                earliest_date_ms = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
                
                params = {
                    'page': (offset // limit) + 1,  # ListenNotes uses 1-based pagination
                    'region': 'us',
                    'safe_mode': 0,
                    'earliest_pub_date_ms': earliest_date_ms,
                    'sort': 'recent_added_first',  # Get recently added podcasts first
                    'show_latest_episodes': 1  # Request latest episode info
                }
                
                response = await client.get(
                    f"{self.listennotes_base_url}/best_podcasts",
                    headers=headers,
                    params=params
                )
                
                if response.status_code != 200:
                    logger.error(f"ListenNotes API error: {response.status_code} - {response.text}")
                    return [], 0
                
                data = response.json()
                
                # Transform ListenNotes results to our format
                podcasts = []
                for ln_podcast in data.get('podcasts', []):
                    # Check if first episode is after 2021-01-01
                    earliest_pub_date = ln_podcast.get('earliest_pub_date_ms', 0)
                    if earliest_pub_date < earliest_date_ms:
                        continue  # Skip podcasts with episodes before 2021
                    
                    # Filter out podcasts without images
                    image_url = ln_podcast.get('image')
                    if not image_url:
                        continue  # Skip podcasts without image URLs
                    
                    # Check if this podcast exists in our database to get claim info
                    listennotes_id = ln_podcast.get('id')
                    claimed = False
                    claimed_by = None
                    is_featured = False
                    following = False
                    
                    # Check local database for additional info
                    if listennotes_id:
                        # Check if podcast exists locally
                        local_podcast = self.supabase.table('podcasts') \
                            .select('id, is_featured') \
                            .eq('listennotes_id', listennotes_id) \
                            .execute()
                        
                        if local_podcast.data:
                            is_featured = local_podcast.data[0].get('is_featured', False)
                            local_id = local_podcast.data[0]['id']
                            
                            # Check if claimed
                            claims_result = self.supabase.table('podcast_claims') \
                                .select('user_id, is_verified, claim_status') \
                                .eq('listennotes_id', listennotes_id) \
                                .eq('is_verified', True) \
                                .eq('claim_status', 'verified') \
                                .execute()
                            
                            if claims_result.data:
                                claimed = True
                                claim_user_id = claims_result.data[0]['user_id']
                                
                                # Get claimant name
                                profile_result = self.supabase.table('user_profiles') \
                                    .select('first_name, last_name, display_name') \
                                    .eq('user_id', claim_user_id) \
                                    .execute()
                                
                                if profile_result.data:
                                    profile = profile_result.data[0]
                                    if profile.get('display_name'):
                                        claimed_by = profile['display_name']
                                    elif profile.get('first_name') and profile.get('last_name'):
                                        claimed_by = f"{profile['first_name']} {profile['last_name']}"
                                    elif profile.get('first_name'):
                                        claimed_by = profile['first_name']
                                    else:
                                        claimed_by = f"User {claim_user_id[:8]}"
                            
                            # Check if user follows this podcast
                            if user_id and local_id:
                                follow_result = self.supabase.table('user_podcast_follows') \
                                    .select('id') \
                                    .eq('user_id', user_id) \
                                    .eq('podcast_id', local_id) \
                                    .execute()
                                following = len(follow_result.data) > 0 if follow_result.data else False
                    
                    podcast = {
                        'id': ln_podcast.get('id'),  # Use ListenNotes ID
                        'listennotes_id': ln_podcast.get('id'),
                        'title': ln_podcast.get('title'),
                        'description': ln_podcast.get('description'),
                        'publisher': ln_podcast.get('publisher'),
                        'language': ln_podcast.get('language', 'en'),
                        'image_url': ln_podcast.get('image'),
                        'thumbnail_url': ln_podcast.get('thumbnail'),
                        'rss_url': ln_podcast.get('rss'),
                        'total_episodes': ln_podcast.get('total_episodes', 0),
                        'explicit_content': ln_podcast.get('explicit_content', False),
                        'is_featured': is_featured,
                        'claimed': claimed,
                        'claimed_by': claimed_by,
                        'following': following if user_id else is_featured,  # Featured shows as following when no user
                        'source': 'listennotes',
                        'created_at': datetime.now(timezone.utc).isoformat(),
                        'updated_at': datetime.now(timezone.utc).isoformat(),
                        'listen_score': ln_podcast.get('listen_score'),
                        'listen_score_global_rank': ln_podcast.get('listen_score_global_rank')
                    }
                    
                    
                    podcasts.append(podcast)
                
                # Calculate total count from API response
                # ListenNotes returns total and next_page_number
                total_count = data.get('total', len(podcasts))
                has_next_page = data.get('has_next', False)
                
                # Since ListenNotes API has limits, we need to handle the total count properly
                # The API might not give us the exact total, so we estimate based on pagination
                if has_next_page:
                    # If there's a next page, we know there are more results
                    estimated_total = max(total_count, offset + limit + 1)
                else:
                    # No next page means we've reached the end
                    estimated_total = offset + len(podcasts)
                
                return podcasts, estimated_total
                
        except Exception as e:
            logger.error(f"Error getting all podcasts from ListenNotes: {e}")
            return [], 0
    
    async def _search_listennotes_api(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search podcasts using ListenNotes API"""
        try:
            if not self.listennotes_api_key:
                logger.warning("ListenNotes API key not configured for search")
                return []
            
            async with httpx.AsyncClient() as client:
                headers = {
                    'X-ListenAPI-Key': self.listennotes_api_key
                }
                
                # Use ListenNotes search endpoint
                params = {
                    'q': query,
                    'type': 'podcast',
                    'page_size': min(limit, 10),  # ListenNotes limits to 10 results
                    'language': 'English'
                }
                
                response = await client.get(
                    f"{self.listennotes_base_url}/search",
                    headers=headers,
                    params=params
                )
                
                if response.status_code != 200:
                    logger.warning(f"ListenNotes search API error: {response.status_code} - {response.text}")
                    return []
                
                data = response.json()
                podcasts = []
                
                for ln_podcast in data.get('results', []):
                    # Decode HTML entities (e.g., &amp; -> &)
                    title_raw = ln_podcast.get('title_original') or ln_podcast.get('title', '')
                    description_raw = ln_podcast.get('description_original') or ln_podcast.get('description', '')
                    publisher_raw = ln_podcast.get('publisher_original') or ln_podcast.get('publisher', '')

                    podcast = {
                        'id': ln_podcast.get('id'),  # Use ListenNotes ID as temporary ID
                        'listennotes_id': ln_podcast.get('id'),
                        'title': html.unescape(title_raw),
                        'description': html.unescape(description_raw),
                        'publisher': html.unescape(publisher_raw),
                        'language': ln_podcast.get('language', 'en'),
                        'image_url': ln_podcast.get('image'),
                        'thumbnail_url': ln_podcast.get('thumbnail'),
                        'rss_url': ln_podcast.get('rss'),
                        'total_episodes': ln_podcast.get('total_episodes', 0),
                        'explicit_content': ln_podcast.get('explicit_content', False),
                        'is_featured': False,  # ListenNotes results are not featured by default
                        'source': 'listennotes',
                        'created_at': datetime.now(timezone.utc).isoformat(),
                        'updated_at': datetime.now(timezone.utc).isoformat(),
                        'categories': []  # We could map genres to categories later
                    }
                    podcasts.append(podcast)
                
                logger.info(f"Found {len(podcasts)} podcasts from ListenNotes API for query: {query}")
                return podcasts
                
        except Exception as e:
            logger.error(f"Error searching ListenNotes API: {e}")
            return []