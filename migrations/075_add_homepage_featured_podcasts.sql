-- Migration: Add homepage featured podcasts support
-- Description: Add is_homepage_featured column to podcasts table for homepage featured section

-- Add is_homepage_featured column to podcasts table
ALTER TABLE public.podcasts
ADD COLUMN IF NOT EXISTS is_homepage_featured BOOLEAN DEFAULT FALSE;

-- Create index for efficient homepage featured podcast queries
CREATE INDEX IF NOT EXISTS idx_podcasts_is_homepage_featured ON public.podcasts(is_homepage_featured) WHERE is_homepage_featured = TRUE;

-- Add comment for documentation
COMMENT ON COLUMN public.podcasts.is_homepage_featured IS 'Whether this podcast is currently featured on the homepage';
