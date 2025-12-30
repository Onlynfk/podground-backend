-- Migration: Drop redundant favorite_podcast_ids column
-- Description: Remove the favorite_podcast_ids array column from user_onboarding table
-- as we now use the user_favorite_podcasts mapping table

-- First, ensure all data has been migrated (safety check)
DO $$
DECLARE
    unmigrated_count INTEGER;
BEGIN
    -- Count users with favorite podcasts that haven't been migrated
    SELECT COUNT(DISTINCT uo.id) INTO unmigrated_count
    FROM public.user_onboarding uo
    WHERE uo.favorite_podcast_ids IS NOT NULL 
    AND array_length(uo.favorite_podcast_ids, 1) > 0
    AND NOT EXISTS (
        SELECT 1 
        FROM public.user_favorite_podcasts ufp 
        WHERE ufp.user_id = uo.id
    );
    
    IF unmigrated_count > 0 THEN
        RAISE NOTICE 'Found % users with unmigrated favorite podcasts. Running migration...', unmigrated_count;
        
        -- Run the migration for any remaining users
        INSERT INTO public.user_favorite_podcasts (user_id, podcast_id)
        SELECT 
            uo.id as user_id,
            unnest_with_ordinality.podcast_id
        FROM 
            public.user_onboarding uo,
            LATERAL unnest(uo.favorite_podcast_ids) WITH ORDINALITY AS unnest_with_ordinality(podcast_id, ordinality)
        WHERE 
            uo.favorite_podcast_ids IS NOT NULL 
            AND array_length(uo.favorite_podcast_ids, 1) > 0
            AND unnest_with_ordinality.ordinality <= 5  -- Only first 5
        ON CONFLICT (user_id, podcast_id) DO NOTHING;
    END IF;
END $$;

-- Drop the column
ALTER TABLE public.user_onboarding 
DROP COLUMN IF EXISTS favorite_podcast_ids;

-- Add comment to document the change
COMMENT ON TABLE public.user_onboarding IS 'User onboarding progress tracking. Note: favorite_podcast_ids column was removed in migration 008 - use user_favorite_podcasts table instead.';

-- Create a view for backwards compatibility (optional - can help during transition)
CREATE OR REPLACE VIEW public.user_onboarding_with_favorites AS
SELECT 
    uo.*,
    COALESCE(
        array_agg(ufp.podcast_id ORDER BY ufp.created_at) FILTER (WHERE ufp.podcast_id IS NOT NULL),
        '{}'::text[]
    ) as favorite_podcast_ids
FROM 
    public.user_onboarding uo
LEFT JOIN 
    public.user_favorite_podcasts ufp ON uo.id = ufp.user_id
GROUP BY uo.id;

COMMENT ON VIEW public.user_onboarding_with_favorites IS 'Compatibility view that includes favorite_podcast_ids aggregated from user_favorite_podcasts table';