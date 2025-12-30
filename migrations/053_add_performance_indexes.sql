-- Migration: Add missing performance indexes
-- Description: Adds indexes for commonly queried columns to improve performance
-- Created: 2025-11-15

-- =============================================================================
-- NOTIFICATIONS TABLE
-- =============================================================================

-- Index for getting unread notifications count (very frequent query)
-- Used in: notification_service.py get_unread_count()
CREATE INDEX IF NOT EXISTS idx_notifications_user_unread
ON public.notifications(user_id, is_read)
WHERE is_read = FALSE;

-- Index for getting user's notifications ordered by recency
-- Used in: notification_service.py get_notifications()
CREATE INDEX IF NOT EXISTS idx_notifications_user_created
ON public.notifications(user_id, created_at DESC);

-- Index for finding notifications related to a user (for cleanup/queries)
CREATE INDEX IF NOT EXISTS idx_notifications_related_user
ON public.notifications(related_user_id)
WHERE related_user_id IS NOT NULL;

-- Index for notification type filtering (if ever needed)
CREATE INDEX IF NOT EXISTS idx_notifications_type
ON public.notifications(type, created_at DESC);

-- =============================================================================
-- USER CONNECTIONS TABLE
-- =============================================================================

-- Index for getting incoming connection requests
-- Used in: user_connections_service.py get_pending_requests()
CREATE INDEX IF NOT EXISTS idx_user_connections_following_status
ON public.user_connections(following_id, status, created_at DESC);

-- Index for getting outgoing connection requests
-- Used in: user_connections_service.py get_pending_requests()
CREATE INDEX IF NOT EXISTS idx_user_connections_follower_status
ON public.user_connections(follower_id, status, created_at DESC);

-- Composite index for both directions with accepted status
CREATE INDEX IF NOT EXISTS idx_user_connections_both_accepted
ON public.user_connections(follower_id, following_id)
WHERE status = 'accepted';

-- =============================================================================
-- USER PODCAST FOLLOWS TABLE
-- =============================================================================

-- Index for getting user's followed podcasts ordered by when they followed
-- Used in: user_listening_service.py get_user_followed_podcasts()
CREATE INDEX IF NOT EXISTS idx_user_podcast_follows_user_followed
ON public.user_podcast_follows(user_id, followed_at DESC);

-- Index for finding followers of a specific podcast (analytics/stats)
CREATE INDEX IF NOT EXISTS idx_user_podcast_follows_podcast
ON public.user_podcast_follows(podcast_id, followed_at DESC);

-- Composite index for checking if user follows specific podcast
-- Used in: podcast_service.py, podcast_search_service.py
CREATE INDEX IF NOT EXISTS idx_user_podcast_follows_user_podcast
ON public.user_podcast_follows(user_id, podcast_id);

-- =============================================================================
-- EPISODES TABLE
-- =============================================================================

-- Index for getting recent episodes for a podcast
-- Used in: user_listening_service.py, podcast_service.py
CREATE INDEX IF NOT EXISTS idx_episodes_podcast_published
ON public.episodes(podcast_id, published_at DESC);

-- Index for episode audio URL lookups (for playback)
CREATE INDEX IF NOT EXISTS idx_episodes_audio_url
ON public.episodes(podcast_id, id)
WHERE audio_url IS NOT NULL;

-- =============================================================================
-- POST COMMENTS TABLE
-- =============================================================================

-- Index for getting user's comments
CREATE INDEX IF NOT EXISTS idx_post_comments_user_created
ON public.post_comments(user_id, created_at DESC)
WHERE deleted_at IS NULL;

