-- Migration: Add post categorization system with AI classification
-- This adds categories table and category_id to posts for AI-driven categorization

-- Categories table for post categorization (separate from podcast categories)
CREATE TABLE IF NOT EXISTS public.post_categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    keywords TEXT[], -- Keywords to help AI classification
    color VARCHAR(7) DEFAULT '#6366f1',
    sort_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add category to posts table
ALTER TABLE public.posts 
ADD COLUMN IF NOT EXISTS category_id UUID REFERENCES public.post_categories(id);

-- Insert default post categories for AI classification
INSERT INTO public.post_categories (name, display_name, description, keywords, color, sort_order) VALUES
('technology', 'Technology', 'Tech news, gadgets, software, AI, and digital innovation', ARRAY['tech', 'technology', 'software', 'ai', 'artificial intelligence', 'gadgets', 'programming', 'coding', 'startup', 'innovation'], '#059669', 1),
('business', 'Business', 'Entrepreneurship, finance, marketing, and professional development', ARRAY['business', 'entrepreneur', 'finance', 'marketing', 'sales', 'money', 'investment', 'startup', 'career', 'professional'], '#0ea5e9', 2),
('health-wellness', 'Health & Wellness', 'Fitness, nutrition, mental health, and wellbeing', ARRAY['health', 'fitness', 'wellness', 'nutrition', 'exercise', 'mental health', 'wellbeing', 'meditation', 'therapy', 'diet'], '#10b981', 3),
('entertainment', 'Entertainment', 'Movies, TV shows, music, games, and pop culture', ARRAY['entertainment', 'movies', 'tv', 'music', 'games', 'gaming', 'celebrity', 'culture', 'fun', 'comedy'], '#f59e0b', 4),
('education', 'Education', 'Learning, tutorials, academic content, and skill development', ARRAY['education', 'learning', 'tutorial', 'course', 'study', 'teaching', 'school', 'university', 'knowledge', 'skills'], '#06b6d4', 5),
('lifestyle', 'Lifestyle', 'Daily life, hobbies, travel, food, and personal experiences', ARRAY['lifestyle', 'travel', 'food', 'cooking', 'hobbies', 'fashion', 'home', 'family', 'personal', 'experience'], '#ec4899', 6),
('science', 'Science', 'Research, discoveries, space, nature, and scientific exploration', ARRAY['science', 'research', 'discovery', 'space', 'nature', 'biology', 'physics', 'chemistry', 'environment', 'climate'], '#3b82f6', 7),
('news-politics', 'News & Politics', 'Current events, politics, social issues, and world news', ARRAY['news', 'politics', 'current events', 'government', 'society', 'social', 'world', 'breaking', 'election', 'policy'], '#dc2626', 8),
('sports', 'Sports', 'Athletics, sports news, fitness, and competitive activities', ARRAY['sports', 'football', 'basketball', 'soccer', 'baseball', 'athletics', 'competition', 'team', 'player', 'game'], '#ea580c', 9),
('arts-creativity', 'Arts & Creativity', 'Visual arts, writing, design, and creative expression', ARRAY['art', 'creative', 'design', 'writing', 'painting', 'photography', 'creativity', 'artist', 'craft', 'inspiration'], '#8b5cf6', 10),
('personal-development', 'Personal Development', 'Self-improvement, productivity, motivation, and life advice', ARRAY['personal development', 'self improvement', 'productivity', 'motivation', 'goals', 'habits', 'mindset', 'growth', 'success', 'advice'], '#7c3aed', 11),
('general', 'General', 'General discussions and topics that don\'t fit other categories', ARRAY['general', 'discussion', 'thoughts', 'random', 'misc', 'other', 'question', 'opinion'], '#6b7280', 12)
ON CONFLICT (name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    keywords = EXCLUDED.keywords,
    color = EXCLUDED.color,
    sort_order = EXCLUDED.sort_order;

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_posts_category_id ON public.posts(category_id);
CREATE INDEX IF NOT EXISTS idx_posts_category_created_at ON public.posts(category_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_post_categories_active ON public.post_categories(is_active, sort_order);

-- Enable RLS on post_categories (read-only for users)
ALTER TABLE public.post_categories ENABLE ROW LEVEL SECURITY;

-- RLS policy: Anyone can read active categories
CREATE POLICY "post_categories_select_policy" ON public.post_categories
    FOR SELECT USING (is_active = true);

-- Update RLS policy for posts to include category_id
DROP POLICY IF EXISTS "posts_select_policy" ON public.posts;
CREATE POLICY "posts_select_policy" ON public.posts
    FOR SELECT USING (
        deleted_at IS NULL AND 
        is_published = true
    );

COMMENT ON TABLE public.post_categories IS 'Categories for automatically classifying posts using AI';
COMMENT ON COLUMN public.posts.category_id IS 'AI-assigned category for this post';