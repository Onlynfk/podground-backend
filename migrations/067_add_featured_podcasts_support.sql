-- Migration: Add featured podcasts support
-- Description: Add is_featured column to podcasts table for weekly featured podcasts

-- Add is_featured column to podcasts table
ALTER TABLE public.podcasts
ADD COLUMN IF NOT EXISTS is_featured BOOLEAN DEFAULT FALSE;

-- Add featured_at timestamp to track when podcast was featured
ALTER TABLE public.podcasts
ADD COLUMN IF NOT EXISTS featured_at TIMESTAMPTZ;

-- Create index for efficient featured podcast queries
CREATE INDEX IF NOT EXISTS idx_podcasts_is_featured ON public.podcasts(is_featured) WHERE is_featured = TRUE;

-- Create index for featured podcasts ordered by featured_at
CREATE INDEX IF NOT EXISTS idx_podcasts_featured_at ON public.podcasts(featured_at DESC) WHERE is_featured = TRUE;

-- Add comments for documentation
COMMENT ON COLUMN public.podcasts.is_featured IS 'Whether this podcast is currently featured for the week';
COMMENT ON COLUMN public.podcasts.featured_at IS 'Timestamp when podcast was marked as featured';
