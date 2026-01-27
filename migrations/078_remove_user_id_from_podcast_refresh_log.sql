-- Migration to remove user_id column from podcast_refresh_log table
-- This makes the endpoint fully public without user tracking

-- Drop the old RLS policy that referenced user_id
DROP POLICY IF EXISTS "Users can view their own refresh logs" ON podcast_refresh_log;

-- Drop the user_id index
DROP INDEX IF EXISTS idx_podcast_refresh_log_user_id;

-- Drop the user_id column
ALTER TABLE podcast_refresh_log DROP COLUMN IF EXISTS user_id;

-- Recreate the RLS policy to allow public inserts
DROP POLICY IF EXISTS "Allow public insert for refresh logs" ON podcast_refresh_log;
CREATE POLICY "Allow public insert for refresh logs"
ON podcast_refresh_log
FOR INSERT
WITH CHECK (true);

-- Add comment about the change
COMMENT ON TABLE podcast_refresh_log IS 'Tracks podcast refresh requests (public endpoint, no user tracking) and follow-up email notifications when podcast owner email becomes available';
