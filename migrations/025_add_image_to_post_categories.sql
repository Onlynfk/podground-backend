-- Add image field to post_categories table
-- This allows each category to have an associated image/icon

BEGIN;

-- Add image_url column to post_categories table
ALTER TABLE public.post_categories 
ADD COLUMN IF NOT EXISTS image_url TEXT;

-- Add comment to document the field
COMMENT ON COLUMN public.post_categories.image_url IS 'URL to category image/icon for UI display';

-- Update existing categories with default images (optional - can be updated later via admin)
UPDATE public.post_categories SET 
  image_url = CASE 
    WHEN name = 'technology' THEN 'https://your-cdn.com/icons/technology.svg'
    WHEN name = 'business' THEN 'https://your-cdn.com/icons/business.svg'
    WHEN name = 'health_wellness' THEN 'https://your-cdn.com/icons/health.svg'
    WHEN name = 'entertainment' THEN 'https://your-cdn.com/icons/entertainment.svg'
    WHEN name = 'education' THEN 'https://your-cdn.com/icons/education.svg'
    WHEN name = 'lifestyle' THEN 'https://your-cdn.com/icons/lifestyle.svg'
    WHEN name = 'science' THEN 'https://your-cdn.com/icons/science.svg'
    WHEN name = 'news_politics' THEN 'https://your-cdn.com/icons/news.svg'
    WHEN name = 'sports' THEN 'https://your-cdn.com/icons/sports.svg'
    WHEN name = 'arts_creativity' THEN 'https://your-cdn.com/icons/arts.svg'
    WHEN name = 'personal_development' THEN 'https://your-cdn.com/icons/personal.svg'
    WHEN name = 'general' THEN 'https://your-cdn.com/icons/general.svg'
    ELSE NULL
  END
WHERE image_url IS NULL;

COMMIT;