#!/usr/bin/env python3
"""
Import episodes for all featured podcasts from ListenNotes API
Run this once to populate episodes for featured podcasts
"""
import os
import asyncio
from dotenv import load_dotenv
from supabase import create_client
from episode_import_service import EpisodeImportService
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

async def import_featured_podcast_episodes():
    """Import episodes for all featured podcasts"""

    # Get credentials
    supabase_url = 'https://aoopeqkhpljrnfgwpraf.supabase.co'
    supabase_key = 'sb_secret_cnnNH2fs6GXb_IBoNQmcXw_fFrVPQ9b'
    listennotes_api_key = '4dae02ace69d4fedb4c7334db6aa9dbd'

    if not all([supabase_url, supabase_key, listennotes_api_key]):
        logger.error("Missing required environment variables")
        return

    # Initialize clients
    supabase = create_client(supabase_url, supabase_key)
    episode_service = EpisodeImportService(supabase, listennotes_api_key)

    print("=" * 60)
    print("IMPORT EPISODES FOR FEATURED PODCASTS")
    print("=" * 60)

    # Get all featured podcasts
    print("\n1. Fetching featured podcasts...")
    result = supabase.table('podcasts') \
        .select('id, listennotes_id, title') \
        .eq('is_featured', True) \
        .order('featured_priority', desc=True) \
        .execute()

    featured_podcasts = result.data or []

    if not featured_podcasts:
        print("❌ No featured podcasts found!")
        return

    print(f"✅ Found {len(featured_podcasts)} featured podcasts\n")

    # Import episodes for each podcast
    total_episodes_imported = 0
    successful_imports = 0
    failed_imports = 0

    print("2. Importing episodes from ListenNotes API...\n")

    for i, podcast in enumerate(featured_podcasts, 1):
        podcast_id = podcast['id']
        listennotes_id = podcast['listennotes_id']
        title = podcast['title']

        print(f"[{i}/{len(featured_podcasts)}] {title[:50]}...")

        if not listennotes_id:
            print(f"   ⚠️  No ListenNotes ID - skipping")
            failed_imports += 1
            continue

        try:
            # Check if episodes already exist
            existing_count = await episode_service.get_episode_count(podcast_id)

            if existing_count >= 100:
                print(f"   ℹ️  Already has {existing_count} episodes (full import) - skipping")
                successful_imports += 1
                continue

            # Import up to 100 recent episodes (upsert will handle any duplicates)
            print(f"   📥 Currently has {existing_count} episodes, importing up to 100...")
            episodes = await episode_service.import_recent_episodes(
                podcast_id=podcast_id,
                listennotes_id=listennotes_id,
                limit=100
            )

            if episodes:
                episode_count = len(episodes)
                new_count = await episode_service.get_episode_count(podcast_id)
                total_episodes_imported += (new_count - existing_count)
                successful_imports += 1
                print(f"   ✅ Now has {new_count} total episodes ({new_count - existing_count} new)")
            else:
                failed_imports += 1
                print(f"   ❌ Failed to import episodes")

        except Exception as e:
            failed_imports += 1
            print(f"   ❌ Error: {str(e)}")

    print("\n" + "=" * 60)
    print("IMPORT COMPLETE")
    print("=" * 60)
    print(f"\n📊 Summary:")
    print(f"   Total featured podcasts: {len(featured_podcasts)}")
    print(f"   Successful imports: {successful_imports}")
    print(f"   Failed imports: {failed_imports}")
    print(f"   Total episodes imported: {total_episodes_imported}")
    print(f"   Average episodes per podcast: {total_episodes_imported / successful_imports if successful_imports > 0 else 0:.1f}")

if __name__ == "__main__":
    asyncio.run(import_featured_podcast_episodes())
