"""
Podcast Episode caching service with configurable TTL
Provides in-memory caching for podcast episodes to reduce database queries and API calls
"""

import logging
import time
import os
from typing import Optional, Dict, Any, List, Tuple
from threading import Lock

logger = logging.getLogger(__name__)

class PodcastEpisodeCacheService:
    """Simple in-memory cache for podcast episodes with TTL support"""

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()

        # Get cache TTL from environment variable (default: same as LATEST_EPISODE_TTL_MINUTES)
        self._ttl_minutes = int(os.getenv('LATEST_EPISODE_TTL_MINUTES', '360'))
        self._ttl_seconds = self._ttl_minutes * 60

        # Cache enabled flag
        self._cache_enabled = os.getenv('ENABLE_LATEST_EPISODE_CACHE', 'true').lower() in ('true', '1', 'yes')

        # Maximum cache size to prevent memory issues
        self._max_cache_size = int(os.getenv('PODCAST_EPISODE_CACHE_MAX_SIZE', '2000'))

        logger.info(f"Podcast episode cache initialized with enabled={self._cache_enabled}, TTL={self._ttl_minutes}min, max_size={self._max_cache_size}")

    def is_enabled(self) -> bool:
        """Check if caching is enabled"""
        return self._cache_enabled

    def _generate_latest_episode_key(self, podcast_id: str) -> str:
        """Generate cache key for latest episode"""
        return f"latest_episode:{podcast_id}"

    def _generate_episodes_list_key(self, podcast_id: str, limit: int, offset: int) -> str:
        """Generate cache key for episode list"""
        return f"episodes_list:{podcast_id}:{limit}:{offset}"

    def get_latest_episode(self, podcast_id: str) -> Optional[Dict[str, Any]]:
        """
        Get cached latest episode if available and not expired

        Args:
            podcast_id: The podcast ID

        Returns:
            Cached episode data or None if not found/expired
        """
        if not self._cache_enabled:
            return None

        cache_key = self._generate_latest_episode_key(podcast_id)

        with self._lock:
            if cache_key in self._cache:
                cached_item = self._cache[cache_key]
                current_time = time.time()

                # Check if cache entry has expired
                if current_time < cached_item["expires_at"]:
                    logger.debug(f"Latest episode cache HIT for podcast {podcast_id[:8]}...")
                    return cached_item["data"]
                else:
                    # Remove expired entry
                    logger.debug(f"Latest episode cache EXPIRED for podcast {podcast_id[:8]}...")
                    del self._cache[cache_key]
            else:
                logger.debug(f"Latest episode cache MISS for podcast {podcast_id[:8]}...")

        return None

    def set_latest_episode(self, podcast_id: str, episode_data: Dict[str, Any]) -> None:
        """
        Cache a latest episode with configured TTL

        Args:
            podcast_id: The podcast ID
            episode_data: The episode data to cache
        """
        if not self._cache_enabled:
            return

        cache_key = self._generate_latest_episode_key(podcast_id)
        current_time = time.time()
        expires_at = current_time + self._ttl_seconds

        with self._lock:
            # Implement simple LRU-like eviction if cache is full
            if len(self._cache) >= self._max_cache_size:
                # Remove oldest entry (simple FIFO for now)
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                logger.debug(f"Episode cache full, evicted oldest entry")

            self._cache[cache_key] = {
                "data": episode_data,
                "expires_at": expires_at,
                "created_at": current_time
            }
            logger.debug(f"Cached latest episode for podcast {podcast_id[:8]}..., TTL={self._ttl_seconds}s")

    def get_episodes_list(self, podcast_id: str, limit: int, offset: int) -> Optional[Tuple[List[Dict[str, Any]], int]]:
        """
        Get cached episode list if available and not expired

        Args:
            podcast_id: The podcast ID
            limit: Limit for pagination
            offset: Offset for pagination

        Returns:
            Tuple of (episodes list, total count) or None if not found/expired
        """
        if not self._cache_enabled:
            return None

        cache_key = self._generate_episodes_list_key(podcast_id, limit, offset)

        with self._lock:
            if cache_key in self._cache:
                cached_item = self._cache[cache_key]
                current_time = time.time()

                # Check if cache entry has expired
                if current_time < cached_item["expires_at"]:
                    logger.debug(f"Episodes list cache HIT for podcast {podcast_id[:8]}... (limit={limit}, offset={offset})")
                    return (cached_item["episodes"], cached_item["total_count"])
                else:
                    # Remove expired entry
                    logger.debug(f"Episodes list cache EXPIRED for podcast {podcast_id[:8]}...")
                    del self._cache[cache_key]
            else:
                logger.debug(f"Episodes list cache MISS for podcast {podcast_id[:8]}... (limit={limit}, offset={offset})")

        return None

    def set_episodes_list(self, podcast_id: str, limit: int, offset: int, episodes: List[Dict[str, Any]], total_count: int) -> None:
        """
        Cache an episode list with configured TTL

        Args:
            podcast_id: The podcast ID
            limit: Limit for pagination
            offset: Offset for pagination
            episodes: The episodes list to cache
            total_count: Total count of episodes
        """
        if not self._cache_enabled:
            return

        cache_key = self._generate_episodes_list_key(podcast_id, limit, offset)
        current_time = time.time()
        expires_at = current_time + self._ttl_seconds

        with self._lock:
            # Implement simple LRU-like eviction if cache is full
            if len(self._cache) >= self._max_cache_size:
                # Remove oldest entry (simple FIFO for now)
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                logger.debug(f"Episode cache full, evicted oldest entry")

            self._cache[cache_key] = {
                "episodes": episodes,
                "total_count": total_count,
                "expires_at": expires_at,
                "created_at": current_time
            }
            logger.debug(f"Cached episodes list for podcast {podcast_id[:8]}... (limit={limit}, offset={offset}, count={len(episodes)})")

    def invalidate_podcast(self, podcast_id: str) -> None:
        """
        Invalidate all cache entries for a specific podcast

        Args:
            podcast_id: The podcast ID to invalidate
        """
        with self._lock:
            # Find and remove all keys related to this podcast
            keys_to_remove = [
                key for key in self._cache.keys()
                if key.startswith(f"latest_episode:{podcast_id}") or key.startswith(f"episodes_list:{podcast_id}")
            ]

            for key in keys_to_remove:
                del self._cache[key]

            if keys_to_remove:
                logger.info(f"Invalidated {len(keys_to_remove)} cache entries for podcast {podcast_id[:8]}...")

    def invalidate_all(self) -> None:
        """
        Invalidate all cached episodes
        Use with caution - only for debugging or emergency cache flush
        """
        with self._lock:
            cache_size = len(self._cache)
            self._cache.clear()
            logger.warning(f"Invalidated entire podcast episode cache ({cache_size} entries)")

    def cleanup_expired(self) -> int:
        """
        Remove all expired entries from cache

        Returns:
            Number of expired entries removed
        """
        with self._lock:
            current_time = time.time()
            expired_keys = [
                key for key, cached_item in self._cache.items()
                if current_time >= cached_item["expires_at"]
            ]

            for key in expired_keys:
                del self._cache[key]

            if expired_keys:
                logger.info(f"Cleaned up {len(expired_keys)} expired podcast episode cache entries")

            return len(expired_keys)

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics

        Returns:
            Dict with cache stats
        """
        with self._lock:
            current_time = time.time()
            expired_count = sum(
                1 for item in self._cache.values()
                if current_time >= item["expires_at"]
            )

            latest_episode_count = sum(1 for key in self._cache.keys() if key.startswith("latest_episode:"))
            episodes_list_count = sum(1 for key in self._cache.keys() if key.startswith("episodes_list:"))

            return {
                "enabled": self._cache_enabled,
                "total_entries": len(self._cache),
                "expired_entries": expired_count,
                "active_entries": len(self._cache) - expired_count,
                "latest_episodes_cached": latest_episode_count,
                "episode_lists_cached": episodes_list_count,
                "ttl_minutes": self._ttl_minutes,
                "ttl_seconds": self._ttl_seconds,
                "max_size": self._max_cache_size
            }


# Global singleton instance
_podcast_episode_cache_service: Optional[PodcastEpisodeCacheService] = None

def get_podcast_episode_cache_service() -> PodcastEpisodeCacheService:
    """Get or create the global PodcastEpisodeCacheService instance"""
    global _podcast_episode_cache_service
    if _podcast_episode_cache_service is None:
        _podcast_episode_cache_service = PodcastEpisodeCacheService()
    return _podcast_episode_cache_service
