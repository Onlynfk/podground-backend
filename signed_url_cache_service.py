"""
Signed URL caching service with configurable TTL
Provides in-memory caching for pre-signed URLs to avoid regenerating them
"""

import logging
import time
import os
from typing import Optional, Dict, Any
from threading import Lock

logger = logging.getLogger(__name__)

class SignedUrlCacheService:
    """Simple in-memory cache for pre-signed URLs with TTL support"""

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()
        # Get cache TTL from environment variable (default: 60 minutes)
        self._ttl_minutes = int(os.getenv('SIGNED_URL_TTL_MINUTES', '60'))
        self._ttl_seconds = self._ttl_minutes * 60
        # Maximum cache size to prevent memory issues
        self._max_cache_size = int(os.getenv('SIGNED_URL_CACHE_MAX_SIZE', '10000'))
        logger.info(f"Signed URL cache initialized with TTL={self._ttl_minutes}min ({self._ttl_seconds}s), max_size={self._max_cache_size}")

    def _generate_cache_key(self, storage_path: str, expiry_seconds: int) -> str:
        """
        Generate a cache key from storage path and expiry time

        Args:
            storage_path: The R2 storage path (e.g., 'avatars/user123/image.jpg')
            expiry_seconds: URL expiration time in seconds

        Returns:
            Cache key string
        """
        # Include expiry in the key so different expiry times are cached separately
        return f"signed_url:{storage_path}:{expiry_seconds}"

    def get(self, storage_path: str, expiry_seconds: int = 3600) -> Optional[str]:
        """
        Get cached signed URL if available and not expired

        Args:
            storage_path: The R2 storage path (e.g., 'avatars/user123/image.jpg')
            expiry_seconds: URL expiration time in seconds (default: 3600 = 1 hour)

        Returns:
            Cached signed URL or None if not found/expired
        """
        cache_key = self._generate_cache_key(storage_path, expiry_seconds)

        with self._lock:
            if cache_key in self._cache:
                cached_item = self._cache[cache_key]
                current_time = time.time()

                # Check if cache entry has expired
                if current_time < cached_item["expires_at"]:
                    logger.debug(f"Cache HIT for {storage_path} (expiry={expiry_seconds}s)")
                    return cached_item["url"]
                else:
                    # Remove expired entry
                    logger.debug(f"Cache EXPIRED for {storage_path} (expiry={expiry_seconds}s)")
                    del self._cache[cache_key]
            else:
                logger.debug(f"Cache MISS for {storage_path} (expiry={expiry_seconds}s)")

        return None

    def set(self, storage_path: str, signed_url: str, expiry_seconds: int = 3600) -> None:
        """
        Cache a signed URL with TTL matching the URL's expiration time

        Args:
            storage_path: The R2 storage path
            signed_url: The pre-signed URL to cache
            expiry_seconds: URL expiration time in seconds (default: 3600 = 1 hour)
        """
        cache_key = self._generate_cache_key(storage_path, expiry_seconds)
        current_time = time.time()

        # Use the minimum of the URL expiry and the configured cache TTL
        # This ensures the cache doesn't hold expired URLs
        cache_ttl = min(expiry_seconds, self._ttl_seconds)
        expires_at = current_time + cache_ttl

        with self._lock:
            # Implement simple LRU-like eviction if cache is full
            if len(self._cache) >= self._max_cache_size:
                # Remove oldest entry (simple FIFO for now)
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                logger.debug(f"Cache full, evicted oldest entry: {oldest_key}")

            self._cache[cache_key] = {
                "url": signed_url,
                "expires_at": expires_at,
                "created_at": current_time,
                "url_expiry_seconds": expiry_seconds
            }
            logger.debug(f"Cached signed URL for {storage_path}, cache TTL={cache_ttl}s, URL expiry={expiry_seconds}s")

    def invalidate(self, storage_path: Optional[str] = None) -> None:
        """
        Invalidate cache entries for a storage path or all entries

        Args:
            storage_path: If provided, invalidate only entries for this storage path.
                         If None, invalidate all entries.
        """
        with self._lock:
            if storage_path is None:
                # Clear entire cache
                cache_size = len(self._cache)
                self._cache.clear()
                logger.info(f"Invalidated entire signed URL cache ({cache_size} entries)")
            else:
                # Invalidate entries for specific storage path (all expiry variants)
                keys_to_remove = [
                    key for key in self._cache.keys()
                    if key.startswith(f"signed_url:{storage_path}:")
                ]

                for key in keys_to_remove:
                    del self._cache[key]

                if keys_to_remove:
                    logger.info(f"Invalidated {len(keys_to_remove)} cache entries for {storage_path}")

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
                logger.info(f"Cleaned up {len(expired_keys)} expired signed URL cache entries")

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

            return {
                "total_entries": len(self._cache),
                "expired_entries": expired_count,
                "active_entries": len(self._cache) - expired_count,
                "ttl_minutes": self._ttl_minutes,
                "ttl_seconds": self._ttl_seconds,
                "max_size": self._max_cache_size
            }


# Global singleton instance
_signed_url_cache_service: Optional[SignedUrlCacheService] = None

def get_signed_url_cache_service() -> SignedUrlCacheService:
    """Get or create the global SignedUrlCacheService instance"""
    global _signed_url_cache_service
    if _signed_url_cache_service is None:
        _signed_url_cache_service = SignedUrlCacheService()
    return _signed_url_cache_service
