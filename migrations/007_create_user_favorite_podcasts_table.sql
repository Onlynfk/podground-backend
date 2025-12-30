-- Migration: Create user_favorite_podcasts mapping table
-- Description: Replace JSONB favorite_podcast_ids with proper relational table
-- This provides better data integrity, querying, and analytics capabilities

-- Create the mapping table for user favorite podcasts
CREATE TABLE IF NOT EXISTS public.user_favorite_podcasts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    podcast_id VARCHAR(255) NOT NULL,  -- ListenNotes podcast ID
    podcast_title VARCHAR(255),  -- Denormalized for performance
    podcast_image VARCHAR(500),  -- Denormalized for performance
    podcast_publisher VARCHAR(255),  -- Denormalized for performance
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Ensure each user can only favorite a podcast once
    UNIQUE(user_id, podcast_id)
);

-- Create indexes for performance
CREATE INDEX idx_user_favorite_podcasts_user_id ON public.user_favorite_podcasts(user_id);
CREATE INDEX idx_user_favorite_podcasts_podcast_id ON public.user_favorite_podcasts(podcast_id);
CREATE INDEX idx_user_favorite_podcasts_created_at ON public.user_favorite_podcasts(created_at);

-- Create RLS policies
ALTER TABLE public.user_favorite_podcasts ENABLE ROW LEVEL SECURITY;

-- Users can view all favorite podcasts (for discovery features)
CREATE POLICY "Favorite podcasts are viewable by all authenticated users" ON public.user_favorite_podcasts
    FOR SELECT
    USING (auth.uid() IS NOT NULL);

-- Users can only insert their own favorites
CREATE POLICY "Users can insert their own favorite podcasts" ON public.user_favorite_podcasts
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Users can only update their own favorites
CREATE POLICY "Users can update their own favorite podcasts" ON public.user_favorite_podcasts
    FOR UPDATE
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Users can only delete their own favorites
CREATE POLICY "Users can delete their own favorite podcasts" ON public.user_favorite_podcasts
    FOR DELETE
    USING (auth.uid() = user_id);

-- Add updated_at trigger
CREATE TRIGGER update_user_favorite_podcasts_updated_at
    BEFORE UPDATE ON public.user_favorite_podcasts
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at_column();

-- Migrate existing data from array to new table
-- This handles favorite_podcast_ids as a PostgreSQL text array
DO $$
DECLARE
    user_record RECORD;
    current_podcast_id TEXT;
    podcast_count INTEGER;
BEGIN
    -- Loop through users who have favorite podcasts
    FOR user_record IN 
        SELECT id as user_id, favorite_podcast_ids 
        FROM public.user_onboarding 
        WHERE favorite_podcast_ids IS NOT NULL 
        AND array_length(favorite_podcast_ids, 1) > 0
    LOOP
        podcast_count := 0;
        
        -- Loop through each favorite podcast
        FOR current_podcast_id IN 
            SELECT unnest(user_record.favorite_podcast_ids)
        LOOP
            -- Insert into new table (skip if already exists)
            INSERT INTO public.user_favorite_podcasts (user_id, podcast_id)
            VALUES (user_record.user_id, current_podcast_id)
            ON CONFLICT (user_id, podcast_id) DO NOTHING;
            
            podcast_count := podcast_count + 1;
            
            -- Only migrate first 5
            EXIT WHEN podcast_count >= 5;
        END LOOP;
    END LOOP;
END $$;

-- Add comments
COMMENT ON TABLE public.user_favorite_podcasts IS 'Stores users favorite podcasts from onboarding';
COMMENT ON COLUMN public.user_favorite_podcasts.podcast_id IS 'ListenNotes podcast ID';

-- Create view for easy access to user's favorite podcasts
CREATE OR REPLACE VIEW public.user_favorite_podcasts_with_metadata AS
SELECT 
    ufp.*,
    COUNT(*) OVER (PARTITION BY podcast_id) as total_favorited_by_users
FROM public.user_favorite_podcasts ufp
ORDER BY user_id, created_at;

-- Grant permissions
GRANT ALL ON public.user_favorite_podcasts TO authenticated;
GRANT ALL ON public.user_favorite_podcasts_with_metadata TO authenticated;

-- Note: The favorite_podcast_ids column in user_onboarding is now deprecated
-- but we keep it for backwards compatibility during transition
COMMENT ON COLUMN public.user_onboarding.favorite_podcast_ids IS 'DEPRECATED: Use user_favorite_podcasts table instead. This column is kept for backwards compatibility.';