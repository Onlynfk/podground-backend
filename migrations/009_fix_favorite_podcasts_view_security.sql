-- Migration: Fix security issue with user_favorite_podcasts_ranked view
-- Issue: View was defined with SECURITY DEFINER which bypasses RLS policies
-- Fix: Drop and recreate view without SECURITY DEFINER, or drop if not needed

-- SECURITY ISSUE IDENTIFIED:
-- The view 'user_favorite_podcasts_ranked' was created with SECURITY DEFINER
-- This is a security risk because:
-- 1. It bypasses Row Level Security (RLS) policies
-- 2. It executes with the permissions of the view creator, not the querying user
-- 3. Users could potentially access data they shouldn't be able to see

-- IMMEDIATE FIX: Drop the problematic view
DROP VIEW IF EXISTS public.user_favorite_podcasts_ranked CASCADE;

-- ALTERNATIVE APPROACH: If ranking is needed, create a secure view
-- This view would respect RLS policies and user permissions:
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
WHERE ufp.user_id = auth.uid(); -- Ensure users only see their own data

-- Enable RLS on the base table if not already enabled
ALTER TABLE public.user_favorite_podcasts ENABLE ROW LEVEL SECURITY;

-- Create RLS policy for user_favorite_podcasts if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies 
        WHERE schemaname = 'public' 
        AND tablename = 'user_favorite_podcasts' 
        AND policyname = 'Users can manage their own favorite podcasts'
    ) THEN
        CREATE POLICY "Users can manage their own favorite podcasts" 
        ON public.user_favorite_podcasts 
        FOR ALL 
        USING (auth.uid() = user_id);
    END IF;
END
$$;

-- NOTES:
-- 1. The new view uses auth.uid() to ensure data isolation per user
-- 2. No SECURITY DEFINER clause - respects the querying user's permissions
-- 3. RLS policies are enforced on the underlying table
-- 4. If the original ranked view is still needed elsewhere, it should be recreated
--    without SECURITY DEFINER and with proper access controls