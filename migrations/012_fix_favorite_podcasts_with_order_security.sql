-- Migration: Fix security issue with user_favorite_podcasts_with_order view
-- Issue: View was defined with SECURITY DEFINER which bypasses RLS policies
-- Fix: Drop and recreate view without SECURITY DEFINER

-- SECURITY ISSUE IDENTIFIED:
-- The view 'user_favorite_podcasts_with_order' has SECURITY DEFINER property
-- This is the same security risk as the previous views:
-- 1. It bypasses Row Level Security (RLS) policies
-- 2. It executes with the permissions of the view creator, not the querying user
-- 3. Users could potentially access other users' favorite podcast data

-- Step 1: Drop the problematic view
DROP VIEW IF EXISTS public.user_favorite_podcasts_with_order CASCADE;

-- Step 2: Recreate the view properly without SECURITY DEFINER
-- This view provides favorite podcasts with ordering
CREATE OR REPLACE VIEW public.user_favorite_podcasts_with_order AS
SELECT 
    ufp.id,
    ufp.user_id,
    ufp.podcast_id,
    ufp.podcast_title,
    ufp.podcast_image,
    ufp.podcast_publisher,
    ufp.created_at,
    ufp.updated_at,
    ROW_NUMBER() OVER (PARTITION BY ufp.user_id ORDER BY ufp.created_at) as favorite_order
FROM public.user_favorite_podcasts ufp
WHERE ufp.user_id = auth.uid(); -- Critical: Users can only see their own favorites

-- Add comment to document the security model
COMMENT ON VIEW public.user_favorite_podcasts_with_order IS 
'View showing user favorite podcasts with ordering. 
Security: Filters by auth.uid() to ensure users only see their own data. 
Does NOT use SECURITY DEFINER - respects RLS policies.';

-- Verify RLS is still enabled on the base table
ALTER TABLE public.user_favorite_podcasts ENABLE ROW LEVEL SECURITY;

-- Ensure the RLS policy exists and is correct
DO $$
BEGIN
    -- Drop existing policy if it exists (to recreate with correct settings)
    DROP POLICY IF EXISTS "Users can manage their own favorite podcasts" ON public.user_favorite_podcasts;
    
    -- Create the policy with proper access control
    CREATE POLICY "Users can manage their own favorite podcasts" 
    ON public.user_favorite_podcasts 
    FOR ALL 
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);
END
$$;

-- Also check if there's a metadata view that needs fixing
DROP VIEW IF EXISTS public.user_favorite_podcasts_with_metadata CASCADE;

-- Recreate metadata view if needed (without SECURITY DEFINER)
CREATE OR REPLACE VIEW public.user_favorite_podcasts_with_metadata AS
SELECT 
    ufp.*,
    COUNT(*) OVER (PARTITION BY ufp.podcast_id) as total_favorited_by_users
FROM public.user_favorite_podcasts ufp
WHERE ufp.user_id = auth.uid()  -- User can only see stats for their own favorites
ORDER BY ufp.user_id, ufp.created_at;

-- Grant appropriate permissions
GRANT SELECT ON public.user_favorite_podcasts_with_order TO authenticated;
GRANT SELECT ON public.user_favorite_podcasts_with_metadata TO authenticated;

-- NOTES:
-- 1. Both views now filter by auth.uid() for proper data isolation
-- 2. No SECURITY DEFINER clause on any view
-- 3. RLS policies are enforced through the base table
-- 4. Users can only see and manage their own favorite podcasts
-- 5. The metadata view now only shows stats for the user's own favorites