-- Migration: Add indexes for global search optimization
-- Description: Creates indexes to improve search performance across all searchable tables
-- Created: 2025-10-18

-- =============================================================================
-- PODCAST SEARCHES
-- =============================================================================

-- Index for podcast title searches (case-insensitive)
CREATE INDEX IF NOT EXISTS idx_podcasts_title_lower
ON podcasts (LOWER(title));

-- Composite index for active podcasts with title search
CREATE INDEX IF NOT EXISTS idx_podcasts_title_active
ON podcasts (LOWER(title), id)
WHERE is_deleted = FALSE OR is_deleted IS NULL;

-- =============================================================================
-- EPISODE SEARCHES
-- =============================================================================

-- Index for episode title searches (case-insensitive)
CREATE INDEX IF NOT EXISTS idx_episodes_title_lower
ON episodes (LOWER(title));

-- Composite index for episodes with podcast relationship
CREATE INDEX IF NOT EXISTS idx_episodes_title_podcast
ON episodes (LOWER(title), podcast_id, id);

-- =============================================================================
-- POST SEARCHES
-- =============================================================================

-- Index for post content searches (case-insensitive)
CREATE INDEX IF NOT EXISTS idx_posts_content_lower
ON posts (LOWER(content))
WHERE is_deleted = FALSE;

-- Composite index for active posts with timestamp for sorting
CREATE INDEX IF NOT EXISTS idx_posts_content_active_timestamp
ON posts (LOWER(content), created_at DESC, id)
WHERE is_deleted = FALSE;

-- Index for user's posts
CREATE INDEX IF NOT EXISTS idx_posts_user_id
ON posts (user_id, created_at DESC)
WHERE is_deleted = FALSE;

-- =============================================================================
-- COMMENT SEARCHES
-- =============================================================================

-- Index for comment content searches (case-insensitive)
CREATE INDEX IF NOT EXISTS idx_comments_content_lower
ON post_comments (LOWER(content))
WHERE is_deleted = FALSE;

-- Composite index for active comments with timestamp
CREATE INDEX IF NOT EXISTS idx_comments_content_active_timestamp
ON post_comments (LOWER(content), created_at DESC, id)
WHERE is_deleted = FALSE;

-- Index for comment post relationship
CREATE INDEX IF NOT EXISTS idx_comments_post_id
ON post_comments (post_id, created_at DESC)
WHERE is_deleted = FALSE;

-- =============================================================================
-- MESSAGE SEARCHES
-- =============================================================================

-- Index for message content searches (case-insensitive)
CREATE INDEX IF NOT EXISTS idx_messages_content_lower
ON messages (LOWER(content))
WHERE is_deleted = FALSE;

-- Composite index for messages by conversation
CREATE INDEX IF NOT EXISTS idx_messages_conversation_content
ON messages (conversation_id, LOWER(content), created_at DESC)
WHERE is_deleted = FALSE;

