"""
Global Search Service
Provides unified search across podcasts, episodes, posts, comments, messages, events, resources, and users
with in-memory caching for performance optimization
Integrates ListenNotes API for podcast/episode discovery
"""
import logging
import os
import time
import hashlib
import httpx
import html
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone

from supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

# Configuration from environment variables
SEARCH_CACHE_TTL_SECONDS = int(os.getenv("SEARCH_CACHE_TTL_SECONDS", "3600"))  # 1 hour default
SEARCH_LIMIT_PER_CATEGORY = int(os.getenv("SEARCH_LIMIT_PER_CATEGORY", "10"))  # 10 results per category default
SEARCH_MAX_LIMIT = int(os.getenv("SEARCH_MAX_LIMIT", "50"))  # Maximum results per category
LISTENNOTES_API_KEY = os.getenv("LISTENNOTES_API_KEY", "")

# Relevance score thresholds (configurable per content type)
PODCAST_MIN_SCORE = float(os.getenv("PODCAST_MIN_RELEVANCE_SCORE", "0.8"))  # Exact/phrase match required
EPISODE_MIN_SCORE = float(os.getenv("EPISODE_MIN_RELEVANCE_SCORE", "0.8"))  # Exact/phrase match required
POST_MIN_SCORE = float(os.getenv("POST_MIN_RELEVANCE_SCORE", "0.3"))  # More lenient for posts
COMMENT_MIN_SCORE = float(os.getenv("COMMENT_MIN_RELEVANCE_SCORE", "0.3"))  # More lenient for comments
MESSAGE_MIN_SCORE = float(os.getenv("MESSAGE_MIN_RELEVANCE_SCORE", "0.3"))  # More lenient for messages
EVENT_MIN_SCORE = float(os.getenv("EVENT_MIN_RELEVANCE_SCORE", "0.3"))  # More lenient for events
RESOURCE_MIN_SCORE = float(os.getenv("RESOURCE_MIN_RELEVANCE_SCORE", "0.3"))  # More lenient for resources
USER_MIN_SCORE = float(os.getenv("USER_MIN_RELEVANCE_SCORE", "0.3"))  # More lenient for users


class SearchCache:
    """Simple in-memory cache with TTL support"""

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _generate_key(self, user_id: str, query: str, offset: int = 0, limit: int = SEARCH_LIMIT_PER_CATEGORY) -> str:
        """Generate cache key from user_id, query, and pagination params"""
        combined = f"{user_id}:{query.lower().strip()}:o{offset}:l{limit}"
        return hashlib.md5(combined.encode()).hexdigest()

    def get(self, user_id: str, query: str, offset: int = 0, limit: int = SEARCH_LIMIT_PER_CATEGORY) -> Optional[Dict[str, Any]]:
        """Get cached result if not expired"""
        key = self._generate_key(user_id, query, offset, limit)

        if key in self._cache:
            cached_data = self._cache[key]
            if time.time() < cached_data['expires_at']:
                logger.info(f"Cache hit for search: {query[:50]}")
                return cached_data['result']
            else:
                # Expired, remove from cache
                del self._cache[key]
                logger.info(f"Cache expired for search: {query[:50]}")

        return None

    def set(self, user_id: str, query: str, result: Dict[str, Any], offset: int = 0, limit: int = SEARCH_LIMIT_PER_CATEGORY, ttl_seconds: int = SEARCH_CACHE_TTL_SECONDS):
        """Cache search result with TTL"""
        key = self._generate_key(user_id, query, offset, limit)
        self._cache[key] = {
            'result': result,
            'expires_at': time.time() + ttl_seconds
        }
        logger.info(f"Cached search result: {query[:50]} (TTL: {ttl_seconds}s)")

    def clear(self):
        """Clear all cached results"""
        self._cache.clear()
        logger.info("Search cache cleared")

    def cleanup_expired(self):
        """Remove all expired entries from cache"""
        now = time.time()
        expired_keys = [
            key for key, data in self._cache.items()
            if now >= data['expires_at']
        ]
        for key in expired_keys:
            del self._cache[key]

        if expired_keys:
            logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")


def calculate_title_only_score(query: str, title: str) -> float:
    """
    Calculate relevance score based ONLY on title matching (for podcasts/episodes)

    Scoring algorithm (strict - title only):
    - Exact match in title: 1.0
    - Title contains query as phrase: 0.8
    - No match: 0.0

    Args:
        query: Search query (normalized to lowercase)
        title: Result title (will be normalized)

    Returns:
        Relevance score: 1.0 (exact), 0.8 (phrase), or 0.0 (no match)
    """
    query_lower = query.lower().strip()
    title_lower = title.lower() if title else ""

    # Exact match in title
    if title_lower == query_lower:
        return 1.0

    # Title contains query as phrase
    if query_lower in title_lower:
        return 0.8

    # No match - require exact phrase matching
    return 0.0


