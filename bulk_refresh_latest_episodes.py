#!/usr/bin/env python3
"""
Bulk refresh latest episodes for all featured podcasts to ensure they show the actual latest episodes
"""

import asyncio
import os
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add the current directory to Python path
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from podcast_service import PodcastDiscoveryService
from supabase_client import SupabaseClient

async def bulk_refresh_featured_podcasts():
    """Bulk refresh latest episodes for all featured podcasts"""
    
    client = SupabaseClient()
    service = PodcastDiscoveryService(client.service_client)
    supabase = client.service_client
    
    print("🔄 Starting bulk refresh of latest episodes for featured podcasts...\n")
    
    try:
        # Get all featured podcasts
        featured_result = supabase.table('podcasts') \
            .select('id, title, listennotes_id, latest_episode_id') \
            .eq('is_featured', True) \
            .execute()
        
        if not featured_result.data:
            print("No featured podcasts found!")
            return
        
        featured_podcasts = featured_result.data
        total_podcasts = len(featured_podcasts)
        print(f"Found {total_podcasts} featured podcasts to refresh\n")
        
        success_count = 0
        error_count = 0
        
        for i, podcast in enumerate(featured_podcasts, 1):
            podcast_id = podcast['id']
            title = podcast['title']
            listennotes_id = podcast['listennotes_id']
            current_latest_id = podcast['latest_episode_id']
            
            print(f"[{i}/{total_podcasts}] Processing: {title[:50]}...")
            print(f"  Podcast ID: {podcast_id}")
            print(f"  ListenNotes ID: {listennotes_id}")
            
            if not listennotes_id:
                print(f"  ⚠️  No ListenNotes ID, skipping")
                error_count += 1
                continue
            
            try:
                # Get current latest episode details for comparison
                current_episode_title = "None"
                if current_latest_id:
                    current_ep = supabase.table('episodes') \
                        .select('title, listennotes_id') \
                        .eq('id', current_latest_id) \
                        .single() \
                        .execute()
                    
                    if current_ep.data:
                        current_episode_title = current_ep.data['title'][:40] + "..."
                
                print(f"  Current episode: {current_episode_title}")
                
                # Force refresh from API
                print(f"  🔄 Refreshing from ListenNotes API...")
                fresh_episode = await service._refresh_latest_episode_from_api(podcast_id, listennotes_id)
                
                if fresh_episode:
                    new_title = fresh_episode.get('title', 'Unknown')[:40] + "..."
                    new_ln_id = fresh_episode.get('listennotes_id')
                    
                    print(f"  ✅ Updated to: {new_title}")
                    print(f"  🆔 New Episode LN ID: {new_ln_id}")
                    success_count += 1
                else:
                    print(f"  ❌ Failed to refresh (no episode returned)")
                    error_count += 1
                
            except Exception as e:
                print(f"  ❌ Error refreshing: {str(e)}")
                error_count += 1
            
            print()  # Add spacing between podcasts
        
        # Summary
        print("=" * 60)
        print("🏁 BULK REFRESH COMPLETE")
        print("=" * 60)
        print(f"Total podcasts processed: {total_podcasts}")
        print(f"✅ Successfully refreshed: {success_count}")
        print(f"❌ Failed to refresh: {error_count}")
        print(f"📊 Success rate: {(success_count/total_podcasts)*100:.1f}%")
        
        if success_count > 0:
            print(f"\n🎉 {success_count} podcasts now have fresh latest episodes!")
        
        if error_count > 0:
            print(f"\n⚠️  {error_count} podcasts could not be refreshed. Check logs above for details.")
        
        return success_count > 0
        
    except Exception as e:
        logger.error(f"Bulk refresh failed: {e}")
        return False

async def verify_refresh_results():
    """Verify that the refresh worked by checking a few podcasts"""
    
    client = SupabaseClient()
    service = PodcastDiscoveryService(client.service_client)
    
    print("\n🔍 Verifying refresh results...")

    # Get a few featured podcasts to verify
    featured, _ = await service.get_featured_podcasts(limit=3)
    
    for i, podcast in enumerate(featured, 1):
        title = podcast.get('title', 'Unknown')[:50]
        
        if 'most_recent_episode' in podcast:
            episode = podcast['most_recent_episode']
            episode_title = episode.get('title', 'Unknown')[:40]
            pub_date = episode.get('published_at', 'Unknown')
            
            print(f"{i}. {title}...")
            print(f"   Latest: {episode_title}... ({pub_date})")
        else:
            print(f"{i}. {title}... ❌ No latest episode found")

if __name__ == "__main__":
    async def main():
        success = await bulk_refresh_featured_podcasts()
        
        if success:
            await verify_refresh_results()
            print("\n✅ Bulk refresh completed successfully!")
        else:
            print("\n❌ Bulk refresh failed!")
            sys.exit(1)
    
    asyncio.run(main())