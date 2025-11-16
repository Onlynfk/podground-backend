#!/usr/bin/env python3
"""
Daily Episode Cleanup Job
Maintains only the 20 most recent episodes per podcast
"""
import asyncio
import logging
import os
from datetime import datetime
from supabase import create_client, Client
from episode_import_service import get_episode_import_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DailyEpisodeCleanup:
    def __init__(self):
        # Initialize Supabase client
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        
        if not supabase_url or not supabase_key:
            raise ValueError("Missing required environment variables: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY")
        
        self.supabase = create_client(supabase_url, supabase_key)
        self.listennotes_api_key = os.getenv('LISTENNOTES_API_KEY')
        
        if not self.listennotes_api_key:
            raise ValueError("Missing required environment variable: LISTENNOTES_API_KEY")
        
        # Get episode import service
        self.episode_service = get_episode_import_service(self.supabase, self.listennotes_api_key)
    
    async def cleanup_all_podcasts(self, keep_count: int = 20) -> dict:
        """
        Clean up episodes for all podcasts, keeping only the most recent episodes
        """
        try:
            logger.info(f"Starting daily episode cleanup - keeping {keep_count} episodes per podcast")
            
            # Get all podcasts that have episodes
            podcasts_result = self.supabase.table('podcasts') \
                .select('id, title') \
                .execute()
            
            if not podcasts_result.data:
                logger.info("No podcasts found to clean up")
                return {"success": True, "podcasts_processed": 0, "total_deleted": 0}
            
            total_deleted = 0
            podcasts_processed = 0
            failed_podcasts = []
            
            for podcast in podcasts_result.data:
                podcast_id = podcast['id']
                podcast_title = podcast['title']
                
                try:
                    # Check if this podcast has episodes
                    episode_count = await self.episode_service.get_episode_count(podcast_id)
                    
                    if episode_count <= keep_count:
                        logger.debug(f"Podcast '{podcast_title}' has {episode_count} episodes - no cleanup needed")
                        continue
                    
                    # Clean up old episodes
                    deleted_count = await self.episode_service.cleanup_old_episodes(podcast_id, keep_count)
                    
                    if deleted_count > 0:
                        logger.info(f"Cleaned up {deleted_count} old episodes for podcast '{podcast_title}'")
                        total_deleted += deleted_count
                    
                    podcasts_processed += 1
                    
                except Exception as e:
                    logger.error(f"Failed to cleanup episodes for podcast '{podcast_title}': {e}")
                    failed_podcasts.append({"id": podcast_id, "title": podcast_title, "error": str(e)})
            
            # Log summary
            logger.info(f"Episode cleanup completed:")
            logger.info(f"  - Podcasts processed: {podcasts_processed}")
            logger.info(f"  - Total episodes deleted: {total_deleted}")
            logger.info(f"  - Failed podcasts: {len(failed_podcasts)}")
            
            if failed_podcasts:
                logger.warning("Failed to cleanup episodes for the following podcasts:")
                for failed in failed_podcasts:
                    logger.warning(f"  - {failed['title']} (ID: {failed['id']}): {failed['error']}")
            
            return {
                "success": True,
                "podcasts_processed": podcasts_processed,
                "total_deleted": total_deleted,
                "failed_podcasts": failed_podcasts
            }
            
        except Exception as e:
            logger.error(f"Error during episode cleanup: {e}")
            return {
                "success": False,
                "error": str(e),
                "podcasts_processed": 0,
                "total_deleted": 0
            }
    
    async def cleanup_specific_podcast(self, podcast_id: str, keep_count: int = 20) -> dict:
        """
        Clean up episodes for a specific podcast
        """
        try:
            # Get podcast details
            podcast_result = self.supabase.table('podcasts') \
                .select('title') \
                .eq('id', podcast_id) \
                .single() \
                .execute()
            
            if not podcast_result.data:
                return {"success": False, "error": "Podcast not found"}
            
            podcast_title = podcast_result.data['title']
            
            # Get current episode count
            episode_count = await self.episode_service.get_episode_count(podcast_id)
            
            if episode_count <= keep_count:
                logger.info(f"Podcast '{podcast_title}' has {episode_count} episodes - no cleanup needed")
                return {
                    "success": True,
                    "podcast_title": podcast_title,
                    "episodes_deleted": 0,
                    "episodes_remaining": episode_count
                }
            
            # Clean up old episodes
            deleted_count = await self.episode_service.cleanup_old_episodes(podcast_id, keep_count)
            
            logger.info(f"Cleaned up {deleted_count} old episodes for podcast '{podcast_title}'")
            
            return {
                "success": True,
                "podcast_title": podcast_title,
                "episodes_deleted": deleted_count,
                "episodes_remaining": keep_count
            }
            
        except Exception as e:
            logger.error(f"Error cleaning up podcast {podcast_id}: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_cleanup_stats(self) -> dict:
        """
        Get statistics about episodes that could be cleaned up
        """
        try:
            # Get all podcasts with episode counts
            stats = {
                "total_podcasts": 0,
                "podcasts_needing_cleanup": 0,
                "total_episodes": 0,
                "episodes_to_delete": 0,
                "podcast_details": []
            }
            
            podcasts_result = self.supabase.table('podcasts') \
                .select('id, title') \
                .execute()
            
            if not podcasts_result.data:
                return stats
            
            stats["total_podcasts"] = len(podcasts_result.data)
            
            for podcast in podcasts_result.data:
                podcast_id = podcast['id']
                podcast_title = podcast['title']
                
                episode_count = await self.episode_service.get_episode_count(podcast_id)
                stats["total_episodes"] += episode_count
                
                if episode_count > 20:
                    episodes_to_delete = episode_count - 20
                    stats["podcasts_needing_cleanup"] += 1
                    stats["episodes_to_delete"] += episodes_to_delete
                    
                    stats["podcast_details"].append({
                        "id": podcast_id,
                        "title": podcast_title,
                        "current_episodes": episode_count,
                        "episodes_to_delete": episodes_to_delete
                    })
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting cleanup stats: {e}")
            return {"error": str(e)}

async def main():
    """Main function for running the cleanup job"""
    try:
        cleanup_job = DailyEpisodeCleanup()
        
        # Check if we should run stats only
        import sys
        if len(sys.argv) > 1 and sys.argv[1] == "--stats":
            stats = await cleanup_job.get_cleanup_stats()
            print("Episode Cleanup Statistics:")
            print(f"Total podcasts: {stats.get('total_podcasts', 0)}")
            print(f"Podcasts needing cleanup: {stats.get('podcasts_needing_cleanup', 0)}")
            print(f"Total episodes: {stats.get('total_episodes', 0)}")
            print(f"Episodes to delete: {stats.get('episodes_to_delete', 0)}")
            return
        
        # Run full cleanup
        result = await cleanup_job.cleanup_all_podcasts()
        
        if result["success"]:
            print(f"Cleanup completed successfully:")
            print(f"  Podcasts processed: {result['podcasts_processed']}")
            print(f"  Total episodes deleted: {result['total_deleted']}")
        else:
            print(f"Cleanup failed: {result.get('error', 'Unknown error')}")
            exit(1)
            
    except Exception as e:
        logger.error(f"Fatal error in cleanup job: {e}")
        exit(1)

if __name__ == "__main__":
    asyncio.run(main())