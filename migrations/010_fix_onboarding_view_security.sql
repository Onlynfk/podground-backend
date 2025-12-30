-- Migration: Fix security issue with user_onboarding_with_favorites view
-- Issue: View was defined with SECURITY DEFINER which bypasses RLS policies
-- Fix: Drop and recreate view without SECURITY DEFINER

-- SECURITY ISSUE IDENTIFIED:
-- The view 'user_onboarding_with_favorites' was created/modified with SECURITY DEFINER
-- This is a security risk because:
-- 1. It bypasses Row Level Security (RLS) policies
-- 2. It executes with the permissions of the view creator, not the querying user
-- 3. Users could potentially access onboarding data they shouldn't be able to see

-- Step 1: Drop the problematic view
DROP VIEW IF EXISTS public.user_onboarding_with_favorites CASCADE;

-- Step 2: Recreate the view properly without SECURITY DEFINER
-- This view aggregates favorite podcasts for backwards compatibility
CREATE OR REPLACE VIEW public.user_onboarding_with_favorites AS
SELECT 
    uo.*,
    -- Aggregate favorite podcasts into an array for compatibility
    COALESCE(
        array_agg(ufp.podcast_id ORDER BY ufp.created_at) FILTER (WHERE ufp.podcast_id IS NOT NULL),
        '{}'::text[]
    ) as favorite_podcast_ids
FROM 
    public.user_onboarding uo
LEFT JOIN 
    public.user_favorite_podcasts ufp ON uo.id = ufp.user_id
WHERE 
    -- Important: Ensure users can only see their own onboarding data
    uo.id = auth.uid()
GROUP BY uo.id;

-- Add comment to document the security fix
COMMENT ON VIEW public.user_onboarding_with_favorites IS 
'Compatibility view that includes favorite_podcast_ids aggregated from user_favorite_podcasts table. 
Security: This view respects RLS by filtering to auth.uid() and does NOT use SECURITY DEFINER.';

-- Step 3: Ensure RLS is enabled on the underlying tables
ALTER TABLE public.user_onboarding ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_favorite_podcasts ENABLE ROW LEVEL SECURITY;

-- Step 4: Create/update RLS policies if they don't exist
DO $$
BEGIN
    -- Policy for user_onboarding table
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies 
        WHERE schemaname = 'public' 
        AND tablename = 'user_onboarding' 
        AND policyname = 'Users can manage their own onboarding'
    ) THEN
        CREATE POLICY "Users can manage their own onboarding" 
        ON public.user_onboarding 
        FOR ALL 
        USING (auth.uid() = id)
        WITH CHECK (auth.uid() = id);
    END IF;

    -- Policy for user_favorite_podcasts table (if not already created)
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies 
        WHERE schemaname = 'public' 
        AND tablename = 'user_favorite_podcasts' 
        AND policyname = 'Users can manage their own favorite podcasts'
    ) THEN
        CREATE POLICY "Users can manage their own favorite podcasts" 
        ON public.user_favorite_podcasts 
        FOR ALL 
        USING (auth.uid() = user_id)
        WITH CHECK (auth.uid() = user_id);
    END IF;
END
$$;

-- NOTES:
-- 1. The view now includes WHERE uo.id = auth.uid() to ensure data isolation
-- 2. No SECURITY DEFINER clause - respects the querying user's permissions
-- 3. RLS policies are enforced on both underlying tables
-- 4. Users can only see and modify their own onboarding data
-- 5. The view maintains backwards compatibility while being secure