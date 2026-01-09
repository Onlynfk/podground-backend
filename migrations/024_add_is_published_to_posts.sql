-- Migration: Add is_published column to posts table
-- This adds the missing is_published column that the code is expecting

-- Add is_published column to posts table
ALTER TABLE public.posts 
ADD COLUMN IF NOT EXISTS is_published BOOLEAN DEFAULT TRUE;

-- Create index for performance on published posts queries
CREATE INDEX IF NOT EXISTS idx_posts_is_published ON public.posts(is_published);

-- Update RLS policy to include is_published condition
DROP POLICY IF EXISTS "Posts are viewable by everyone" ON public.posts;
CREATE POLICY "Posts are viewable by everyone" ON public.posts
    FOR SELECT USING (deleted_at IS NULL AND is_published = TRUE);

-- Add comment for documentation
COMMENT ON COLUMN public.posts.is_published IS 'Whether the post is published and visible to other users. Defaults to true.';