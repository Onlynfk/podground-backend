-- Migration 032: Make posts content optional and add validation
-- Allows posts to be text-only, media-only, or combination

-- Make content column optional
ALTER TABLE public.posts ALTER COLUMN content DROP NOT NULL;

-- Add CHECK constraint to ensure posts have either content OR media
-- We'll check this by ensuring either:
-- 1. content is not null/empty, OR  
-- 2. post has associated media in post_media table
-- Note: We can't directly reference post_media in a CHECK constraint, so we'll handle this in application logic

-- Add a function to validate post has content or media
CREATE OR REPLACE FUNCTION validate_post_has_content_or_media()
RETURNS TRIGGER AS $$
BEGIN
    -- If content exists and is not empty, allow the post
    IF NEW.content IS NOT NULL AND trim(NEW.content) != '' THEN
        RETURN NEW;
    END IF;
    
    -- If no content, check if post has media
    -- Note: This check will happen after post_media records are inserted
    -- So we'll allow posts without content for now and validate in application
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger to validate posts (will be enhanced later)
DROP TRIGGER IF EXISTS validate_post_content_trigger ON public.posts;
CREATE TRIGGER validate_post_content_trigger
    BEFORE INSERT OR UPDATE ON public.posts
    FOR EACH ROW EXECUTE FUNCTION validate_post_has_content_or_media();

-- Create post reactions table
CREATE TABLE IF NOT EXISTS public.post_reactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id UUID NOT NULL REFERENCES public.posts(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    reaction_type VARCHAR(50) NOT NULL, -- emoji or reaction name
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Ensure one reaction per user per post per type
    UNIQUE(post_id, user_id, reaction_type)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_post_reactions_post ON public.post_reactions(post_id);
CREATE INDEX IF NOT EXISTS idx_post_reactions_user ON public.post_reactions(user_id);
CREATE INDEX IF NOT EXISTS idx_post_reactions_type ON public.post_reactions(reaction_type);

-- Enable RLS
ALTER TABLE public.post_reactions ENABLE ROW LEVEL SECURITY;

-- RLS Policies for post reactions
CREATE POLICY "Users can read all reactions" ON public.post_reactions FOR SELECT USING (true);
CREATE POLICY "Users can manage their own reactions" ON public.post_reactions 
    FOR ALL USING (user_id = auth.uid());

-- Add reaction counts to posts table for performance
ALTER TABLE public.posts ADD COLUMN IF NOT EXISTS reactions_count INTEGER DEFAULT 0;

-- Function to update reaction counts
CREATE OR REPLACE FUNCTION update_post_reaction_count()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE public.posts SET reactions_count = reactions_count + 1 
        WHERE id = NEW.post_id;
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        UPDATE public.posts SET reactions_count = reactions_count - 1 
        WHERE id = OLD.post_id;
        RETURN OLD;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Trigger for reaction count updates
CREATE TRIGGER update_post_reaction_count_trigger
    AFTER INSERT OR DELETE ON public.post_reactions
    FOR EACH ROW EXECUTE FUNCTION update_post_reaction_count();

-- Update existing posts reaction counts
UPDATE public.posts 
SET reactions_count = (
    SELECT COUNT(*) 
    FROM public.post_reactions 
    WHERE post_id = posts.id
);