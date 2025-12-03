-- Migration: Add is_pinned column to posts table
-- Description: Allows posts to be pinned to the top of feeds and profiles

-- Add is_pinned column to posts table
ALTER TABLE public.posts
ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN DEFAULT false;

-- Create index for efficient filtering of pinned posts
CREATE INDEX IF NOT EXISTS idx_posts_is_pinned ON public.posts(is_pinned) WHERE is_pinned = true;

-- Create composite index for user's pinned posts
CREATE INDEX IF NOT EXISTS idx_posts_user_pinned ON public.posts(user_id, is_pinned, created_at DESC) WHERE is_pinned = true;

-- Update existing posts to have is_pinned = false (explicit, though DEFAULT handles this)
UPDATE public.posts
SET is_pinned = false
WHERE is_pinned IS NULL;

-- Add comment to document the column
COMMENT ON COLUMN public.posts.is_pinned IS 'Whether the post is pinned to the top of the user''s profile or feed';

-- Log completion
DO $$
BEGIN
  RAISE NOTICE 'Added is_pinned column to posts table with indexes';
END $$;
