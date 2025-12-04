"""
Feed caching service with event-based and TTL-based invalidation
Provides in-memory caching for feed responses with automatic invalidation when data changes
Uses database triggers to track feed updates and invalidate cache accordingly
"""

import logging
import time
import hashlib
import json
import os
from typing import Optional, Dict, Any
from threading import Lock
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class FeedCacheService:
    """Feed cache with event-based and TTL-based invalidation"""

    def __init__(self, supabase_client=None):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()
        # Get cache TTL from environment variable (default: 300 seconds = 5 minutes)
        # This acts as a safety net in case event-based invalidation misses something
        self._ttl_seconds = int(os.getenv('FEED_CACHE_TTL_SECONDS', '300'))
        # Maximum cache size to prevent memory issues
        self._max_cache_size = int(os.getenv('FEED_CACHE_MAX_SIZE', '1000'))
        # Enable event-based invalidation (default: true)
        self._event_based_invalidation = os.getenv('FEED_CACHE_EVENT_BASED', 'true').lower() in ('true', '1', 'yes')
        # Supabase client for checking database timestamps
        self._supabase = supabase_client
        # Cache the last_updated_at timestamp to avoid excessive database queries
        self._last_db_check: float = 0
        self._cached_db_timestamp: Optional[datetime] = None
        self._db_check_interval = 1.0  # Check database at most once per second
        logger.info(f"Feed cache initialized with TTL={self._ttl_seconds}s, max_size={self._max_cache_size}, event_based={self._event_based_invalidation}")

    def _generate_cache_key(self, user_id: str, limit: int, cursor: Optional[str], offset: Optional[int]) -> str:
        """
        Generate a cache key from feed parameters

        Args:
            user_id: User ID requesting the feed
            limit: Number of posts to return
            cursor: Cursor for pagination
            offset: Offset for pagination

        Returns:
            Cache key string
        """
        # Create a deterministic cache key from parameters
        params = {
            "user_id": user_id,
            "limit": limit,
            "cursor": cursor,
            "offset": offset
        }
        # Use JSON serialization for consistent ordering
        params_str = json.dumps(params, sort_keys=True)
        # Hash the parameters for a shorter key
        key_hash = hashlib.md5(params_str.encode()).hexdigest()
        return f"feed:{key_hash}"

    def _get_feed_last_updated(self) -> Optional[datetime]:
        """
        Get the last_updated_at timestamp from the database
        Uses caching to avoid excessive database queries

        Returns:
            Last updated timestamp or None if not available
        """
        if not self._event_based_invalidation or not self._supabase:
            return None

        current_time = time.time()

        # Return cached timestamp if we checked recently
        if current_time - self._last_db_check < self._db_check_interval and self._cached_db_timestamp:
            return self._cached_db_timestamp

        try:
            result = self._supabase.table('feed_cache_metadata') \
                .select('last_updated_at') \
                .eq('id', '00000000-0000-0000-0000-000000000001') \
                .single() \
                .execute()

            if result.data and 'last_updated_at' in result.data:
                timestamp_str = result.data['last_updated_at']
                # Parse ISO format timestamp
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))

                # Update cache
                self._last_db_check = current_time
                self._cached_db_timestamp = timestamp

                return timestamp
        except Exception as e:
            logger.warning(f"Error getting feed last_updated timestamp: {e}")

        return None

    def _is_cache_valid(self, cached_at: datetime, expires_at: float) -> bool:
        """
        Check if a cached entry is still valid based on both event-based and TTL checks

        Args:
            cached_at: When the entry was cached (datetime)
            expires_at: When the TTL expires (timestamp)

        Returns:
            True if cache is still valid, False otherwise
        """
        current_time = time.time()

        # First check TTL (safety net)
        if current_time >= expires_at:
            logger.debug("Cache expired (TTL)")
            return False

        # If event-based invalidation is enabled, check database timestamp
        if self._event_based_invalidation:
            db_timestamp = self._get_feed_last_updated()
            if db_timestamp:
                # Cache is invalid if database was updated after this entry was cached
                if db_timestamp > cached_at:
                    logger.debug(f"Cache invalidated by database event (cached: {cached_at}, db_updated: {db_timestamp})")
                    return False

        return True

    def get(self, user_id: str, limit: int, cursor: Optional[str] = None, offset: Optional[int] = None) -> Optional[Dict]:
        """
        Get cached feed response if available and not expired

        Args:
            user_id: User ID requesting the feed
            limit: Number of posts to return
            cursor: Cursor for pagination
            offset: Offset for pagination

        Returns:
            Cached response dict or None if not found/expired
        """
        cache_key = self._generate_cache_key(user_id, limit, cursor, offset)

        with self._lock:
            if cache_key in self._cache:
                cached_item = self._cache[cache_key]

                # Check if cache entry is still valid (both event-based and TTL)
                if self._is_cache_valid(cached_item["cached_at"], cached_item["expires_at"]):
                    logger.debug(f"Cache HIT for key {cache_key}")
                    return cached_item["data"]
                else:
                    # Remove expired/invalidated entry
                    logger.debug(f"Cache INVALIDATED for key {cache_key}")
                    del self._cache[cache_key]
            else:
                logger.debug(f"Cache MISS for key {cache_key}")

        return None

    def set(self, user_id: str, limit: int, cursor: Optional[str], offset: Optional[int], data: Dict) -> None:
        """
        Cache a feed response with TTL and event-based invalidation

        Args:
            user_id: User ID requesting the feed
            limit: Number of posts to return
            cursor: Cursor for pagination
            offset: Offset for pagination
            data: Feed response data to cache
        """
        cache_key = self._generate_cache_key(user_id, limit, cursor, offset)
        current_time = time.time()
        cached_at = datetime.now(timezone.utc)
        expires_at = current_time + self._ttl_seconds

        with self._lock:
            # Implement simple LRU-like eviction if cache is full
            if len(self._cache) >= self._max_cache_size:
                # Remove oldest entry (simple FIFO for now)
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                logger.debug(f"Cache full, evicted oldest entry: {oldest_key}")

            self._cache[cache_key] = {
                "data": data,
                "expires_at": expires_at,
                "cached_at": cached_at,  # Store as datetime for event-based validation
                "created_at": current_time  # Keep for backwards compatibility
            }
            logger.debug(f"Cached feed response for key {cache_key}, cached_at={cached_at}, expires in {self._ttl_seconds}s")

    def set_supabase_client(self, supabase_client):
        """
        Set the Supabase client for database operations

        Args:
            supabase_client: The Supabase client instance
        """
        self._supabase = supabase_client
        logger.debug("Supabase client set for feed cache service")

    def invalidate_via_database(self) -> bool:
        """
        Invalidate cache by updating the database timestamp
        This triggers automatic invalidation for all cached entries

        Returns:
            True if successful, False otherwise
        """
        if not self._supabase:
            logger.warning("Cannot invalidate via database: Supabase client not set")
            return False

        try:
            self._supabase.table('feed_cache_metadata') \
                .update({'last_updated_at': datetime.now(timezone.utc).isoformat()}) \
                .eq('id', '00000000-0000-0000-0000-000000000001') \
                .execute()

            # Clear cached database timestamp to force refresh on next check
            self._cached_db_timestamp = None
            self._last_db_check = 0

            logger.info("Feed cache invalidated via database timestamp update")
            return True
        except Exception as e:
            logger.error(f"Error invalidating feed cache via database: {e}")
            return False

    def invalidate(self, user_id: Optional[str] = None) -> None:
        """
        Invalidate cache entries (in-memory only)
        For application-level invalidation, use invalidate_via_database() instead

        Args:
            user_id: If provided, invalidate only entries for this user.
                     If None, invalidate all entries.
        """
        with self._lock:
            if user_id is None:
                # Clear entire cache
                cache_size = len(self._cache)
                self._cache.clear()
                logger.info(f"Invalidated entire feed cache in-memory ({cache_size} entries)")
            else:
                # Invalidate entries for specific user
                # Check the cached data to find user-specific entries
                keys_to_remove = []
                for key, cached_item in self._cache.items():
                    # The cache key contains user_id in the params used to generate it
                    # We need to check if this cache entry is for the given user
                    # Since we can't reverse the hash, we'll check all keys that start with "feed:"
                    # and remove them if they match the user_id pattern in the original params
                    if key.startswith("feed:"):
                        # For simplicity, we'll store user_id in the cached data for efficient lookup
                        # For now, invalidate all feed entries (simpler and safer)
                        keys_to_remove.append(key)

                for key in keys_to_remove:
                    del self._cache[key]
                logger.info(f"Invalidated {len(keys_to_remove)} feed cache entries in-memory (all users affected)")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics

        Returns:
            Dict with cache stats
        """
        with self._lock:
            current_time = time.time()
            expired_count = sum(1 for item in self._cache.values() if current_time >= item["expires_at"])

            return {
                "total_entries": len(self._cache),
                "expired_entries": expired_count,
                "active_entries": len(self._cache) - expired_count,
                "ttl_seconds": self._ttl_seconds,
                "max_size": self._max_cache_size
            }


# Global singleton instance
_feed_cache_service: Optional[FeedCacheService] = None

def get_feed_cache_service() -> FeedCacheService:
    """Get or create the global FeedCacheService instance"""
    global _feed_cache_service
    if _feed_cache_service is None:
        _feed_cache_service = FeedCacheService()
    return _feed_cache_service
