-- Migration: Add feed cache invalidation triggers
-- This creates a metadata table to track when the feed was last updated,
-- and triggers that automatically update the timestamp when relevant data changes.

-- Create feed cache metadata table
CREATE TABLE IF NOT EXISTS public.feed_cache_metadata (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    last_updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert a single row to track global feed updates
-- Use ON CONFLICT to avoid errors if row already exists
INSERT INTO public.feed_cache_metadata (id, last_updated_at, created_at)
VALUES ('00000000-0000-0000-0000-000000000001'::UUID, NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_feed_cache_metadata_last_updated
ON public.feed_cache_metadata(last_updated_at);

-- Create trigger function to invalidate feed cache
CREATE OR REPLACE FUNCTION public.invalidate_feed_cache()
RETURNS TRIGGER AS $$
BEGIN
    -- Update the last_updated_at timestamp to invalidate cache
    UPDATE public.feed_cache_metadata
    SET last_updated_at = NOW()
    WHERE id = '00000000-0000-0000-0000-000000000001'::UUID;

    -- Return appropriate value based on operation
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    ELSE
        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Attach triggers to posts table
DROP TRIGGER IF EXISTS posts_feed_cache_trigger ON public.posts;
CREATE TRIGGER posts_feed_cache_trigger
AFTER INSERT OR UPDATE OR DELETE ON public.posts
FOR EACH ROW EXECUTE FUNCTION public.invalidate_feed_cache();

-- Attach triggers to post_comments table
DROP TRIGGER IF EXISTS post_comments_feed_cache_trigger ON public.post_comments;
CREATE TRIGGER post_comments_feed_cache_trigger
AFTER INSERT OR UPDATE OR DELETE ON public.post_comments
FOR EACH ROW EXECUTE FUNCTION public.invalidate_feed_cache();

-- Attach triggers to post_likes table
DROP TRIGGER IF EXISTS post_likes_feed_cache_trigger ON public.post_likes;
CREATE TRIGGER post_likes_feed_cache_trigger
AFTER INSERT OR DELETE ON public.post_likes
FOR EACH ROW EXECUTE FUNCTION public.invalidate_feed_cache();

-- Attach triggers to comment_likes table
DROP TRIGGER IF EXISTS comment_likes_feed_cache_trigger ON public.comment_likes;
CREATE TRIGGER comment_likes_feed_cache_trigger
AFTER INSERT OR DELETE ON public.comment_likes
FOR EACH ROW EXECUTE FUNCTION public.invalidate_feed_cache();

-- Attach triggers to post_media table (in case media is added/removed separately)
DROP TRIGGER IF EXISTS post_media_feed_cache_trigger ON public.post_media;
CREATE TRIGGER post_media_feed_cache_trigger
AFTER INSERT OR UPDATE OR DELETE ON public.post_media
FOR EACH ROW EXECUTE FUNCTION public.invalidate_feed_cache();

-- Comment: These triggers ensure that any change to feed-relevant data
-- automatically updates the last_updated_at timestamp, which the Python
-- application uses to determine if cached feed data is still valid.
--
-- Note: User account deletions are handled by Supabase auth.users (not accessible
-- via public triggers). Post/comment soft deletes will trigger cache invalidation.
