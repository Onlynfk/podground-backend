"""
User Profile caching service with configurable TTL
Provides in-memory caching for user profiles to reduce database queries
"""

import logging
import time
import os
from typing import Optional, Dict, Any, List
from threading import Lock

logger = logging.getLogger(__name__)

class UserProfileCacheService:
    """Simple in-memory cache for user profiles with TTL support"""

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()
        # Get cache TTL from environment variable (default: 60 minutes)
        self._ttl_minutes = int(os.getenv('USER_PROFILE_CACHE_TTL_MINUTES', '60'))
        self._ttl_seconds = self._ttl_minutes * 60
        # Maximum cache size to prevent memory issues
        self._max_cache_size = int(os.getenv('USER_PROFILE_CACHE_MAX_SIZE', '5000'))
        logger.info(f"User profile cache initialized with TTL={self._ttl_minutes}min ({self._ttl_seconds}s), max_size={self._max_cache_size}")

    def _generate_cache_key(self, user_id: str) -> str:
        """
        Generate a cache key from user ID

        Args:
            user_id: The user ID

        Returns:
            Cache key string
        """
        return f"user_profile:{user_id}"

    def get(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get cached user profile if available and not expired

        Args:
            user_id: The user ID

        Returns:
            Cached user profile or None if not found/expired
        """
        cache_key = self._generate_cache_key(user_id)

        with self._lock:
            if cache_key in self._cache:
                cached_item = self._cache[cache_key]
                current_time = time.time()

                # Check if cache entry has expired
                if current_time < cached_item["expires_at"]:
                    logger.debug(f"Profile cache HIT for user {user_id}")
                    return cached_item["data"]
                else:
                    # Remove expired entry
                    logger.debug(f"Profile cache EXPIRED for user {user_id}")
                    del self._cache[cache_key]
            else:
                logger.debug(f"Profile cache MISS for user {user_id}")

        return None

    def set(self, user_id: str, profile_data: Dict[str, Any]) -> None:
        """
        Cache a user profile with configured TTL

        Args:
            user_id: The user ID
            profile_data: The user profile data to cache
        """
        cache_key = self._generate_cache_key(user_id)
        current_time = time.time()
        expires_at = current_time + self._ttl_seconds

        with self._lock:
            # Implement simple LRU-like eviction if cache is full
            if len(self._cache) >= self._max_cache_size:
                # Remove oldest entry (simple FIFO for now)
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                logger.debug(f"Profile cache full, evicted oldest entry: {oldest_key}")

            self._cache[cache_key] = {
                "data": profile_data,
                "expires_at": expires_at,
                "created_at": current_time
            }
            logger.debug(f"Cached profile for user {user_id}, TTL={self._ttl_seconds}s")

    def get_batch(self, user_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Get multiple cached user profiles

        Args:
            user_ids: List of user IDs

        Returns:
            Dictionary mapping user_id to profile data for cached profiles only
        """
        if not user_ids:
            return {}

        cached_profiles = {}
        current_time = time.time()

        with self._lock:
            for user_id in user_ids:
                cache_key = self._generate_cache_key(user_id)

                if cache_key in self._cache:
                    cached_item = self._cache[cache_key]

                    # Check if cache entry has expired
                    if current_time < cached_item["expires_at"]:
                        cached_profiles[user_id] = cached_item["data"]
                    else:
                        # Remove expired entry
                        del self._cache[cache_key]

        if cached_profiles:
            logger.debug(f"Profile batch cache: {len(cached_profiles)}/{len(user_ids)} found")
        else:
            logger.debug(f"Profile batch cache: 0/{len(user_ids)} found (all MISS)")

        return cached_profiles

    def set_batch(self, profiles: List[Dict[str, Any]]) -> None:
        """
        Cache multiple user profiles

        Args:
            profiles: List of profile dictionaries (must contain 'user_id' or 'id' field)
        """
        if not profiles:
            return

        current_time = time.time()
        expires_at = current_time + self._ttl_seconds
        cached_count = 0

        with self._lock:
            for profile in profiles:
                # Accept either 'user_id' or 'id' field
                user_id = profile.get('user_id') or profile.get('id')
                if not user_id:
                    logger.warning("Profile missing user_id/id field, skipping cache")
                    continue

                cache_key = self._generate_cache_key(user_id)

                # Check cache size limit
                if len(self._cache) >= self._max_cache_size and cache_key not in self._cache:
                    # Remove oldest entry
                    oldest_key = next(iter(self._cache))
                    del self._cache[oldest_key]

                self._cache[cache_key] = {
                    "data": profile,
                    "expires_at": expires_at,
                    "created_at": current_time
                }
                cached_count += 1

        logger.debug(f"Cached {cached_count} profiles in batch")

    def invalidate(self, user_id: str) -> None:
        """
        Invalidate cache for a specific user

        Args:
            user_id: The user ID to invalidate
        """
        cache_key = self._generate_cache_key(user_id)

        with self._lock:
            if cache_key in self._cache:
                del self._cache[cache_key]
                logger.info(f"Invalidated profile cache for user {user_id}")
            else:
                logger.debug(f"No cache entry to invalidate for user {user_id}")

    def invalidate_all(self) -> None:
        """
        Invalidate all cached user profiles
        Use with caution - only for debugging or emergency cache flush
        """
        with self._lock:
            cache_size = len(self._cache)
            self._cache.clear()
            logger.warning(f"Invalidated entire user profile cache ({cache_size} entries)")

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
                logger.info(f"Cleaned up {len(expired_keys)} expired user profile cache entries")

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

    # ===== Notification Count Caching Methods =====

    def _generate_notification_count_key(self, user_id: str) -> str:
        """Generate cache key for notification count"""
        return f"notification_count:{user_id}"

    def get_notification_count(self, user_id: str) -> Optional[int]:
        """
        Get cached unread notification count

        Args:
            user_id: The user ID

        Returns:
            Cached count or None if not found/expired
        """
        cache_key = self._generate_notification_count_key(user_id)

        with self._lock:
            if cache_key in self._cache:
                cached_item = self._cache[cache_key]
                current_time = time.time()

                if current_time < cached_item["expires_at"]:
                    logger.debug(f"Notification count cache HIT for user {user_id}")
                    return cached_item["count"]
                else:
                    # Remove expired entry
                    logger.debug(f"Notification count cache EXPIRED for user {user_id}")
                    del self._cache[cache_key]
            else:
                logger.debug(f"Notification count cache MISS for user {user_id}")

        return None

    def set_notification_count(self, user_id: str, count: int, ttl_seconds: Optional[int] = None) -> None:
        """
        Cache unread notification count

        Args:
            user_id: The user ID
            count: The unread notification count
            ttl_seconds: Optional TTL (defaults to env var NOTIFICATION_COUNT_CACHE_TTL_MINUTES)
        """
        cache_key = self._generate_notification_count_key(user_id)
        current_time = time.time()

        # Use configurable TTL for notification counts (default 5 minutes)
        if ttl_seconds is None:
            ttl_minutes = int(os.getenv('NOTIFICATION_COUNT_CACHE_TTL_MINUTES', '5'))
            notification_ttl = ttl_minutes * 60
        else:
            notification_ttl = ttl_seconds

        expires_at = current_time + notification_ttl

        with self._lock:
            # Check cache size limit
            if len(self._cache) >= self._max_cache_size and cache_key not in self._cache:
                # Remove oldest entry
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]

            self._cache[cache_key] = {
                "count": count,
                "expires_at": expires_at,
                "created_at": current_time
            }
            logger.debug(f"Cached notification count for user {user_id}: {count}")

    def increment_notification_count(self, user_id: str) -> None:
        """
        Increment cached notification count (when new notification created)

        Args:
            user_id: The user ID
        """
        cache_key = self._generate_notification_count_key(user_id)

        with self._lock:
            if cache_key in self._cache:
                cached_item = self._cache[cache_key]
                current_time = time.time()

                # Only increment if not expired
                if current_time < cached_item["expires_at"]:
                    cached_item["count"] += 1
                    logger.debug(f"Incremented notification count for user {user_id} to {cached_item['count']}")
                else:
                    # Expired, remove it
                    del self._cache[cache_key]

    def decrement_notification_count(self, user_id: str) -> None:
        """
        Decrement cached notification count (when notification marked as read)

        Args:
            user_id: The user ID
        """
        cache_key = self._generate_notification_count_key(user_id)

        with self._lock:
            if cache_key in self._cache:
                cached_item = self._cache[cache_key]
                current_time = time.time()

                # Only decrement if not expired
                if current_time < cached_item["expires_at"]:
                    cached_item["count"] = max(0, cached_item["count"] - 1)
                    logger.debug(f"Decremented notification count for user {user_id} to {cached_item['count']}")
                else:
                    # Expired, remove it
                    del self._cache[cache_key]

    def invalidate_notification_count(self, user_id: str) -> None:
        """
        Invalidate cached notification count

        Args:
            user_id: The user ID
        """
        cache_key = self._generate_notification_count_key(user_id)

        with self._lock:
            if cache_key in self._cache:
                del self._cache[cache_key]
                logger.debug(f"Invalidated notification count cache for user {user_id}")


# Global singleton instance
_user_profile_cache_service: Optional[UserProfileCacheService] = None

def get_user_profile_cache_service() -> UserProfileCacheService:
    """Get or create the global UserProfileCacheService instance"""
    global _user_profile_cache_service
    if _user_profile_cache_service is None:
        _user_profile_cache_service = UserProfileCacheService()
    return _user_profile_cache_service
