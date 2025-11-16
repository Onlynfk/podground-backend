-- Fix podcast_categories table if it exists with wrong type
-- This migration handles the case where podcast_categories might have been created with BIGINT id

-- First, check if the table exists and drop foreign key constraints if needed
DO $$ 
BEGIN
    -- Drop the foreign key constraint if it exists
    IF EXISTS (
        SELECT 1 
        FROM information_schema.table_constraints 
        WHERE constraint_name = 'podcasts_category_id_fkey' 
        AND table_name = 'podcasts'
    ) THEN
        ALTER TABLE public.podcasts DROP CONSTRAINT podcasts_category_id_fkey;
    END IF;
    
    -- Check if podcast_categories exists with wrong type
    IF EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'podcast_categories' 
        AND column_name = 'id' 
        AND data_type != 'uuid'
    ) THEN
        -- Drop and recreate the table with correct structure
        DROP TABLE IF EXISTS public.podcast_categories CASCADE;
    END IF;
END $$;

-- Now create/recreate the table with correct structure
CREATE TABLE IF NOT EXISTS public.podcast_categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    color VARCHAR(7) DEFAULT '#6366f1',
    icon_name VARCHAR(50),
    sort_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Re-insert default categories
INSERT INTO public.podcast_categories (name, display_name, description, color, sort_order) VALUES
('arts', 'Arts', 'Visual arts, performing arts, and creative content', '#8b5cf6', 1),
('business', 'Business', 'Entrepreneurship, finance, and professional development', '#0ea5e9', 2),
('comedy', 'Comedy', 'Stand-up, improv, and humorous content', '#f59e0b', 3),
('education', 'Education', 'Learning, academic content, and skill development', '#06b6d4', 4),
('fiction', 'Fiction', 'Storytelling, drama, and fictional narratives', '#ef4444', 5),
('health-fitness', 'Health & Fitness', 'Wellness, exercise, nutrition, and mental health', '#10b981', 6),
('history', 'History', 'Historical events, biographies, and cultural heritage', '#92400e', 7),
('kids-family', 'Kids & Family', 'Family-friendly content and children''s programming', '#f97316', 8),
('leisure', 'Leisure', 'Hobbies, games, and recreational activities', '#ec4899', 9),
('music', 'Music', 'Music industry, reviews, and artist interviews', '#7c3aed', 10),
('news', 'News', 'Current events, journalism, and news analysis', '#374151', 11),
('religion-spirituality', 'Religion & Spirituality', 'Faith, philosophy, and spiritual growth', '#6366f1', 12),
('science', 'Science', 'Research, discoveries, and scientific exploration', '#3b82f6', 13),
('society-culture', 'Society & Culture', 'Social issues, relationships, and cultural commentary', '#dc2626', 14),
('sports', 'Sports', 'Athletics, sports news, and game analysis', '#ea580c', 15),
('technology', 'Technology', 'Tech news, gadgets, and digital innovation', '#059669', 16),
('true-crime', 'True Crime', 'Criminal cases, investigations, and mysteries', '#7f1d1d', 17),
('tv-film', 'TV & Film', 'Entertainment industry, reviews, and behind-the-scenes', '#047857', 18)
ON CONFLICT (name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    color = EXCLUDED.color,
    sort_order = EXCLUDED.sort_order;

-- Now add the foreign key constraint back if podcasts table exists
DO $$ 
BEGIN
    IF EXISTS (
        SELECT 1 
        FROM information_schema.tables 
        WHERE table_name = 'podcasts'
    ) THEN
        ALTER TABLE public.podcasts 
        ADD CONSTRAINT podcasts_category_id_fkey 
        FOREIGN KEY (category_id) 
        REFERENCES public.podcast_categories(id);
    END IF;
END $$;