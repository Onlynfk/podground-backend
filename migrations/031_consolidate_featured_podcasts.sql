-- Migration to consolidate featured_podcasts table into podcasts table
-- This moves all data from featured_podcasts table into the main podcasts table

-- Add the featured columns back to podcasts table
ALTER TABLE public.podcasts 
ADD COLUMN IF NOT EXISTS is_featured BOOLEAN DEFAULT FALSE;

ALTER TABLE public.podcasts 
ADD COLUMN IF NOT EXISTS featured_priority INTEGER DEFAULT 0;

ALTER TABLE public.podcasts 
ADD COLUMN IF NOT EXISTS featured_until TIMESTAMPTZ;

-- First, insert any featured podcasts that aren't already in the podcasts table
INSERT INTO public.podcasts (
    listennotes_id,
    title,
    publisher,
    description,
    image_url,
    thumbnail_url,
    total_episodes,
    explicit_content,
    language,
    is_featured,
    featured_priority,
    created_at,
    updated_at
)
SELECT 
    fp.podcast_id as listennotes_id,
    fp.title,
    fp.publisher,
    fp.description,
    fp.image_url,
    fp.image_url as thumbnail_url,
    COALESCE(fp.total_episodes, 0),
    COALESCE(fp.explicit_content, false),
    'en' as language,
    true as is_featured,
    COALESCE(fp.priority, 0) as featured_priority,
    fp.created_at,
    fp.updated_at
FROM public.featured_podcasts fp
WHERE NOT EXISTS (
    SELECT 1 FROM public.podcasts p 
    WHERE p.listennotes_id = fp.podcast_id
);

-- Update existing podcasts to mark them as featured if they exist in featured_podcasts
UPDATE public.podcasts p
SET 
    is_featured = true,
    featured_priority = COALESCE(fp.priority, 0),
    updated_at = NOW()
FROM public.featured_podcasts fp
WHERE p.listennotes_id = fp.podcast_id;

-- Migrate category mappings from featured_podcast_category_mappings to podcast_category_mappings
INSERT INTO public.podcast_category_mappings (podcast_id, category_id)
SELECT DISTINCT
    p.id as podcast_id,
    fpcm.category_id
FROM public.featured_podcast_category_mappings fpcm
JOIN public.featured_podcasts fp ON fpcm.featured_podcast_id = fp.id
JOIN public.podcasts p ON p.listennotes_id = fp.podcast_id
WHERE NOT EXISTS (
    SELECT 1 FROM public.podcast_category_mappings pcm
    WHERE pcm.podcast_id = p.id AND pcm.category_id = fpcm.category_id
);

-- Drop the featured podcasts tables (commented out for safety - uncomment when ready)
-- DROP TABLE IF EXISTS public.featured_podcast_category_mappings CASCADE;
-- DROP TABLE IF EXISTS public.featured_podcasts CASCADE;

-- Add index on is_featured column for better query performance
CREATE INDEX IF NOT EXISTS idx_podcasts_is_featured ON public.podcasts(is_featured) WHERE is_featured = true;
CREATE INDEX IF NOT EXISTS idx_podcasts_featured_priority ON public.podcasts(featured_priority DESC) WHERE is_featured = true;