def calculate_relevance_score(query: str, title: str, description: str = "") -> float:
    """
    Calculate relevance score for a search result based on query matching
    (Used for posts, comments, messages, events, users - more lenient)

    Scoring algorithm:
    - Exact match in title: 1.0
    - Title contains query as phrase: 0.8
    - Title contains all query words: 0.6
    - Description contains query as phrase: 0.5
    - Description contains some query words: 0.3
    - Partial word matches: 0.2

    Args:
        query: Search query (normalized to lowercase)
        title: Result title (will be normalized)
        description: Result description (will be normalized)

    Returns:
        Relevance score between 0.0 and 1.0
    """
    query_lower = query.lower().strip()
    title_lower = title.lower() if title else ""
    desc_lower = description.lower() if description else ""

    # Exact match in title
    if title_lower == query_lower:
        return 1.0

    # Title contains query as phrase
    if query_lower in title_lower:
        return 0.8

    # Split query into words
    query_words = set(query_lower.split())
    title_words = set(title_lower.split())
    desc_words = set(desc_lower.split())

    # Title contains all query words
    if query_words and query_words.issubset(title_words):
        return 0.6

    # Description contains query as phrase
    if query_lower in desc_lower:
        return 0.5

    # Calculate word overlap
    title_overlap = len(query_words & title_words) / len(query_words) if query_words else 0
    desc_overlap = len(query_words & desc_words) / len(query_words) if query_words else 0

    # At least 50% of query words in title or description
    if title_overlap >= 0.5 or desc_overlap >= 0.5:
        return 0.4

    # Some words match
    if title_overlap > 0 or desc_overlap > 0:
        return 0.3

    # Partial word matches (substring matching)
    for query_word in query_words:
        for title_word in title_words:
            if query_word in title_word or title_word in query_word:
                return 0.2
        for desc_word in desc_words:
            if query_word in desc_word or desc_word in query_word:
                return 0.2

    return 0.0


