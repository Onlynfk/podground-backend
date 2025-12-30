-- Migration: Add composite indexes for better feed query performance
-- Optimizes queries that filter on deleted_at and order by created_at

-- Composite index for feed queries (WHERE deleted_at IS NULL ORDER BY created_at DESC)
CREATE INDEX IF NOT EXISTS idx_posts_deleted_at_created_at
    ON public.posts(deleted_at, created_at DESC)
    WHERE deleted_at IS NULL;

-- Composite index for user-specific feed queries
CREATE INDEX IF NOT EXISTS idx_posts_user_deleted_created
    ON public.posts(user_id, deleted_at, created_at DESC)
    WHERE deleted_at IS NULL;

-- Index for category-based queries
CREATE INDEX IF NOT EXISTS idx_posts_category_deleted_created
    ON public.posts(category_id, deleted_at, created_at DESC)
    WHERE deleted_at IS NULL AND category_id IS NOT NULL;

-- Index for post_saves queries (for saved posts feed)
CREATE INDEX IF NOT EXISTS idx_post_saves_user_created
    ON public.post_saves(user_id, created_at DESC);

-- Index for post_likes with post_id (for engagement queries)
CREATE INDEX IF NOT EXISTS idx_post_likes_post_user
    ON public.post_likes(post_id, user_id);

-- Index for post_saves with post_id (for checking if saved)
CREATE INDEX IF NOT EXISTS idx_post_saves_post_user
    ON public.post_saves(post_id, user_id);

-- Comment: These indexes significantly improve performance for:
-- 1. Main feed queries that exclude deleted posts
-- 2. User-specific post listings
-- 3. Category-filtered feeds
-- 4. Saved posts retrieval
-- 5. Checking user engagement on posts (likes/saves)
