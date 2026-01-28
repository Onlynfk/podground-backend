-- Create podcast_refresh_log table to track podcast refresh requests
-- This table logs when podcast data refreshes are requested from ListenNotes
-- and tracks whether we've followed up with the podcast owner when their email becomes available
-- Note: This endpoint is public, so no user tracking

CREATE TABLE IF NOT EXISTS podcast_refresh_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    podcast_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    email_sent BOOLEAN NOT NULL DEFAULT FALSE,
    podcast_email TEXT
);

-- Index for finding unprocessed logs by time
CREATE INDEX IF NOT EXISTS idx_podcast_refresh_log_unprocessed
ON podcast_refresh_log(podcast_id, created_at)
WHERE processed_at IS NULL;

-- Index for podcast lookups
CREATE INDEX IF NOT EXISTS idx_podcast_refresh_log_podcast_id
ON podcast_refresh_log(podcast_id);

-- Enable RLS
ALTER TABLE podcast_refresh_log ENABLE ROW LEVEL SECURITY;

-- Policy: Service role can do everything (for background job)
CREATE POLICY "Service role can manage all refresh logs"
ON podcast_refresh_log
FOR ALL
USING (auth.jwt()->>'role' = 'service_role');

-- Policy: Allow public inserts (for unauthenticated refresh requests)
CREATE POLICY "Allow public insert for refresh logs"
ON podcast_refresh_log
FOR INSERT
WITH CHECK (true);

-- Add comment
COMMENT ON TABLE podcast_refresh_log IS 'Tracks podcast refresh requests and follow-up email notifications when podcast owner email becomes available';