class GlobalSearchService:
    """Service for searching across all content types"""

    def __init__(self):
        self.supabase_client = get_supabase_client()
        self.cache = SearchCache()

        # Initialize R2 configuration for signed URLs
        self.r2_public_url = os.getenv('R2_PUBLIC_URL', '')

    def _generate_signed_url(self, url: Optional[str]) -> Optional[str]:
        """
        Generate pre-signed URL for R2 storage images

        Args:
            url: Direct R2 public URL or external URL

        Returns:
            Pre-signed URL if it's an R2 URL, otherwise returns the original URL
        """
        if not url:
            return None

        # If it's an R2 URL, generate signed URL
        if self.r2_public_url and url.startswith(self.r2_public_url):
            try:
                storage_path = url.replace(f"{self.r2_public_url}/", "")
                from media_service import MediaService
                media_service = MediaService()
                return media_service.generate_signed_url(storage_path, expiry=3600)
            except Exception as e:
                logger.warning(f"Failed to generate signed URL for {url}: {e}")
                return url

        # Return original URL if it's external (podcast/episode images from ListenNotes, etc.)
        return url

    async def _regenerate_urls_in_search_results(self, search_response: Dict[str, Any]) -> None:
        """
        Regenerate fresh pre-signed URLs for all R2 images in cached search results.
        This ensures URLs are always valid even when served from cache.

        Args:
            search_response: The cached search response to update
        """
        try:
            from concurrent.futures import ThreadPoolExecutor
            from user_profile_service import UserProfileService

            results = search_response.get('results', {})

            # Collect all R2 image URLs and user avatar regeneration tasks
            image_regeneration_tasks = []
            user_profile_tasks = []

            # Podcasts - regenerate image_url (only R2 images, not ListenNotes)
            for podcast in results.get('podcasts', []):
                if podcast.get('image_url') and self.r2_public_url and podcast['image_url'].startswith(self.r2_public_url):
                    image_regeneration_tasks.append(('podcast', podcast, 'image_url', podcast['image_url']))

            # Episodes - regenerate image_url (only R2 images, not ListenNotes)
            for episode in results.get('episodes', []):
                if episode.get('image_url') and self.r2_public_url and episode['image_url'].startswith(self.r2_public_url):
                    image_regeneration_tasks.append(('episode', episode, 'image_url', episode['image_url']))

            # Posts - regenerate image_url and author avatar_url
            for post in results.get('posts', []):
                if post.get('image_url') and self.r2_public_url and post['image_url'].startswith(self.r2_public_url):
                    image_regeneration_tasks.append(('post', post, 'image_url', post['image_url']))

                # Collect user IDs for avatar regeneration
                author = post.get('author', {})
                if author.get('id'):
                    user_profile_tasks.append(('post_author', post, author))

            # Comments - regenerate author avatar_url
            for comment in results.get('comments', []):
                author = comment.get('author', {})
                if author.get('id'):
                    user_profile_tasks.append(('comment_author', comment, author))

            # Messages - regenerate sender avatar_url
            for message in results.get('messages', []):
                sender = message.get('sender', {})
                if sender.get('id'):
                    user_profile_tasks.append(('message_sender', message, sender))

            # Events - regenerate creator avatar_url
            for event in results.get('events', []):
                creator = event.get('creator', {})
                if creator.get('id'):
                    user_profile_tasks.append(('event_creator', event, creator))

            # Resources - regenerate image_url
            for resource in results.get('resources', []):
                if resource.get('image_url') and self.r2_public_url and resource['image_url'].startswith(self.r2_public_url):
                    image_regeneration_tasks.append(('resource', resource, 'image_url', resource['image_url']))

            # Users - regenerate avatar_url
            for user in results.get('users', []):
                if user.get('id'):
                    user_profile_tasks.append(('user', None, user))

            # Partners - regenerate logo_url
            for partner in results.get('partners', []):
                if partner.get('logo_url') and self.r2_public_url and partner['logo_url'].startswith(self.r2_public_url):
                    image_regeneration_tasks.append(('partner', partner, 'logo_url', partner['logo_url']))

            # Experts - regenerate avatar_url
            for expert in results.get('experts', []):
                if expert.get('avatar_url') and self.r2_public_url and expert['avatar_url'].startswith(self.r2_public_url):
                    image_regeneration_tasks.append(('expert', expert, 'avatar_url', expert['avatar_url']))

            # Regenerate R2 image URLs in parallel
            if image_regeneration_tasks:
                with ThreadPoolExecutor(max_workers=10) as executor:
                    def regenerate_url_sync(url: str) -> str:
                        return self._generate_signed_url(url)

                    urls_to_regenerate = [task[3] for task in image_regeneration_tasks]
                    fresh_urls = list(executor.map(regenerate_url_sync, urls_to_regenerate))

                    # Apply fresh URLs back to results
                    for idx, (item_type, item, field, old_url) in enumerate(image_regeneration_tasks):
                        item[field] = fresh_urls[idx]

            # Regenerate user avatars (these come from UserProfileService)
            if user_profile_tasks:
                # Extract unique user IDs
                user_ids = list(set(
                    user_obj.get('id')
                    for task_type, parent_obj, user_obj in user_profile_tasks
                    if user_obj.get('id')
                ))

                if user_ids:
                    # Fetch fresh profiles with signed avatar URLs
                    profile_service = UserProfileService()
                    fresh_profiles = await profile_service.get_users_by_ids(user_ids)
                    profiles_map = {p['id']: p for p in fresh_profiles}

                    # Apply fresh avatar URLs
                    for task_type, parent_obj, user_obj in user_profile_tasks:
                        user_id = user_obj.get('id')
                        if user_id in profiles_map:
                            fresh_avatar_url = profiles_map[user_id].get('avatar_url')
                            user_obj['avatar_url'] = fresh_avatar_url

            logger.debug(f"Regenerated {len(image_regeneration_tasks)} R2 image URLs and {len(user_profile_tasks)} user avatars in search results")

        except Exception as e:
            logger.error(f"Error regenerating URLs in search results: {e}")
            # Don't fail the request if URL regeneration fails

    async def search_all(
        self,
        user_id: str,
        query: str,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Search across all content types with pagination

        Args:
            user_id: Current user ID for filtering messages/events
            query: Search query string
            limit: Max results per category (default from env)
            offset: Number of results to skip

        Returns:
            Dictionary with results grouped by category
        """
        if not query or not query.strip():
            return self._empty_result(limit or SEARCH_LIMIT_PER_CATEGORY, offset)

        query = query.strip()
        limit = min(limit or SEARCH_LIMIT_PER_CATEGORY, SEARCH_MAX_LIMIT)
        offset = max(0, offset)  # Ensure offset is at least 0

        # Check cache first (using offset for cache key)
        cached_result = self.cache.get(user_id, query, offset, limit)
        if cached_result:
            logger.debug(f"Search cache HIT for query '{query}' - regenerating URLs")
            # Regenerate fresh pre-signed URLs (URLs in cache may be expired)
            await self._regenerate_urls_in_search_results(cached_result)
            cached_result['cached'] = True
            return cached_result

        logger.info(f"Performing global search for user {user_id}: '{query}' (offset {offset}, limit {limit})")
        search_start = time.time()

        # Search all categories in parallel using asyncio.gather
        import asyncio
        search_results = await asyncio.gather(
            self._search_podcasts(query, limit, offset),
            self._search_episodes(query, limit, offset),
            self._search_posts(query, limit, offset, user_id),
            self._search_comments(query, limit, offset, user_id),
            self._search_messages(query, limit, offset, user_id),
            self._search_events(query, limit, offset, user_id),
            self._search_resources(query, limit, offset),
            self._search_users(query, limit, offset, user_id),
            self._search_partners(query, limit, offset),
            self._search_experts(query, limit, offset),
            return_exceptions=True  # Don't fail entire search if one category fails
        )

        # Map results back to categories
        results = {
            'podcasts': search_results[0] if not isinstance(search_results[0], Exception) else [],
            'episodes': search_results[1] if not isinstance(search_results[1], Exception) else [],
            'posts': search_results[2] if not isinstance(search_results[2], Exception) else [],
            'comments': search_results[3] if not isinstance(search_results[3], Exception) else [],
            'messages': search_results[4] if not isinstance(search_results[4], Exception) else [],
            'events': search_results[5] if not isinstance(search_results[5], Exception) else [],
            'resources': search_results[6] if not isinstance(search_results[6], Exception) else [],
            'users': search_results[7] if not isinstance(search_results[7], Exception) else [],
            'partners': search_results[8] if not isinstance(search_results[8], Exception) else [],
            'experts': search_results[9] if not isinstance(search_results[9], Exception) else [],
        }

        # Log any exceptions
        for idx, (category, result) in enumerate(zip(['podcasts', 'episodes', 'posts', 'comments', 'messages', 'events', 'resources', 'users', 'partners', 'experts'], search_results)):
            if isinstance(result, Exception):
                logger.error(f"Error searching {category}: {result}")

        search_duration = time.time() - search_start
        logger.info(f"Global search completed in {search_duration:.2f}s (parallel execution)")

        # Calculate totals (for this request)
        total_results = sum(len(results[category]) for category in results)

        response = {
            'query': query,
            'offset': offset,
            'limit': limit,
            'total_results': total_results,
            'results': results,
            'cached': False
        }

        # Cache the result
        self.cache.set(user_id, query, response, offset, limit)

        return response

    def _empty_result(self, limit: int = SEARCH_LIMIT_PER_CATEGORY, offset: int = 0) -> Dict[str, Any]:
        """Return empty search result structure"""
        return {
            'query': '',
            'offset': offset,
            'limit': limit,
            'total_results': 0,
            'results': {
                'podcasts': [],
                'episodes': [],
                'posts': [],
                'comments': [],
                'messages': [],
                'events': [],
                'resources': [],
                'users': [],
                'partners': [],
                'experts': []
            },
            'cached': False
        }

    async def _search_podcasts(self, query: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        """
        Search podcasts using PostgreSQL full-text search + ListenNotes API
        Uses ts_rank for relevance ranking and filters by minimum score
        """
        try:
            # First search local database using full-text search
            # Using ts_rank for relevance scoring
            db_result = self.supabase_client.service_client.rpc(
                'search_podcasts_ranked',
                {
                    'search_query': query,
                    'result_limit': limit * 2,  # Fetch more to account for filtering
                    'result_offset': offset
                }
            ).execute()

            podcasts = []
            local_listennotes_ids = set()

            for podcast in (db_result.data or []):
                # Calculate title-only relevance score (strict matching)
                relevance_score = calculate_title_only_score(
                    query,
                    podcast.get('title', '')
                )

                # Skip low-relevance results from database (0.8 threshold = exact/phrase match only)
                if relevance_score < PODCAST_MIN_SCORE:
                    continue

                podcasts.append({
                    'id': podcast.get('id'),
                    'listennotes_id': podcast.get('listennotes_id'),
                    'title': podcast['title'],
                    'description': podcast.get('description', '')[:200],
                    'image_url': self._generate_signed_url(podcast.get('image_url')),
                    'publisher': podcast.get('publisher'),
                    'source': 'database',
                    'type': 'podcast',
                    'relevance_score': relevance_score
                })
                if podcast.get('listennotes_id'):
                    local_listennotes_ids.add(podcast['listennotes_id'])

            # If we have fewer results than limit, search ListenNotes API
            remaining_slots = limit - len(podcasts)
            if remaining_slots > 0 and LISTENNOTES_API_KEY:
                api_podcasts = await self._search_listennotes_podcasts(query, remaining_slots * 2, offset)

                # Add API results that aren't already in our database and meet relevance threshold
                for api_podcast in api_podcasts:
                    if api_podcast.get('listennotes_id') not in local_listennotes_ids:
                        # Calculate title-only relevance score for API results (strict matching)
                        relevance_score = calculate_title_only_score(
                            query,
                            api_podcast.get('title', '')
                        )

                        # Only add if meets minimum relevance threshold (exact/phrase match only)
                        if relevance_score >= PODCAST_MIN_SCORE:
                            api_podcast['relevance_score'] = relevance_score
                            podcasts.append(api_podcast)

            # Sort all results by relevance score (descending)
            podcasts.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)

            return podcasts[:limit]  # Return top results up to limit

        except Exception as e:
            logger.error(f"Error searching podcasts: {e}")
            # Fallback to simple search if RPC function doesn't exist yet
            try:
                db_result = self.supabase_client.service_client.table('podcasts') \
                    .select('id, listennotes_id, title, description, image_url, publisher') \
                    .ilike('title', f'%{query}%') \
                    .range(offset, offset + limit - 1) \
                    .execute()

                podcasts = []
                for podcast in (db_result.data or []):
                    relevance_score = calculate_title_only_score(
                        query,
                        podcast.get('title', '')
                    )

                    if relevance_score >= PODCAST_MIN_SCORE:
                        podcasts.append({
                            'id': podcast.get('id'),
                            'listennotes_id': podcast.get('listennotes_id'),
                            'title': podcast['title'],
                            'description': podcast.get('description', '')[:200],
                            'image_url': self._generate_signed_url(podcast.get('image_url')),
                            'publisher': podcast.get('publisher'),
                            'source': 'database',
                            'type': 'podcast',
                            'relevance_score': relevance_score
                        })

                return podcasts[:limit]
            except Exception as fallback_error:
                logger.error(f"Fallback search also failed: {fallback_error}")
                return []

    async def _search_episodes(self, query: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        """
        Search episodes using PostgreSQL full-text search + ListenNotes API
        Uses ts_rank for relevance ranking and filters by minimum score
        """
        try:
            # First search local database using full-text search
            db_result = self.supabase_client.service_client.rpc(
                'search_episodes_ranked',
                {
                    'search_query': query,
                    'result_limit': limit * 2,  # Fetch more to account for filtering
                    'result_offset': offset
                }
            ).execute()

            episodes = []
            local_episode_ids = set()

            for episode in (db_result.data or []):
                # Calculate title-only relevance score (strict matching)
                relevance_score = calculate_title_only_score(
                    query,
                    episode.get('title', '')
                )

                # Skip low-relevance results from database (0.8 threshold = exact/phrase match only)
                if relevance_score < EPISODE_MIN_SCORE:
                    continue

                podcast = episode.get('podcasts') or {}
                episode_image = episode.get('image_url') or podcast.get('image_url')
                episodes.append({
                    'id': episode.get('id'),
                    'listennotes_id': episode.get('listennotes_id'),
                    'title': episode['title'],
                    'description': episode.get('description', '')[:200],
                    'image_url': self._generate_signed_url(episode_image),
                    'podcast_id': episode.get('podcast_id'),
                    'podcast_title': podcast.get('title'),
                    'podcast_listennotes_id': podcast.get('listennotes_id'),
                    'source': 'database',
                    'type': 'episode',
                    'relevance_score': relevance_score
                })
                if episode.get('listennotes_id'):
                    local_episode_ids.add(episode['listennotes_id'])

            # If we have fewer results than limit, search ListenNotes API
            remaining_slots = limit - len(episodes)
            if remaining_slots > 0 and LISTENNOTES_API_KEY:
                api_episodes = await self._search_listennotes_episodes(query, remaining_slots * 2, offset)

                # Add API results that aren't already in our database and meet relevance threshold
                for api_episode in api_episodes:
                    if api_episode.get('listennotes_id') not in local_episode_ids:
                        # Calculate title-only relevance score for API results (strict matching)
                        relevance_score = calculate_title_only_score(
                            query,
                            api_episode.get('title', '')
                        )

                        # Only add if meets minimum relevance threshold (exact/phrase match only)
                        if relevance_score >= EPISODE_MIN_SCORE:
                            api_episode['relevance_score'] = relevance_score
                            episodes.append(api_episode)

            # Sort all results by relevance score (descending)
            episodes.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)

            return episodes[:limit]  # Return top results up to limit

        except Exception as e:
            logger.error(f"Error searching episodes: {e}")
            # Fallback to simple search if RPC function doesn't exist yet
            try:
                db_result = self.supabase_client.service_client.table('episodes') \
                    .select('id, listennotes_id, title, description, image_url, podcast_id, podcasts!episodes_podcast_id_fkey(title, image_url, listennotes_id)') \
                    .ilike('title', f'%{query}%') \
                    .range(offset, offset + limit - 1) \
                    .execute()

                episodes = []
                for episode in (db_result.data or []):
                    relevance_score = calculate_title_only_score(
                        query,
                        episode.get('title', '')
                    )

                    if relevance_score >= EPISODE_MIN_SCORE:
                        podcast = episode.get('podcasts') or {}
                        episode_image = episode.get('image_url') or podcast.get('image_url')
                        episodes.append({
                            'id': episode.get('id'),
                            'listennotes_id': episode.get('listennotes_id'),
                            'title': episode['title'],
                            'description': episode.get('description', '')[:200],
                            'image_url': self._generate_signed_url(episode_image),
                            'podcast_id': episode.get('podcast_id'),
                            'podcast_title': podcast.get('title'),
                            'podcast_listennotes_id': podcast.get('listennotes_id'),
                            'source': 'database',
                            'type': 'episode',
                            'relevance_score': relevance_score
                        })

                return episodes[:limit]
            except Exception as fallback_error:
                logger.error(f"Fallback search also failed: {fallback_error}")
                return []

    async def _search_posts(self, query: str, limit: int, offset: int, user_id: str) -> List[Dict[str, Any]]:
        """Search posts by content"""
        try:
            # Search in post content
            result = self.supabase_client.service_client.table('posts') \
                .select('id, content, post_type, user_id, created_at') \
                .ilike('content', f'%{query}%') \
                .is_('deleted_at', None) \
                .order('created_at', desc=True) \
                .range(offset, offset + limit - 1) \
                .execute()

            if not result.data:
                return []

            # Get user IDs and post IDs for batch fetching
            user_ids = list(set(post['user_id'] for post in result.data))
            post_ids = [post['id'] for post in result.data]

            # Batch fetch user profiles (already returns signed avatar URLs)
            from user_profile_service import UserProfileService
            profile_service = UserProfileService()
            user_profiles = await profile_service.get_users_by_ids(user_ids)
            profiles_map = {u['id']: u for u in user_profiles}

            # Batch fetch first image for each post
            media_result = self.supabase_client.service_client.table('post_media') \
                .select('post_id, url') \
                .in_('post_id', post_ids) \
                .eq('type', 'image') \
                .order('position') \
                .execute()

            # Map first image per post and generate signed URLs
            images_map = {}
            for media in (media_result.data or []):
                post_id = media['post_id']
                if post_id not in images_map:
                    images_map[post_id] = self._generate_signed_url(media['url'])

            posts = []
            for post in result.data:
                author = profiles_map.get(post['user_id'], {})
                posts.append({
                    'id': post['id'],
                    'content': post['content'][:200] if post.get('content') else '',  # Truncate
                    'post_type': post['post_type'],
                    'author': {
                        'id': author.get('id'),
                        'name': author.get('name'),
                        'avatar_url': author.get('avatar_url')  # Already signed from profile service
                    },
                    'image_url': images_map.get(post['id']),
                    'created_at': post['created_at'],
                    'type': 'post'
                })

            return posts
        except Exception as e:
            logger.error(f"Error searching posts: {e}")
            return []

    async def _search_comments(self, query: str, limit: int, offset: int, user_id: str) -> List[Dict[str, Any]]:
        """Search comments by content"""
        try:
            result = self.supabase_client.service_client.table('post_comments') \
                .select('id, content, post_id, user_id, created_at, posts(id, content)') \
                .ilike('content', f'%{query}%') \
                .is_('deleted_at', None) \
                .order('created_at', desc=True) \
                .range(offset, offset + limit - 1) \
                .execute()

            if not result.data:
                return []

            # Batch fetch user profiles (already returns signed avatar URLs)
            user_ids = list(set(comment['user_id'] for comment in result.data))
            from user_profile_service import UserProfileService
            profile_service = UserProfileService()
            user_profiles = await profile_service.get_users_by_ids(user_ids)
            profiles_map = {u['id']: u for u in user_profiles}

            comments = []
            for comment in result.data:
                author = profiles_map.get(comment['user_id'], {})
                post = comment.get('posts') or {}
                comments.append({
                    'id': comment['id'],
                    'content': comment['content'][:200],  # Truncate
                    'post_id': comment['post_id'],
                    'post_preview': post.get('content', '')[:100] if post.get('content') else '',
                    'author': {
                        'id': author.get('id'),
                        'name': author.get('name'),
                        'avatar_url': author.get('avatar_url')  # Already signed from profile service
                    },
                    'created_at': comment['created_at'],
                    'type': 'comment'
                })

            return comments
        except Exception as e:
            logger.error(f"Error searching comments: {e}")
            return []

    async def _search_messages(self, query: str, limit: int, offset: int, user_id: str) -> List[Dict[str, Any]]:
        """Search messages in user's conversations"""
        try:
            # First get user's conversation IDs
            conversations_result = self.supabase_client.service_client.table('conversation_participants') \
                .select('conversation_id') \
                .eq('user_id', user_id) \
                .is_('left_at', None) \
                .execute()

            if not conversations_result.data:
                logger.info(f"No conversations found for user {user_id}")
                return []

            conversation_ids = [c['conversation_id'] for c in conversations_result.data]

            # Limit conversation IDs to avoid URL length issues (max 100)
            if len(conversation_ids) > 100:
                logger.warning(f"User {user_id} has {len(conversation_ids)} conversations, limiting to 100 for search")
                conversation_ids = conversation_ids[:100]

            logger.info(f"Searching messages in {len(conversation_ids)} conversations for user {user_id}")

            # Search messages in these conversations
            # Use client-side filtering to avoid Cloudflare Worker issues with .ilike()
            result = self.supabase_client.service_client.table('messages') \
                .select('id, content, conversation_id, sender_id, created_at') \
                .in_('conversation_id', conversation_ids) \
                .eq('is_deleted', False) \
                .order('created_at', desc=True) \
                .limit(100) \
                .execute()

            # Filter by content on client side
            if result.data:
                query_lower = query.lower()
                result.data = [m for m in result.data if query_lower in (m.get('content') or '').lower()]

            # Manual pagination
            if offset > 0 and result.data:
                result.data = result.data[offset:offset + limit]
            elif result.data:
                result.data = result.data[:limit]

            if not result.data:
                logger.info(f"No messages found matching query '{query}' for user {user_id}")
                return []

            logger.info(f"Found {len(result.data)} messages matching query '{query}' for user {user_id}")

            # Batch fetch sender profiles (already returns signed avatar URLs)
            sender_ids = list(set(msg['sender_id'] for msg in result.data))
            from user_profile_service import UserProfileService
            profile_service = UserProfileService()
            user_profiles = await profile_service.get_users_by_ids(sender_ids)
            profiles_map = {u['id']: u for u in user_profiles}

            messages = []
            for message in result.data:
                sender = profiles_map.get(message['sender_id'], {})
                messages.append({
                    'id': message['id'],
                    'content': message['content'][:200],  # Truncate
                    'conversation_id': message['conversation_id'],
                    'sender': {
                        'id': sender.get('id'),
                        'name': sender.get('name'),
                        'avatar_url': sender.get('avatar_url')  # Already signed from profile service
                    },
                    'created_at': message['created_at'],
                    'type': 'message'
                })

            return messages
        except Exception as e:
            logger.error(f"Error searching messages for user {user_id}: {e}", exc_info=True)
            return []

    async def _search_events(self, query: str, limit: int, offset: int, user_id: str) -> List[Dict[str, Any]]:
        """Search events by title"""
        try:
            logger.info(f"Searching events with query '{query}' for user {user_id}")

            # Use .ilike() in Python instead of on server to avoid Cloudflare Worker issues
            # Fetch all events then filter client-side
            result = self.supabase_client.service_client.table('events') \
                .select('id, title, description, event_date, location, host_user_id, host_name, created_at') \
                .order('event_date', desc=True) \
                .limit(100) \
                .execute()

            # Filter by title on client side
            if result.data:
                query_lower = query.lower()
                result.data = [e for e in result.data if query_lower in (e.get('title') or '').lower()]

            # Manual pagination
            if offset > 0 and result.data:
                result.data = result.data[offset:offset + limit]
            elif result.data:
                result.data = result.data[:limit]

            if not result.data:
                logger.info(f"No events found matching query '{query}'")
                return []

            logger.info(f"Found {len(result.data)} events matching query '{query}'")

            # Batch fetch creator profiles if host_user_id exists (already returns signed avatar URLs)
            # Note: Some events may have host_user_id = null (PodGround platform events)
            creator_ids = list(set(event['host_user_id'] for event in result.data if event.get('host_user_id')))
            profiles_map = {}
            if creator_ids:
                from user_profile_service import UserProfileService
                profile_service = UserProfileService()
                user_profiles = await profile_service.get_users_by_ids(creator_ids)
                profiles_map = {u['id']: u for u in user_profiles}

            events = []
            for event in result.data:
                # Get creator info from profile if host_user_id exists, otherwise use host_name
                host_user_id = event.get('host_user_id')
                if host_user_id and host_user_id in profiles_map:
                    creator = profiles_map[host_user_id]
                    creator_info = {
                        'id': creator.get('id'),
                        'name': creator.get('name'),
                        'avatar_url': creator.get('avatar_url')  # Already signed from profile service
                    }
                else:
                    # PodGround platform event or host info not available
                    creator_info = {
                        'id': None,
                        'name': event.get('host_name', 'PodGround'),
                        'avatar_url': None
                    }

                events.append({
                    'id': event['id'],
                    'title': event['title'],
                    'description': event.get('description', '')[:200],  # Truncate
                    'event_date': event.get('event_date'),
                    'location': event.get('location'),
                    'creator': creator_info,
                    'created_at': event['created_at'],
                    'type': 'event'
                })

            return events
        except Exception as e:
            logger.error(f"Error searching events: {e}", exc_info=True)
            return []

    async def _search_resources(self, query: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        """Search resources by title (articles and videos)"""
        try:
            logger.info(f"Searching resources with query '{query}'")

            # Use .ilike() in Python instead of on server to avoid Cloudflare Worker issues
            # Fetch all resources then filter client-side
            result = self.supabase_client.service_client.table('resources') \
                .select('id, title, description, type, url, image_url, author, read_time, created_at') \
                .order('created_at', desc=True) \
                .limit(100) \
                .execute()

            # Filter by title on client side
            if result.data:
                query_lower = query.lower()
                result.data = [r for r in result.data if query_lower in (r.get('title') or '').lower()]

            # Manual pagination
            if offset > 0 and result.data:
                result.data = result.data[offset:offset + limit]
            elif result.data:
                result.data = result.data[:limit]

            if not result.data:
                logger.info(f"No resources found matching query '{query}'")
                return []

            logger.info(f"Found {len(result.data)} resources matching query '{query}'")

            resources = []
            for resource in result.data:
                # Generate signed URL for resource image if it's from R2
                image_url = self._generate_signed_url(resource.get('image_url'))

                resources.append({
                    'id': resource['id'],
                    'title': resource['title'],
                    'description': resource.get('description', '')[:200],  # Truncate
                    'resource_type': resource['type'],  # 'article', 'video', 'guide', 'tool'
                    'url': resource.get('url'),
                    'image_url': image_url,
                    'author': resource.get('author'),
                    'read_time': resource.get('read_time'),
                    'created_at': resource['created_at'],
                    'type': 'resource'
                })

            return resources
        except Exception as e:
            logger.error(f"Error searching resources: {e}", exc_info=True)
            return []

    async def _search_users(self, query: str, limit: int, offset: int, current_user_id: str) -> List[Dict[str, Any]]:
        """Search users by name"""
        try:
            # Search in user profiles (name and bio)
            from user_profile_service import UserProfileService
            from user_settings_service import get_user_settings_service

            profile_service = UserProfileService()
            settings_service = get_user_settings_service()

            # Search by name using user_profiles table
            result = self.supabase_client.service_client.table('user_profiles') \
                .select('user_id, first_name, last_name, bio') \
                .neq('user_id', current_user_id) \
                .or_(f'first_name.ilike.%{query}%,last_name.ilike.%{query}%') \
                .range(offset, offset + (limit * 3) - 1) \
                .execute()  # Fetch more to account for privacy filtering

            if not result.data:
                return []

            # Filter by platform readiness (completed onboarding + verified podcast claim)
            user_ids = [u['user_id'] for u in result.data]
            platform_ready_result = self.supabase_client.filter_platform_ready_users(user_ids)

            if not platform_ready_result["success"]:
                logger.error(f"Failed to filter platform ready users in search: {platform_ready_result.get('error')}")
                return []

            ready_user_ids = platform_ready_result["ready_user_ids"]
            if not ready_user_ids:
                return []

            # Get full profiles with avatars (already returns signed avatar URLs)
            user_profiles = await profile_service.get_users_by_ids(ready_user_ids)

            users = []
            for profile in user_profiles:
                # Check if user is searchable based on privacy settings
                is_searchable = await settings_service.is_user_searchable(profile['id'])

                if not is_searchable:
                    logger.debug(f"User {profile['id']} is not searchable, skipping")
                    continue

                users.append({
                    'id': profile['id'],
                    'name': profile.get('name'),
                    'bio': profile.get('bio', '')[:200] if profile.get('bio') else '',
                    'avatar_url': profile.get('avatar_url'),  # Already signed from profile service
                    'podcast_name': profile.get('podcast_name'),
                    'type': 'user'
                })

                # Stop when we have enough results
                if len(users) >= limit:
                    break

            return users[:limit]  # Return only requested limit
        except Exception as e:
            logger.error(f"Error searching users: {e}")
            return []

    async def _search_partners(self, query: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        """Search partner deals by partner name and description"""
        try:
            logger.info(f"Searching partner deals with query '{query}'")

            # Fetch all active partner deals then filter client-side
            result = self.supabase_client.service_client.table('partner_deals') \
                .select('id, partner_name, deal_title, description, deal_url, image_url, category, created_at') \
                .eq('is_active', True) \
                .order('created_at', desc=True) \
                .limit(100) \
                .execute()

            # Filter by partner name, deal_title, and description on client side
            if result.data:
                query_lower = query.lower()
                result.data = [
                    p for p in result.data
                    if query_lower in (p.get('partner_name') or '').lower()
                    or query_lower in (p.get('deal_title') or '').lower()
                    or query_lower in (p.get('description') or '').lower()
                ]

            # Manual pagination
            if offset > 0 and result.data:
                result.data = result.data[offset:offset + limit]
            elif result.data:
                result.data = result.data[:limit]

            if not result.data:
                logger.info(f"No partner deals found matching query '{query}'")
                return []

            logger.info(f"Found {len(result.data)} partner deals matching query '{query}'")

            partners = []
            for partner in result.data:
                # Generate signed URL for partner logo if it's from R2
                logo_url = self._generate_signed_url(partner.get('image_url'))

                partners.append({
                    'id': partner['id'],
                    'partner_name': partner.get('partner_name'),
                    'deal_title': partner.get('deal_title'),
                    'description': partner.get('description', '')[:200],  # Truncate
                    'deal_url': partner.get('deal_url'),
                    'category': partner.get('category'),
                    'logo_url': logo_url,
                    'created_at': partner['created_at'],
                    'type': 'partner'
                })

            return partners
        except Exception as e:
            logger.error(f"Error searching partner deals: {e}", exc_info=True)
            return []

    async def _search_experts(self, query: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        """Search experts by name, title, specialization, and bio"""
        try:
            logger.info(f"Searching experts with query '{query}'")

            # Fetch all experts then filter client-side
            result = self.supabase_client.service_client.table('experts') \
                .select('id, name, title, specialization, bio, avatar_url, is_available, hourly_rate, rating, created_at') \
                .order('rating', desc=True) \
                .limit(100) \
                .execute()

            # Filter by name, title, specialization, and bio on client side
            if result.data:
                query_lower = query.lower()
                result.data = [
                    e for e in result.data
                    if query_lower in (e.get('name') or '').lower()
                    or query_lower in (e.get('title') or '').lower()
                    or query_lower in (e.get('specialization') or '').lower()
                    or query_lower in (e.get('bio') or '').lower()
                ]

            # Manual pagination
            if offset > 0 and result.data:
                result.data = result.data[offset:offset + limit]
            elif result.data:
                result.data = result.data[:limit]

            if not result.data:
                logger.info(f"No experts found matching query '{query}'")
                return []

            logger.info(f"Found {len(result.data)} experts matching query '{query}'")

            experts = []
            for expert in result.data:
                # Generate signed URL for expert avatar if it's from R2
                avatar_url = self._generate_signed_url(expert.get('avatar_url'))

                experts.append({
                    'id': expert['id'],
                    'name': expert.get('name'),
                    'title': expert.get('title'),
                    'specialization': expert.get('specialization'),
                    'bio': expert.get('bio', '')[:200] if expert.get('bio') else '',  # Truncate
                    'avatar_url': avatar_url,
                    'is_available': expert.get('is_available'),
                    'hourly_rate': expert.get('hourly_rate'),
                    'rating': expert.get('rating'),
                    'created_at': expert['created_at'],
                    'type': 'expert'
                })

            return experts
        except Exception as e:
            logger.error(f"Error searching experts: {e}", exc_info=True)
            return []

    async def _search_listennotes_podcasts(self, query: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        """Search ListenNotes API for podcasts"""
        if not LISTENNOTES_API_KEY:
            return []

        try:
            async with httpx.AsyncClient() as client:
                headers = {'X-ListenAPI-Key': LISTENNOTES_API_KEY}

                # Filter for podcasts with first episode from Jan 1, 2021 onwards
                jan_1_2021 = datetime(2021, 1, 1, tzinfo=timezone.utc)

                params = {
                    'q': query,
                    'sort_by_date': 0,  # Relevance
                    'type': 'podcast',
                    'offset': offset,
                    'len_min': limit,
                    'published_after': int(jan_1_2021.timestamp() * 1000),
                }

                response = await client.get(
                    "https://listen-api.listennotes.com/api/v2/search",
                    headers=headers,
                    params=params,
                    timeout=5.0  # 5 second timeout
                )

                if response.status_code != 200:
                    logger.warning(f"ListenNotes API error: {response.status_code}")
                    return []

                data = response.json()
                podcasts = []

                for result in data.get('results', []):
                    # Decode HTML entities (e.g., &amp; -> &)
                    title_raw = result.get('title_original', result.get('title', ''))
                    description_raw = result.get('description_original') or result.get('description', '')
                    publisher_raw = result.get('publisher_original', result.get('publisher', ''))

                    podcasts.append({
                        'id': result.get('id'),  # ListenNotes ID
                        'listennotes_id': result.get('id'),
                        'title': html.unescape(title_raw),
                        'description': html.unescape(description_raw)[:200],
                        'image_url': result.get('image'),  # External URL, no signing needed
                        'publisher': html.unescape(publisher_raw),
                        'source': 'listennotes',
                        'type': 'podcast'
                    })

                logger.info(f"ListenNotes API returned {len(podcasts)} podcasts for query: '{query}'")
                return podcasts

        except httpx.TimeoutException:
            logger.warning(f"ListenNotes API timeout for query: '{query}'")
            return []
        except Exception as e:
            logger.error(f"Error searching ListenNotes podcasts: {e}")
            return []

    async def _search_listennotes_episodes(self, query: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        """Search ListenNotes API for episodes"""
        if not LISTENNOTES_API_KEY:
            return []

        try:
            async with httpx.AsyncClient() as client:
                headers = {'X-ListenAPI-Key': LISTENNOTES_API_KEY}

                params = {
                    'q': query,
                    'sort_by_date': 0,  # Relevance
                    'type': 'episode',
                    'offset': offset,
                    'len_min': limit,
                }

                response = await client.get(
                    "https://listen-api.listennotes.com/api/v2/search",
                    headers=headers,
                    params=params,
                    timeout=5.0  # 5 second timeout
                )

                if response.status_code != 200:
                    logger.warning(f"ListenNotes API error: {response.status_code}")
                    return []

                data = response.json()
                episodes = []

                for result in data.get('results', []):
                    # Decode HTML entities (e.g., &amp; -> &)
                    title_raw = result.get('title_original', result.get('title', ''))
                    description_raw = result.get('description_original') or result.get('description', '')
                    podcast_title_raw = result.get('podcast', {}).get('title_original', result.get('podcast', {}).get('title', ''))

                    episodes.append({
                        'id': result.get('id'),  # ListenNotes episode ID
                        'listennotes_id': result.get('id'),
                        'title': html.unescape(title_raw),
                        'description': html.unescape(description_raw)[:200],
                        'image_url': result.get('image'),  # External URL, no signing needed
                        'podcast_id': None,  # Not in our database
                        'podcast_title': html.unescape(podcast_title_raw),
                        'podcast_listennotes_id': result.get('podcast', {}).get('id'),
                        'audio_url': result.get('audio'),
                        'pub_date': result.get('pub_date_ms'),
                        'source': 'listennotes',
                        'type': 'episode'
                    })

                logger.info(f"ListenNotes API returned {len(episodes)} episodes for query: '{query}'")
                return episodes

        except httpx.TimeoutException:
            logger.warning(f"ListenNotes API timeout for query: '{query}'")
            return []
        except Exception as e:
            logger.error(f"Error searching ListenNotes episodes: {e}")
            return []


# Global instance
_global_search_service = None

def get_global_search_service() -> GlobalSearchService:
    """Get or create global search service instance"""
    global _global_search_service
    if _global_search_service is None:
        _global_search_service = GlobalSearchService()
    return _global_search_service
