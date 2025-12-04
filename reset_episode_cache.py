#!/usr/bin/env python3
"""
Reset the episode cache by clearing latest_episode_updated_at timestamps
This forces all podcasts to refresh their episodes on next access
"""

import sys
import os
from dotenv import load_dotenv

load_dotenv()

# Configuration
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_SERVICE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("❌ SUPABASE_URL or SUPABASE_SERVICE_KEY not set in .env")
    sys.exit(1)

try:
    from supabase import create_client
except ImportError:
    print("❌ Install supabase: pip install supabase")
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

print("🔄 Resetting episode cache for all podcasts...")
print(f"Connected to: {SUPABASE_URL}")
print()

# Check if latest_episode_updated_at column exists
sample = supabase.table('podcasts').select('*').limit(1).execute()
has_timestamp_column = False
if sample.data and len(sample.data) > 0:
    has_timestamp_column = 'latest_episode_updated_at' in sample.data[0]

print(f"Timestamp column exists: {has_timestamp_column}")
print()

response = input("Reset cache by clearing episode IDs? (yes/no): ")

if response.lower() == 'yes':
    try:
        if has_timestamp_column:
            # Clear both latest_episode_id and timestamp
            result = supabase.table('podcasts').update({
                'latest_episode_id': None,
                'latest_episode_updated_at': None
            }).neq('id', '00000000-0000-0000-0000-000000000000').execute()
            print("✅ Cleared latest_episode_id and latest_episode_updated_at")
        else:
            # Only clear latest_episode_id (timestamp column doesn't exist)
            result = supabase.table('podcasts').update({
                'latest_episode_id': None
            }).neq('id', '00000000-0000-0000-0000-000000000000').execute()
            print("✅ Cleared latest_episode_id")
            print("ℹ️  Note: latest_episode_updated_at column doesn't exist yet")
            print("   Run migration 057_add_latest_episode_timestamp.sql to add it")

        count = len(result.data) if result.data else 0
        print(f"✅ Reset cache for {count} podcasts")
        print("Next time episodes are accessed, they will be refreshed from ListenNotes API")

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
else:
    print("Cancelled")
