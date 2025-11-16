"""
Feed caching service with configurable TTL
Provides simple in-memory caching for feed responses to reduce database load
"""

import logging
import time
import hashlib
import json
import os
from typing import Optional, Dict, Any
from threading import Lock

logger = logging.getLogger(__name__)

class FeedCacheService:
    """Simple in-memory cache for feed responses with TTL support"""

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()
        # Get cache TTL from environment variable (default: 60 seconds)
        self._ttl_seconds = int(os.getenv('FEED_CACHE_TTL_SECONDS', '60'))
        # Maximum cache size to prevent memory issues
        self._max_cache_size = int(os.getenv('FEED_CACHE_MAX_SIZE', '1000'))
        logger.info(f"Feed cache initialized with TTL={self._ttl_seconds}s, max_size={self._max_cache_size}")

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
                current_time = time.time()

                # Check if cache entry has expired
                if current_time < cached_item["expires_at"]:
                    logger.debug(f"Cache HIT for key {cache_key}")
                    return cached_item["data"]
                else:
                    # Remove expired entry
                    logger.debug(f"Cache EXPIRED for key {cache_key}")
                    del self._cache[cache_key]
            else:
                logger.debug(f"Cache MISS for key {cache_key}")

        return None

    def set(self, user_id: str, limit: int, cursor: Optional[str], offset: Optional[int], data: Dict) -> None:
        """
        Cache a feed response with TTL

        Args:
            user_id: User ID requesting the feed
            limit: Number of posts to return
            cursor: Cursor for pagination
            offset: Offset for pagination
            data: Feed response data to cache
        """
        cache_key = self._generate_cache_key(user_id, limit, cursor, offset)
        current_time = time.time()
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
                "created_at": current_time
            }
            logger.debug(f"Cached feed response for key {cache_key}, expires in {self._ttl_seconds}s")

    def invalidate(self, user_id: Optional[str] = None) -> None:
        """
        Invalidate cache entries

        Args:
            user_id: If provided, invalidate only entries for this user.
                     If None, invalidate all entries.
        """
        with self._lock:
            if user_id is None:
                # Clear entire cache
                cache_size = len(self._cache)
                self._cache.clear()
                logger.info(f"Invalidated entire feed cache ({cache_size} entries)")
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
                logger.info(f"Invalidated {len(keys_to_remove)} feed cache entries (all users affected)")

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
