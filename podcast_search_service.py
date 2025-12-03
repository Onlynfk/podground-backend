"""
Podcast Search Service
Implements PostgreSQL-based caching with ListenNotes API integration
"""
import httpx
import logging
import os
import html
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone, timedelta
from supabase import Client
import json

logger = logging.getLogger(__name__)

class PodcastSearchService:
    def __init__(self, supabase: Client, listennotes_api_key: str):
        self.supabase = supabase
        self.listennotes_api_key = listennotes_api_key
        self.listennotes_base_url = "https://listen-api.listennotes.com/api/v2"
        # Configurable cache TTL via environment variable (default: 1440 minutes = 24 hours)
        self.search_cache_minutes = int(os.getenv('PODCAST_SEARCH_CACHE_MINUTES', '1440'))
        self.podcast_cache_days = 7
        logger.info(f"Podcast search cache initialized with TTL={self.search_cache_minutes} minutes")
    
    async def search_podcasts(
        self, 
        query: str, 
        genre_id: Optional[int] = None,
        sort_by: str = 'relevance',
        limit: int = 20,
        offset: int = 0,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Search for podcasts with caching
        """
        try:
            # First check cache
            cached_results = await self._get_cached_search(query, genre_id, sort_by, limit, offset)
            if cached_results:
                logger.info(f"Returning cached search results for: {query}")
                # Update claimed status for cached results
                await self._update_claimed_status_batch(cached_results['results'])
                # Update following status if user is provided
                if user_id:
                    await self._update_following_status_batch(cached_results['results'], user_id)
                else:
                    # Set following to false for all results
                    for podcast in cached_results['results']:
                        podcast['following'] = False
                
                # Enrich cached results with latest episode info
                enriched_cached = []
                for podcast in cached_results['results']:
                    latest_episode = await self._get_latest_episode_info(podcast.get('listennotes_id'))
                    if latest_episode:
                        podcast['latest_episode'] = latest_episode
                    enriched_cached.append(podcast)
                
                cached_results['results'] = enriched_cached
                return cached_results
            
            # Cache miss - fetch from API
            api_results = await self._search_listennotes_api(query, genre_id, sort_by, limit, offset)
            if not api_results:
                return {'results': [], 'total': 0, 'source': 'api_error'}
            
            # Cache the results
            await self._cache_search_results(query, genre_id, sort_by, api_results['results'])
            
            # Also cache podcast details for quick access
            await self._cache_podcast_details_from_search(api_results['results'])
            
            # Transform results and add claimed/following status
            results = []
            for podcast in api_results['results']:
                # Decode HTML entities (e.g., &amp; -> &)
                title_raw = podcast.get('title_original', podcast.get('title', ''))
                publisher_raw = podcast.get('publisher_original', podcast.get('publisher', ''))
                description_raw = podcast.get('description_original', podcast.get('description', ''))

                result = {
                    'id': podcast.get('id'),
                    'listennotes_id': podcast.get('id'),
                    'title': html.unescape(title_raw),
                    'publisher': html.unescape(publisher_raw),
                    'description': html.unescape(description_raw),
                    'image': podcast.get('image'),
                    'claimed': False,  # Will be updated in batch
                    'following': False  # Will be updated in batch
                }
                results.append(result)
            
            # Update claimed status for all results
            await self._update_claimed_status_batch(results)
            
            # Update following status if user is provided
            if user_id:
                await self._update_following_status_batch(results, user_id)
            
            # Enrich all results with latest episode info
            enriched_results = []
            for podcast in results:
                latest_episode = await self._get_latest_episode_info(podcast.get('listennotes_id'))
                if latest_episode:
                    podcast['latest_episode'] = latest_episode
                enriched_results.append(podcast)
            
            logger.info(f"Fetched and cached {len(enriched_results)} results for: {query}")
            return {
                'results': enriched_results,
                'total': api_results.get('total', len(enriched_results)),
                'source': 'api'
            }
            
        except Exception as e:
            logger.error(f"Error in podcast search: {e}")
            return {'results': [], 'total': 0, 'source': 'error'}
    
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
            # Extract all listennotes IDs
            listennotes_ids = [p['listennotes_id'] for p in podcasts if 'listennotes_id' in p]
            
            if not listennotes_ids:
                return
            
            # Get internal podcast IDs for these listennotes IDs
            podcasts_result = self.supabase.table('podcasts') \
                .select('id, listennotes_id') \
                .in_('listennotes_id', listennotes_ids) \
                .execute()
            
            if not podcasts_result.data:
                # None of these podcasts exist in our database, so not following any
                for podcast in podcasts:
                    podcast['following'] = False
                return
            
            # Create mapping of listennotes_id to internal podcast_id
            id_mapping = {p['listennotes_id']: p['id'] for p in podcasts_result.data}
            internal_podcast_ids = list(id_mapping.values())
            
            # Query user follows for these podcasts
            follows_result = self.supabase.table('user_podcast_follows') \
                .select('podcast_id') \
                .eq('user_id', user_id) \
                .in_('podcast_id', internal_podcast_ids) \
                .execute()
            
            # Create set of followed internal podcast IDs
            followed_internal_ids = {f['podcast_id'] for f in (follows_result.data or [])}
            
            # Update following status in the podcast list
            for podcast in podcasts:
                if 'listennotes_id' in podcast:
                    listennotes_id = podcast['listennotes_id']
                    internal_id = id_mapping.get(listennotes_id)
                    podcast['following'] = internal_id in followed_internal_ids if internal_id else False
                    
        except Exception as e:
            logger.error(f"Error updating following status batch: {e}")
            # Set all to false on error
            for podcast in podcasts:
                podcast['following'] = False
    
    async def _is_user_following_podcast(self, user_id: str, listennotes_id: str) -> bool:
        """Check if a user is following a specific podcast"""
        try:
            # First get the internal podcast ID
            podcast_result = self.supabase.table('podcasts') \
                .select('id') \
                .eq('listennotes_id', listennotes_id) \
                .single() \
                .execute()
            
            if not podcast_result.data:
                return False
            
            podcast_id = podcast_result.data['id']
            
            # Check if user is following this podcast
            follow_result = self.supabase.table('user_podcast_follows') \
                .select('id') \
                .eq('user_id', user_id) \
                .eq('podcast_id', podcast_id) \
                .single() \
                .execute()
            
            return bool(follow_result.data)
        except Exception:
            return False

    async def get_podcast_details(self, listennotes_id: str, include_episodes: bool = False, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get detailed podcast information with caching
        """
        try:
            # Check if podcast is already cached
            cached_podcast = await self._get_cached_podcast(listennotes_id)
            if cached_podcast and not self._is_cache_expired(cached_podcast.get('cache_expires_at')):
                logger.info(f"Returning cached podcast details for: {listennotes_id}")
                
                # Add claimed status from database
                cached_podcast['claimed'] = cached_podcast.get('is_claimed', False)
                
                # Add following status if user is provided
                if user_id:
                    cached_podcast['following'] = await self._is_user_following_podcast(user_id, listennotes_id)
                else:
                    cached_podcast['following'] = False
                
                if include_episodes:
                    episodes = await self._get_cached_episodes(listennotes_id)
                    cached_podcast['recent_episodes'] = episodes
                
                # Always include latest episode info
                latest_episode = await self._get_latest_episode_info(listennotes_id)
                if latest_episode:
                    cached_podcast['latest_episode'] = latest_episode
                
                return cached_podcast
            
            # Cache miss or expired - fetch from API
            api_data = await self._fetch_podcast_from_listennotes(listennotes_id)
            if not api_data:
                return None
            
            # Cache the podcast details
            podcast_id = await self._cache_podcast_from_api_data(api_data)
            
            # Transform for response
            result = self._transform_podcast_for_response(api_data)
            
            # Check if this podcast is claimed
            result['claimed'] = await self._is_podcast_claimed(listennotes_id)
            
            # Add following status if user is provided
            if user_id:
                result['following'] = await self._is_user_following_podcast(user_id, listennotes_id)
            else:
                result['following'] = False
            
            # Always include latest episode info
            latest_episode = await self._get_latest_episode_info(listennotes_id)
            if latest_episode:
                result['latest_episode'] = latest_episode
            
            # Cache recent episodes if requested
            if include_episodes and api_data.get('episodes'):
                episodes = await self._cache_episodes_from_api_data(
                    listennotes_id, 
                    api_data['episodes'][:10]  # Cache top 10 episodes
                )
                result['recent_episodes'] = episodes
            
            logger.info(f"Fetched and cached podcast details for: {listennotes_id}")
            return result
            
        except Exception as e:
            logger.error(f"Error getting podcast details: {e}")
            return None
    
    async def get_featured_podcasts(self, limit: int = 20, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get featured podcasts (always from database)
        """
        try:
            # Fetch podcasts with latest_episode_id in a single query
            result = self.supabase.table('podcasts') \
                .select('id, listennotes_id, rss_url, title, description, publisher, language, image_url, thumbnail_url, explicit_content, is_featured, latest_episode_id, created_at, updated_at') \
                .eq('is_featured', True) \
                .order('featured_priority', desc=True) \
                .limit(limit) \
                .execute()

            podcasts = result.data or []

            # Add claimed and following status to each podcast
            for podcast in podcasts:
                podcast['claimed'] = podcast.get('is_claimed', False)
                podcast['following'] = False  # Will be updated in batch if user provided

            # Update following status if user is provided
            if user_id:
                await self._update_following_status_batch(podcasts, user_id)

            # Batch fetch latest episodes for all podcasts
            latest_episode_ids = [p['latest_episode_id'] for p in podcasts if p.get('latest_episode_id')]

            episodes_map = {}
            if latest_episode_ids:
                episodes_result = self.supabase.table('episodes') \
                    .select('id, listennotes_id, guid, title, description, audio_url, image_url, duration_seconds, explicit_content, published_at, created_at, updated_at') \
                    .in_('id', latest_episode_ids) \
                    .execute()

                # Create mapping of episode_id to episode data
                for episode in (episodes_result.data or []):
                    # Convert published_at to pub_date for consistency
                    if 'published_at' in episode and episode['published_at']:
                        episode['pub_date'] = episode['published_at']
                    else:
                        episode['pub_date'] = episode.get('created_at')
                    episodes_map[episode['id']] = episode

            # Attach latest episode to each podcast
            for podcast in podcasts:
                episode_id = podcast.get('latest_episode_id')
                if episode_id and episode_id in episodes_map:
                    podcast['latest_episode'] = episodes_map[episode_id]
                # Remove latest_episode_id from response
                podcast.pop('latest_episode_id', None)

            return podcasts

        except Exception as e:
            logger.error(f"Error fetching featured podcasts: {e}")
            return []
    
    async def get_podcasts_by_category(self, category_id: str, limit: int = 20, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get podcasts by category (mix of cached and featured)
        """
        try:
            # Get podcasts from database first
            result = self.supabase.table('podcasts') \
                .select('id, listennotes_id, rss_url, title, description, publisher, language, image_url, thumbnail_url, explicit_content, is_featured, created_at, updated_at') \
                .eq('category_id', category_id) \
                .order('is_featured', desc=True) \
                .order('featured_priority', desc=True) \
                .limit(limit) \
                .execute()
            
            db_podcasts = result.data or []
            
            # Add claimed and following status to database results
            for podcast in db_podcasts:
                podcast['claimed'] = podcast.get('is_claimed', False)
                podcast['following'] = False  # Will be updated in batch if user provided
            
            # Update following status for database results if user is provided
            if user_id:
                await self._update_following_status_batch(db_podcasts, user_id)
            
            # If we need more results, search via API
            if len(db_podcasts) < limit:
                # Get genre ID for this category
                genre_result = self.supabase.table('category_genre') \
                    .select('genre_id') \
                    .eq('category_id', category_id) \
                    .limit(1) \
                    .execute()
                
                if genre_result.data:
                    genre_id = genre_result.data[0]['genre_id']
                    additional_results = await self.search_podcasts(
                        query='', 
                        genre_id=genre_id, 
                        limit=limit - len(db_podcasts),
                        user_id=user_id
                    )
                    
                    # Combine results (avoiding duplicates)
                    existing_ids = {p.get('listennotes_id') for p in db_podcasts}
                    for podcast in additional_results['results']:
                        if podcast.get('listennotes_id') not in existing_ids:
                            db_podcasts.append(podcast)
            
            # Enrich all podcasts with latest episode info
            enriched_podcasts = []
            for podcast in db_podcasts:
                latest_episode = await self._get_latest_episode_info(podcast.get('listennotes_id'))
                if latest_episode:
                    podcast['latest_episode'] = latest_episode
                enriched_podcasts.append(podcast)
            
            return enriched_podcasts
            
        except Exception as e:
            logger.error(f"Error fetching podcasts by category: {e}")
            return []
    
    async def cleanup_expired_cache(self) -> int:
        """
        Clean up expired cache entries
        """
        try:
            # Call the database function
            self.supabase.rpc('cleanup_expired_cache').execute()
            
            # Count what was cleaned up
            search_deleted = self.supabase.table('podcast_search_cache') \
                .select('id', count='exact') \
                .lt('expires_at', datetime.now(timezone.utc).isoformat()) \
                .execute()
            
            episode_deleted = self.supabase.table('episode_cache') \
                .select('id', count='exact') \
                .lt('expires_at', datetime.now(timezone.utc).isoformat()) \
                .execute()
            
            total_cleaned = (search_deleted.count or 0) + (episode_deleted.count or 0)
            logger.info(f"Cleaned up {total_cleaned} expired cache entries")
            
            return total_cleaned
            
        except Exception as e:
            logger.error(f"Error cleaning up cache: {e}")
            return 0
    
    # Private methods
    
    async def _get_cached_search(
        self, 
        query: str, 
        genre_id: Optional[int], 
        sort_by: str, 
        limit: int, 
        offset: int
    ) -> Optional[Dict[str, Any]]:
        """Get cached search results"""
        try:
            result = self.supabase.table('podcast_search_cache') \
                .select('*') \
                .eq('search_query', query) \
                .eq('genre_id', genre_id) \
                .eq('sort_by', sort_by) \
                .gt('expires_at', datetime.now(timezone.utc).isoformat()) \
                .range(offset, offset + limit - 1) \
                .execute()
            
            if result.data:
                return {
                    'results': [self._transform_search_cache_to_response(r) for r in result.data],
                    'total': len(result.data),
                    'source': 'cache'
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting cached search: {e}")
            return None
    
    async def _search_listennotes_api(
        self, 
        query: str, 
        genre_id: Optional[int], 
        sort_by: str, 
        limit: int, 
        offset: int
    ) -> Optional[Dict[str, Any]]:
        """Search ListenNotes API"""
        try:
            async with httpx.AsyncClient() as client:
                headers = {'X-ListenAPI-Key': self.listennotes_api_key}
                
                # Filter for podcasts with first episode from Jan 1, 2021 onwards
                jan_1_2021 = datetime(2021, 1, 1, tzinfo=timezone.utc)
                
                params = {
                    'q': query,
                    'sort_by_date': '0' if sort_by == 'relevance' else '1',
                    'type': 'podcast',
                    'offset': offset,
                    'len_min': limit,
                    'published_after': int(jan_1_2021.timestamp() * 1000),  # Episodes from Jan 1, 2021 onwards
                }
                
                if genre_id:
                    params['genre_ids'] = str(genre_id)
                
                response = await client.get(
                    f"{self.listennotes_base_url}/search",
                    headers=headers,
                    params=params
                )
                
                if response.status_code != 200:
                    logger.error(f"ListenNotes API error: {response.status_code}")
                    return None
                
                data = response.json()
                return {
                    'results': data.get('results', []),
                    'total': data.get('total', 0)
                }
                
        except Exception as e:
            logger.error(f"Error searching ListenNotes API: {e}")
            return None
    
    async def _cache_search_results(self, query: str, genre_id: Optional[int], sort_by: str, results: List[Dict]) -> None:
        """Cache search results"""
        try:
            cache_entries = []
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=self.search_cache_minutes)
            
            for result in results:
                # Decode HTML entities (e.g., &amp; -> &) before caching
                title_raw = result.get('title_original', result.get('title', ''))
                publisher_raw = result.get('publisher_original', result.get('publisher', ''))
                description_raw = result.get('description_original') or result.get('description', '')

                cache_entry = {
                    'search_query': query,
                    'genre_id': genre_id,
                    'sort_by': sort_by,
                    'listennotes_id': result.get('id'),
                    'title': html.unescape(title_raw)[:500],
                    'publisher': html.unescape(publisher_raw)[:255],
                    'description': html.unescape(description_raw)[:1000],
                    'image_url': result.get('image'),
                    'total_episodes': result.get('total_episodes', 0),
                    'first_episode_date': self._parse_timestamp(result.get('earliest_pub_date_ms')),
                    'latest_episode_date': self._parse_timestamp(result.get('latest_pub_date_ms')),
                    'listen_score': result.get('listen_score'),
                    'expires_at': expires_at.isoformat()
                }
                cache_entries.append(cache_entry)
            
            if cache_entries:
                self.supabase.table('podcast_search_cache') \
                    .upsert(cache_entries, on_conflict='search_query,genre_id,sort_by,listennotes_id') \
                    .execute()
                
        except Exception as e:
            logger.error(f"Error caching search results: {e}")
    
    async def _get_cached_podcast(self, listennotes_id: str) -> Optional[Dict[str, Any]]:
        """Get cached podcast details"""
        try:
            result = self.supabase.table('podcasts') \
                .select('id, listennotes_id, rss_url, title, description, publisher, language, image_url, thumbnail_url, explicit_content, is_featured, created_at, updated_at') \
                .eq('listennotes_id', listennotes_id) \
                .single() \
                .execute()
            
            return result.data
            
        except Exception as e:
            logger.debug(f"Podcast not in cache: {listennotes_id}")
            return None
    
    async def _fetch_podcast_from_listennotes(self, listennotes_id: str) -> Optional[Dict[str, Any]]:
        """Fetch podcast details from ListenNotes API"""
        try:
            async with httpx.AsyncClient() as client:
                headers = {'X-ListenAPI-Key': self.listennotes_api_key}
                
                response = await client.get(
                    f"{self.listennotes_base_url}/podcasts/{listennotes_id}",
                    headers=headers
                )
                
                if response.status_code != 200:
                    logger.error(f"ListenNotes API error: {response.status_code}")
                    return None
                
                return response.json()
                
        except Exception as e:
            logger.error(f"Error fetching podcast from ListenNotes: {e}")
            return None
    
    def _parse_timestamp(self, timestamp_ms: Optional[int]) -> Optional[str]:
        """Convert millisecond timestamp to ISO string"""
        if timestamp_ms:
            return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()
        return None
    
    def _is_cache_expired(self, expires_at: Optional[str]) -> bool:
        """Check if cache entry is expired"""
        if not expires_at:
            return True
        
        try:
            expiry = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            return expiry < datetime.now(timezone.utc)
        except:
            return True
    
    def _transform_search_cache_to_response(self, cache_entry: Dict[str, Any]) -> Dict[str, Any]:
        """Transform cached search entry to API response format"""
        return {
            'id': cache_entry['listennotes_id'],
            'listennotes_id': cache_entry['listennotes_id'],
            'title': cache_entry['title'],
            'publisher': cache_entry['publisher'],
            'description': cache_entry['description'],
            'image': cache_entry['image_url'],
            'claimed': False,  # Will be updated in batch
            'following': False  # Will be updated in batch
        }
    
    def _transform_podcast_for_response(self, api_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform API podcast data to response format"""
        # Decode HTML entities (e.g., &amp; -> &)
        title_raw = api_data.get('title_original', api_data.get('title', ''))
        description_raw = api_data.get('description_original', api_data.get('description', ''))
        publisher_raw = api_data.get('publisher_original', api_data.get('publisher', ''))

        return {
            'id': api_data.get('id'),
            'listennotes_id': api_data.get('id'),
            'title': html.unescape(title_raw),
            'description': html.unescape(description_raw),
            'publisher': html.unescape(publisher_raw),
            'image': api_data.get('image'),
            'website': api_data.get('website'),
            'rss': api_data.get('rss'),
            'language': api_data.get('language'),
            'explicit_content': api_data.get('explicit_content'),
            'claimed': False,  # Will be updated separately
            'following': False  # Will be updated separately
        }
    
    async def _cache_podcast_from_api_data(self, api_data: Dict[str, Any]) -> Optional[str]:
        """Cache podcast data from API response"""
        try:
            # Decode HTML entities (e.g., &amp; -> &) before caching
            title_raw = api_data.get('title_original') or api_data.get('title', '')
            publisher_raw = api_data.get('publisher_original') or api_data.get('publisher', '')
            description_raw = api_data.get('description_original') or api_data.get('description', '')

            # Use the database function to cache podcast
            result = self.supabase.rpc('cache_podcast_from_api', {
                'p_listennotes_id': api_data.get('id'),
                'p_title': html.unescape(title_raw)[:500],
                'p_publisher': html.unescape(publisher_raw)[:255],
                'p_description': html.unescape(description_raw),
                'p_image_url': api_data.get('image'),
                'p_rss_url': api_data.get('rss'),
                'p_website_url': api_data.get('website'),
                'p_total_episodes': api_data.get('total_episodes', 0),
                'p_first_episode_date': self._parse_timestamp(api_data.get('earliest_pub_date_ms')),
                'p_latest_episode_date': self._parse_timestamp(api_data.get('latest_pub_date_ms')),
                'p_listen_score': api_data.get('listen_score'),
                'p_genre_id': api_data.get('genre_ids', [None])[0] if api_data.get('genre_ids') else None
            }).execute()
            
            return result.data if result.data else None
            
        except Exception as e:
            logger.error(f"Error caching podcast from API data: {e}")
            return None
    
    async def _cache_podcast_details_from_search(self, search_results: List[Dict[str, Any]]) -> None:
        """Cache basic podcast details from search results"""
        try:
            for result in search_results:
                await self._cache_podcast_from_api_data(result)
                
        except Exception as e:
            logger.error(f"Error caching podcast details from search: {e}")
    
    async def _get_cached_episodes(self, listennotes_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get cached episodes for a podcast"""
        try:
            result = self.supabase.table('episode_cache') \
                .select('*') \
                .eq('podcast_listennotes_id', listennotes_id) \
                .gt('expires_at', datetime.now(timezone.utc).isoformat()) \
                .order('published_at', desc=True) \
                .limit(limit) \
                .execute()
            
            return result.data or []
            
        except Exception as e:
            logger.error(f"Error getting cached episodes: {e}")
            return []
    
    async def _get_latest_episode_info(self, listennotes_id: str) -> Optional[Dict[str, Any]]:
        """Get the latest episode info for a podcast"""
        try:
            # First try to get from episodes table (for podcasts in our DB)
            podcast_result = self.supabase.table('podcasts') \
                .select('id') \
                .eq('listennotes_id', listennotes_id) \
                .single() \
                .execute()
            
            if podcast_result.data:
                # Get the podcast's latest_episode_id
                podcast_detail = self.supabase.table('podcasts') \
                    .select('latest_episode_id') \
                    .eq('listennotes_id', listennotes_id) \
                    .single() \
                    .execute()
                
                if podcast_detail.data and podcast_detail.data.get('latest_episode_id'):
                    episode_result = self.supabase.table('episodes') \
                        .select('id, listennotes_id, guid, title, description, audio_url, image_url, duration_seconds, explicit_content, published_at, created_at, updated_at') \
                        .eq('id', podcast_detail.data['latest_episode_id']) \
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
            
            # Fallback to episode cache
            cache_result = self.supabase.table('episode_cache') \
                .select('*') \
                .eq('podcast_listennotes_id', listennotes_id) \
                .gt('expires_at', datetime.now(timezone.utc).isoformat()) \
                .order('published_at', desc=True) \
                .limit(1) \
                .execute()
            
            if cache_result.data:
                return cache_result.data[0]
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting latest episode info: {e}")
            return None
    
    async def _cache_episodes_from_api_data(self, podcast_listennotes_id: str, episodes_data: List[Dict]) -> List[Dict[str, Any]]:
        """Cache episodes from API data"""
        try:
            cache_entries = []
            expires_at = datetime.now(timezone.utc) + timedelta(days=7)
            
            for episode in episodes_data:
                cache_entry = {
                    'listennotes_episode_id': episode.get('id'),
                    'podcast_listennotes_id': podcast_listennotes_id,
                    'title': episode.get('title', '')[:500],
                    'description': (episode.get('description') or '')[:1000],
                    'audio_url': episode.get('audio'),
                    'image_url': episode.get('image'),
                    'duration_seconds': episode.get('audio_length_sec'),
                    'published_at': self._parse_timestamp(episode.get('pub_date_ms')),
                    'expires_at': expires_at.isoformat()
                }
                cache_entries.append(cache_entry)
            
            if cache_entries:
                result = self.supabase.table('episode_cache') \
                    .upsert(cache_entries, on_conflict='listennotes_episode_id') \
                    .execute()
                
                return result.data or []
            
            return []
            
        except Exception as e:
            logger.error(f"Error caching episodes from API data: {e}")
            return []

# Singleton instance
podcast_search_service = None

def get_podcast_search_service(supabase: Client, listennotes_api_key: str) -> PodcastSearchService:
    """Get or create podcast search service instance"""
    global podcast_search_service
    if podcast_search_service is None:
        podcast_search_service = PodcastSearchService(supabase, listennotes_api_key)
    return podcast_search_service