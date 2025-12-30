-- Add the missing latest_episode_updated_at column for TTL-based caching
-- This column was supposed to be added in migration 027 but may have been skipped

-- Add the timestamp column if it doesn't exist
ALTER TABLE public.podcasts
ADD COLUMN IF NOT EXISTS latest_episode_updated_at TIMESTAMPTZ;

-- Add index for faster TTL queries
CREATE INDEX IF NOT EXISTS idx_podcasts_latest_episode_updated
ON public.podcasts(latest_episode_updated_at)
WHERE latest_episode_id IS NOT NULL;

-- Set initial timestamps for existing podcasts (optional - sets to now so they won't refresh immediately)
-- Comment this out if you want all podcasts to refresh on next access
UPDATE public.podcasts
SET latest_episode_updated_at = NOW()
WHERE latest_episode_id IS NOT NULL
  AND latest_episode_updated_at IS NULL;

-- Show results
SELECT
    COUNT(*) as total_podcasts,
    COUNT(latest_episode_id) as have_latest_episode,
    COUNT(latest_episode_updated_at) as have_timestamp
FROM public.podcasts;
