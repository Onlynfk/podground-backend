"""
Cache Cleanup Scheduler
Periodically cleans up expired cache entries and refreshes followed podcasts
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Any

from supabase_client import SupabaseClient
from podcast_search_service import get_podcast_search_service

logger = logging.getLogger(__name__)

class CacheCleanupScheduler:
    def __init__(self):
        try:
            self.supabase_client = SupabaseClient()
        except Exception as e:
            logger.warning(f"Could not initialize Supabase client: {e}")
            self.supabase_client = None
        
        self.listennotes_api_key = os.getenv('LISTENNOTES_API_KEY')
        self.podcast_service = None
        self.is_running = False
    
    def get_podcast_service(self):
        """Lazy load podcast service"""
        if not self.podcast_service and self.listennotes_api_key and self.supabase_client:
            self.podcast_service = get_podcast_search_service(
                self.supabase_client.service_client, 
                self.listennotes_api_key
            )
        return self.podcast_service
    
    async def cleanup_expired_cache(self) -> Dict[str, Any]:
        """Clean up expired cache entries"""
        try:
            podcast_service = self.get_podcast_service()
            if not podcast_service:
                logger.error("Podcast service not available - missing API key")
                return {"success": False, "error": "Service not available"}
            
            cleaned_count = await podcast_service.cleanup_expired_cache()
            
            logger.info(f"Cache cleanup completed: {cleaned_count} entries cleaned")
            return {
                "success": True,
                "cleaned_count": cleaned_count,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error during cache cleanup: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def refresh_followed_podcasts_cache(self) -> Dict[str, Any]:
        """Trigger refresh of followed podcasts cache"""
        try:
            if not self.supabase_client:
                return {"success": False, "error": "Supabase client not available"}
                
            # Call the database function to identify podcasts needing refresh
            result = self.supabase_client.service_client.rpc('refresh_followed_podcasts_cache').execute()
            
            logger.info("Followed podcasts cache refresh initiated")
            return {
                "success": True,
                "message": "Cache refresh initiated",
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error refreshing followed podcasts cache: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        try:
            if not self.supabase_client:
                return {"success": False, "error": "Supabase client not available"}
            # Search cache stats
            search_cache_result = self.supabase_client.service_client.table('podcast_search_cache') \
                .select('id', count='exact') \
                .execute()
            
            expired_search_result = self.supabase_client.service_client.table('podcast_search_cache') \
                .select('id', count='exact') \
                .lt('expires_at', datetime.utcnow().isoformat()) \
                .execute()
            
            # Episode cache stats
            episode_cache_result = self.supabase_client.service_client.table('episode_cache') \
                .select('id', count='exact') \
                .execute()
            
            expired_episode_result = self.supabase_client.service_client.table('episode_cache') \
                .select('id', count='exact') \
                .lt('expires_at', datetime.utcnow().isoformat()) \
                .execute()
            
            # Cached podcasts stats
            cached_podcasts_result = self.supabase_client.service_client.table('podcasts') \
                .select('id', count='exact') \
                .eq('is_cached', True) \
                .execute()
            
            expired_podcasts_result = self.supabase_client.service_client.table('podcasts') \
                .select('id', count='exact') \
                .eq('is_cached', True) \
                .lt('cache_expires_at', datetime.utcnow().isoformat()) \
                .execute()
            
            stats = {
                "search_cache": {
                    "total": search_cache_result.count or 0,
                    "expired": expired_search_result.count or 0
                },
                "episode_cache": {
                    "total": episode_cache_result.count or 0,
                    "expired": expired_episode_result.count or 0
                },
                "podcast_cache": {
                    "total": cached_podcasts_result.count or 0,
                    "expired": expired_podcasts_result.count or 0
                },
                "timestamp": datetime.utcnow().isoformat()
            }
            
            return {"success": True, "stats": stats}
            
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def run_maintenance_cycle(self) -> Dict[str, Any]:
        """Run a complete maintenance cycle"""
        results = {
            "started_at": datetime.utcnow().isoformat(),
            "tasks": {}
        }
        
        try:
            # 1. Get initial stats
            initial_stats = await self.get_cache_stats()
            results["tasks"]["initial_stats"] = initial_stats
            
            # 2. Clean up expired cache
            cleanup_result = await self.cleanup_expired_cache()
            results["tasks"]["cache_cleanup"] = cleanup_result
            
            # 3. Refresh followed podcasts
            refresh_result = await self.refresh_followed_podcasts_cache()
            results["tasks"]["cache_refresh"] = refresh_result
            
            # 4. Get final stats
            final_stats = await self.get_cache_stats()
            results["tasks"]["final_stats"] = final_stats
            
            results["completed_at"] = datetime.utcnow().isoformat()
            results["success"] = all(
                task.get("success", False) 
                for task in results["tasks"].values()
            )
            
            logger.info(f"Maintenance cycle completed: {results['success']}")
            return results
            
        except Exception as e:
            results["error"] = str(e)
            results["success"] = False
            results["completed_at"] = datetime.utcnow().isoformat()
            logger.error(f"Maintenance cycle failed: {e}")
            return results

# Global instance
cache_scheduler = CacheCleanupScheduler()

async def run_cache_cleanup():
    """Standalone function for external scheduling"""
    return await cache_scheduler.cleanup_expired_cache()

async def run_maintenance_cycle():
    """Standalone function for external scheduling"""
    return await cache_scheduler.run_maintenance_cycle()

if __name__ == "__main__":
    """Run maintenance cycle directly"""
    async def main():
        result = await run_maintenance_cycle()
        print(f"Maintenance result: {result}")
    
    asyncio.run(main())