-- Add image_url field to podcast_categories table
-- This allows each category to have an associated image/icon for UI display

BEGIN;

-- Add image_url column to podcast_categories table
ALTER TABLE public.podcast_categories 
ADD COLUMN IF NOT EXISTS image_url TEXT;

-- Add comment to document the field
COMMENT ON COLUMN public.podcast_categories.image_url IS 'URL to category image/icon for UI display';

-- Update existing categories with default images (optional - can be updated later via admin)
UPDATE public.podcast_categories SET 
  image_url = CASE 
    WHEN name = 'arts' THEN 'https://your-cdn.com/icons/arts.svg'
    WHEN name = 'business' THEN 'https://your-cdn.com/icons/business.svg'
    WHEN name = 'comedy' THEN 'https://your-cdn.com/icons/comedy.svg'
    WHEN name = 'education' THEN 'https://your-cdn.com/icons/education.svg'
    WHEN name = 'fiction' THEN 'https://your-cdn.com/icons/fiction.svg'
    WHEN name = 'health-fitness' THEN 'https://your-cdn.com/icons/health-fitness.svg'
    WHEN name = 'history' THEN 'https://your-cdn.com/icons/history.svg'
    WHEN name = 'kids-family' THEN 'https://your-cdn.com/icons/kids-family.svg'
    WHEN name = 'leisure' THEN 'https://your-cdn.com/icons/leisure.svg'
    WHEN name = 'music' THEN 'https://your-cdn.com/icons/music.svg'
    WHEN name = 'news' THEN 'https://your-cdn.com/icons/news.svg'
    WHEN name = 'religion-spirituality' THEN 'https://your-cdn.com/icons/religion.svg'
    WHEN name = 'science' THEN 'https://your-cdn.com/icons/science.svg'
    WHEN name = 'society-culture' THEN 'https://your-cdn.com/icons/society.svg'
    WHEN name = 'sports' THEN 'https://your-cdn.com/icons/sports.svg'
    WHEN name = 'technology' THEN 'https://your-cdn.com/icons/technology.svg'
    WHEN name = 'true-crime' THEN 'https://your-cdn.com/icons/true-crime.svg'
    WHEN name = 'tv-film' THEN 'https://your-cdn.com/icons/tv-film.svg'
    ELSE NULL
  END
WHERE image_url IS NULL;

COMMIT;