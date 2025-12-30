-- Migration: Fix user_connections table structure and relationships
-- Issue: PostgREST is having trouble with following_id column queries
-- Fix: Ensure proper foreign key constraints and add helpful comments

-- First, let's check and ensure the foreign key constraints are properly defined
-- (They should already exist, but let's make sure)
ALTER TABLE public.user_connections
    DROP CONSTRAINT IF EXISTS user_connections_follower_id_fkey,
    DROP CONSTRAINT IF EXISTS user_connections_following_id_fkey;

-- Re-add the foreign key constraints with explicit names
ALTER TABLE public.user_connections
    ADD CONSTRAINT user_connections_follower_id_fkey 
        FOREIGN KEY (follower_id) REFERENCES auth.users(id) ON DELETE CASCADE,
    ADD CONSTRAINT user_connections_following_id_fkey 
        FOREIGN KEY (following_id) REFERENCES auth.users(id) ON DELETE CASCADE;

-- Add helpful comments for PostgREST
COMMENT ON TABLE public.user_connections IS 'Stores user connections/following relationships';
COMMENT ON COLUMN public.user_connections.follower_id IS 'User who is following (initiates connection)';
COMMENT ON COLUMN public.user_connections.following_id IS 'User being followed (receives connection request)';
COMMENT ON COLUMN public.user_connections.status IS 'Connection status: pending, accepted, rejected, blocked';

-- Create helper functions that work with just user IDs (avoiding auth.users access issues)
CREATE OR REPLACE FUNCTION get_user_following_ids(user_id UUID)
RETURNS TABLE(following_id UUID) AS $$
BEGIN
    RETURN QUERY
    SELECT uc.following_id
    FROM public.user_connections uc
    WHERE uc.follower_id = user_id
    AND uc.status = 'accepted';
END;
$$ LANGUAGE plpgsql SECURITY INVOKER;

CREATE OR REPLACE FUNCTION get_user_follower_ids(user_id UUID) 
RETURNS TABLE(follower_id UUID) AS $$
BEGIN
    RETURN QUERY
    SELECT uc.follower_id
    FROM public.user_connections uc
    WHERE uc.following_id = user_id
    AND uc.status = 'accepted';
END;
$$ LANGUAGE plpgsql SECURITY INVOKER;

-- Grant execute permissions
GRANT EXECUTE ON FUNCTION get_user_following_ids(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION get_user_follower_ids(UUID) TO authenticated;

-- Add an index that might help with the query performance
CREATE INDEX IF NOT EXISTS idx_user_connections_composite 
ON public.user_connections(follower_id, status, following_id);

-- Note: If the PostgREST error persists, we can use these functions instead:
-- SELECT * FROM get_user_following(user_id) instead of querying the table directly