-- Index for comment author with post relationship (for user's comment history)
CREATE INDEX IF NOT EXISTS idx_post_comments_user_post
ON public.post_comments(user_id, post_id, created_at DESC)
WHERE deleted_at IS NULL;

-- =============================================================================
-- MESSAGE REACTIONS TABLE
-- =============================================================================

-- Index for getting all reactions for a message
-- Used in: messages_service.py get_message_reactions()
CREATE INDEX IF NOT EXISTS idx_message_reactions_message
ON public.message_reactions(message_id, created_at DESC);

-- Index for getting user's reactions (cleanup/queries)
CREATE INDEX IF NOT EXISTS idx_message_reactions_user
ON public.message_reactions(user_id, message_id);

-- Composite index for checking if user reacted to message with specific emoji
CREATE INDEX IF NOT EXISTS idx_message_reactions_message_user_emoji
ON public.message_reactions(message_id, user_id, emoji);

-- =============================================================================
-- MESSAGES TABLE (ADDITIONAL)
-- =============================================================================

-- Index for getting messages by sender (user's sent messages)
CREATE INDEX IF NOT EXISTS idx_messages_sender_created
ON public.messages(sender_id, created_at DESC)
WHERE is_deleted = FALSE;

-- Index for message search within conversation with sender filter
CREATE INDEX IF NOT EXISTS idx_messages_conversation_sender
ON public.messages(conversation_id, sender_id, created_at DESC)
WHERE is_deleted = FALSE;

-- =============================================================================
-- CONVERSATION PARTICIPANTS (ADDITIONAL)
-- =============================================================================

-- Index for finding active conversations by user (improved version)
CREATE INDEX IF NOT EXISTS idx_conversation_participants_user_active
ON public.conversation_participants(user_id, joined_at DESC)
WHERE left_at IS NULL;

-- Index for conversation membership lookup
CREATE INDEX IF NOT EXISTS idx_conversation_participants_conversation_user
ON public.conversation_participants(conversation_id, user_id);

-- =============================================================================
-- USER LISTENING PROGRESS TABLE
-- =============================================================================

-- Note: idx_user_progress_user (user_id, last_played_at DESC) already exists from migration 019
-- Note: idx_user_progress_episode (episode_id) already exists from migration 019

-- Index for composite episode+user lookups (useful for checking specific user progress on episode)
CREATE INDEX IF NOT EXISTS idx_user_listening_progress_episode_user
ON public.user_listening_progress(episode_id, user_id);

-- =============================================================================
-- PODCASTS TABLE (ADDITIONAL)
-- =============================================================================

-- Index for featured podcasts ordered by priority
CREATE INDEX IF NOT EXISTS idx_podcasts_featured_priority
ON public.podcasts(is_featured, featured_priority)
WHERE is_featured = TRUE;

-- Index for claimed podcasts
CREATE INDEX IF NOT EXISTS idx_podcasts_claimed
ON public.podcasts(id, listennotes_id)
WHERE listennotes_id IS NOT NULL;

-- =============================================================================
-- USER PROFILES (ADDITIONAL)
-- =============================================================================

-- Note: user_profiles table doesn't have podcast_id column
-- Podcast ownership is tracked via podcast_claims table

-- =============================================================================
-- PODCAST CLAIMS TABLE
-- =============================================================================

-- Index for getting user's claimed podcasts
CREATE INDEX IF NOT EXISTS idx_podcast_claims_user_status
ON public.podcast_claims(user_id, claim_status, created_at DESC);

-- Index for finding claims by listennotes_id
CREATE INDEX IF NOT EXISTS idx_podcast_claims_listennotes_status
ON public.podcast_claims(listennotes_id, claim_status);

-- Index for verified claims
CREATE INDEX IF NOT EXISTS idx_podcast_claims_verified
ON public.podcast_claims(user_id, listennotes_id)
WHERE claim_status = 'verified';

-- =============================================================================
-- USER ACTIVITY TABLE
-- =============================================================================

-- Index for getting user's activity feed
CREATE INDEX IF NOT EXISTS idx_user_activity_user_created
ON public.user_activity(user_id, created_at DESC);

-- Index for activity type filtering
CREATE INDEX IF NOT EXISTS idx_user_activity_type_created
ON public.user_activity(activity_type, created_at DESC);

-- =============================================================================
-- EVENTS TABLE (ADDITIONAL)
-- =============================================================================

-- Note: Events table indexes already exist in migration 017_enhance_events_system.sql
-- including idx_events_date_status, idx_events_host_user_id, idx_events_tags, etc.
-- No additional indexes needed

-- =============================================================================
-- POST SAVES (ADDITIONAL)
-- =============================================================================

-- Improve existing index with DESC for chronological ordering
CREATE INDEX IF NOT EXISTS idx_post_saves_user_saved_at
ON public.post_saves(user_id, created_at DESC);

-- =============================================================================
-- VERIFICATION & STATISTICS
-- =============================================================================

-- Run this query to verify all indexes were created:
-- SELECT
--     schemaname,
--     tablename,
--     indexname,
--     indexdef
-- FROM pg_indexes
-- WHERE schemaname = 'public'
--     AND indexname LIKE 'idx_%'
-- ORDER BY tablename, indexname;

-- Check index sizes (useful for monitoring):
-- SELECT
--     schemaname,
--     tablename,
--     indexname,
--     pg_size_pretty(pg_relation_size(indexname::regclass)) as index_size
-- FROM pg_indexes
-- WHERE schemaname = 'public'
--     AND indexname LIKE 'idx_%'
-- ORDER BY pg_relation_size(indexname::regclass) DESC;

-- Monitor index usage after deployment:
-- SELECT
--     schemaname,
--     tablename,
--     indexname,
--     idx_scan as times_used,
--     idx_tup_read as tuples_read,
--     idx_tup_fetch as tuples_fetched
-- FROM pg_stat_user_indexes
-- WHERE schemaname = 'public'
--     AND indexname LIKE 'idx_%'
-- ORDER BY idx_scan DESC;

-- Find unused indexes (run after a week in production):
-- SELECT
--     schemaname,
--     tablename,
--     indexname,
--     pg_size_pretty(pg_relation_size(indexname::regclass)) as index_size
-- FROM pg_stat_user_indexes
-- WHERE schemaname = 'public'
--     AND idx_scan = 0
--     AND indexname LIKE 'idx_%'
-- ORDER BY pg_relation_size(indexname::regclass) DESC;

COMMENT ON INDEX idx_notifications_user_unread IS 'Performance: Unread notification counts (cached in app but DB fallback)';
COMMENT ON INDEX idx_user_podcast_follows_user_followed IS 'Performance: User followed podcasts feed';
COMMENT ON INDEX idx_episodes_podcast_published IS 'Performance: Recent episodes for podcast';
COMMENT ON INDEX idx_user_connections_following_status IS 'Performance: Incoming connection requests';
COMMENT ON INDEX idx_user_connections_follower_status IS 'Performance: Outgoing connection requests';
