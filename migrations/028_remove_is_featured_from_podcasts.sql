-- Migration: Remove deprecated is_featured column from podcasts table
-- Description: The is_featured field is redundant as we have a dedicated featured_podcasts table
-- Date: 2025-09-22

-- Drop the is_featured column from podcasts table
ALTER TABLE public.podcasts 
DROP COLUMN IF EXISTS is_featured;

-- Also drop related columns if they exist
ALTER TABLE public.podcasts 
DROP COLUMN IF EXISTS featured_priority;

ALTER TABLE public.podcasts 
DROP COLUMN IF EXISTS featured_until;

-- Add comment to document the change
COMMENT ON TABLE public.podcasts IS 'Main podcasts table. For featured podcasts, use the featured_podcasts table instead.';
