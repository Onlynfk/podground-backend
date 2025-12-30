-- Migration: Add storage_path to post_media for signed URL generation
-- This enables private media access via signed URLs instead of public URLs

-- Add storage_path column to post_media table
ALTER TABLE public.post_media
ADD COLUMN IF NOT EXISTS storage_path TEXT;

-- Create index for storage path lookups
CREATE INDEX IF NOT EXISTS idx_post_media_storage_path ON public.post_media(storage_path);

-- Comment to explain the change
COMMENT ON COLUMN public.post_media.storage_path IS
'R2 storage path for generating signed URLs (e.g., media/{user_id}/{year}/{month}/{file}.jpg).
When present, use this to generate signed URLs instead of using the url column directly.';

-- For existing records, we'll extract the storage path from the URL
-- This is a one-time data migration for backward compatibility
UPDATE public.post_media
SET storage_path = REPLACE(url, CONCAT('https://pub-', (SELECT current_setting('app.r2_public_url', true)), '/'), '')
WHERE storage_path IS NULL AND url IS NOT NULL;
