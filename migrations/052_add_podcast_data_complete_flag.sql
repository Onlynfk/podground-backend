-- Migration: Add flag to track whether podcast has full data from ListenNotes
-- Description: Used by claimed podcast import service to know which podcasts need data refresh

-- Add column to track if podcast has complete data from ListenNotes
ALTER TABLE public.podcasts
ADD COLUMN IF NOT EXISTS has_full_data BOOLEAN DEFAULT true;

-- Mark existing podcasts with placeholder descriptions as incomplete
UPDATE public.podcasts
SET has_full_data = false
WHERE description LIKE 'Claimed podcast:%';

-- Remove placeholder prefix from descriptions
UPDATE public.podcasts
SET description = TRIM(REPLACE(description, 'Claimed podcast:', ''))
WHERE description LIKE 'Claimed podcast:%';

-- Add index for efficient querying of incomplete podcasts
CREATE INDEX IF NOT EXISTS idx_podcasts_incomplete_data
ON public.podcasts(has_full_data)
WHERE has_full_data = false;

-- Add comment
COMMENT ON COLUMN public.podcasts.has_full_data IS 'Whether podcast has complete data from ListenNotes API. False indicates placeholder data that needs to be refreshed.';