-- Index for conversation participants (for filtering user's conversations)
CREATE INDEX IF NOT EXISTS idx_conversation_participants_user
ON conversation_participants (user_id, conversation_id)
WHERE left_at IS NULL;

-- =============================================================================
-- EVENT SEARCHES
-- =============================================================================

-- Index for event title searches (case-insensitive)
CREATE INDEX IF NOT EXISTS idx_events_title_lower
ON events (LOWER(title));

-- Composite index for events with date sorting
CREATE INDEX IF NOT EXISTS idx_events_title_date
ON events (LOWER(title), event_date DESC, id);

-- Index for event creator
CREATE INDEX IF NOT EXISTS idx_events_creator_id
ON events (creator_id, event_date DESC);

-- =============================================================================
-- USER SEARCHES
-- =============================================================================

-- Index for first name searches (case-insensitive)
CREATE INDEX IF NOT EXISTS idx_user_profiles_first_name_lower
ON user_profiles (LOWER(first_name));

-- Index for last name searches (case-insensitive)
CREATE INDEX IF NOT EXISTS idx_user_profiles_last_name_lower
ON user_profiles (LOWER(last_name));

-- Composite index for full name searches
CREATE INDEX IF NOT EXISTS idx_user_profiles_name_composite
ON user_profiles (LOWER(first_name), LOWER(last_name), user_id);

-- =============================================================================
-- POST MEDIA (for fetching images)
-- =============================================================================

-- Index for fetching first image of posts
CREATE INDEX IF NOT EXISTS idx_post_media_post_image
ON post_media (post_id, position)
WHERE type = 'image';

-- =============================================================================
-- ADDITIONAL PERFORMANCE INDEXES
-- =============================================================================

-- Index for podcast follows (used in personalized feed)
CREATE INDEX IF NOT EXISTS idx_podcast_followers_user
ON podcast_followers (user_id, podcast_id);

-- Index for user connections (used in activity feed)
CREATE INDEX IF NOT EXISTS idx_user_connections_status
ON user_connections (user_id, status)
WHERE status = 'accepted';

-- =============================================================================
-- FUTURE: FULL-TEXT SEARCH PREPARATION (commented out for now)
-- =============================================================================

-- Uncomment these when ready to migrate to PostgreSQL Full-Text Search (FTS)
-- This will provide better search performance and ranking at scale

-- Add tsvector columns for full-text search
-- ALTER TABLE podcasts ADD COLUMN IF NOT EXISTS search_vector tsvector;
-- ALTER TABLE episodes ADD COLUMN IF NOT EXISTS search_vector tsvector;
-- ALTER TABLE posts ADD COLUMN IF NOT EXISTS search_vector tsvector;
-- ALTER TABLE post_comments ADD COLUMN IF NOT EXISTS search_vector tsvector;
-- ALTER TABLE messages ADD COLUMN IF NOT EXISTS search_vector tsvector;
-- ALTER TABLE events ADD COLUMN IF NOT EXISTS search_vector tsvector;
-- ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS search_vector tsvector;

-- Create triggers to maintain tsvector columns
-- CREATE TRIGGER podcasts_search_vector_update
-- BEFORE INSERT OR UPDATE ON podcasts
-- FOR EACH ROW EXECUTE FUNCTION
-- tsvector_update_trigger(search_vector, 'pg_catalog.english', title, description);

-- CREATE TRIGGER episodes_search_vector_update
-- BEFORE INSERT OR UPDATE ON episodes
-- FOR EACH ROW EXECUTE FUNCTION
-- tsvector_update_trigger(search_vector, 'pg_catalog.english', title, description);

-- Create GIN indexes for fast full-text search
-- CREATE INDEX IF NOT EXISTS idx_podcasts_search_vector ON podcasts USING GIN(search_vector);
-- CREATE INDEX IF NOT EXISTS idx_episodes_search_vector ON episodes USING GIN(search_vector);
-- CREATE INDEX IF NOT EXISTS idx_posts_search_vector ON posts USING GIN(search_vector);
-- CREATE INDEX IF NOT EXISTS idx_comments_search_vector ON post_comments USING GIN(search_vector);
-- CREATE INDEX IF NOT EXISTS idx_messages_search_vector ON messages USING GIN(search_vector);
-- CREATE INDEX IF NOT EXISTS idx_events_search_vector ON events USING GIN(search_vector);
-- CREATE INDEX IF NOT EXISTS idx_user_profiles_search_vector ON user_profiles USING GIN(search_vector);

-- =============================================================================
-- VERIFICATION QUERIES
-- =============================================================================

-- Run these queries to verify indexes were created successfully:
-- SELECT schemaname, tablename, indexname FROM pg_indexes WHERE tablename IN ('podcasts', 'episodes', 'posts', 'post_comments', 'messages', 'events', 'user_profiles') ORDER BY tablename, indexname;

-- Check index usage stats (run after some search queries):
-- SELECT schemaname, tablename, indexname, idx_scan, idx_tup_read, idx_tup_fetch FROM pg_stat_user_indexes WHERE tablename IN ('podcasts', 'episodes', 'posts', 'post_comments', 'messages', 'events', 'user_profiles') ORDER BY idx_scan DESC;
