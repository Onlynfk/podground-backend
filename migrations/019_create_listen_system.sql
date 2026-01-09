-- Listen System Database Schema
-- Comprehensive podcast discovery, playback, and user personalization

-- Create podcast categories table (drop if exists with wrong structure)
DROP TABLE IF EXISTS public.podcast_categories CASCADE;

CREATE TABLE public.podcast_categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    color VARCHAR(7) DEFAULT '#6366f1', -- hex color for UI
    icon_name VARCHAR(50),
    sort_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create podcasts table (shows)
CREATE TABLE IF NOT EXISTS public.podcasts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- External identifiers
    listennotes_id VARCHAR(50) UNIQUE, -- from ListenNotes API
    rss_url TEXT,
    
    -- Basic info
    title VARCHAR(500) NOT NULL,
    description TEXT,
    publisher VARCHAR(255),
    language VARCHAR(10) DEFAULT 'en',
    
    -- Media
    image_url TEXT,
    thumbnail_url TEXT,
    
    -- Metadata
    category_id UUID REFERENCES public.podcast_categories(id),
    total_episodes INTEGER DEFAULT 0,
    explicit_content BOOLEAN DEFAULT FALSE,
    
    -- PodGround features
    is_featured BOOLEAN DEFAULT FALSE,
    featured_priority INTEGER DEFAULT 0, -- higher = more prominent
    featured_until TIMESTAMPTZ, -- featured expiry
    is_network BOOLEAN DEFAULT FALSE, -- is this a podcast network?
    network_id UUID REFERENCES public.podcasts(id), -- belongs to network
    
    -- Stats
    follower_count INTEGER DEFAULT 0,
    listen_score DECIMAL(3,2) DEFAULT 0.0, -- 0-5 rating
    
    -- Timestamps
    last_episode_date TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Search
    search_vector tsvector
);

-- Create episodes table
CREATE TABLE IF NOT EXISTS public.episodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    podcast_id UUID NOT NULL REFERENCES public.podcasts(id) ON DELETE CASCADE,
    
    -- External identifiers
    listennotes_id VARCHAR(50) UNIQUE,
    guid VARCHAR(255), -- from RSS
    
    -- Basic info
    title VARCHAR(500) NOT NULL,
    description TEXT,
    
    -- Media
    audio_url TEXT,
    image_url TEXT,
    duration_seconds INTEGER, -- episode length in seconds
    file_size_bytes BIGINT,
    mime_type VARCHAR(50),
    
    -- Metadata
    episode_number INTEGER,
    season_number INTEGER,
    episode_type VARCHAR(20) DEFAULT 'full', -- full, trailer, bonus
    explicit_content BOOLEAN DEFAULT FALSE,
    
    -- Timestamps
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Search
    search_vector tsvector
);

-- User podcast follows
CREATE TABLE IF NOT EXISTS public.user_podcast_follows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    podcast_id UUID NOT NULL REFERENCES public.podcasts(id) ON DELETE CASCADE,
    followed_at TIMESTAMPTZ DEFAULT NOW(),
    notification_enabled BOOLEAN DEFAULT TRUE,
    
    UNIQUE(user_id, podcast_id)
);

-- User episode saves/bookmarks
CREATE TABLE IF NOT EXISTS public.user_episode_saves (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    episode_id UUID NOT NULL REFERENCES public.episodes(id) ON DELETE CASCADE,
    saved_at TIMESTAMPTZ DEFAULT NOW(),
    notes TEXT, -- user notes about episode
    
    UNIQUE(user_id, episode_id)
);

-- User listening progress/history
CREATE TABLE IF NOT EXISTS public.user_listening_progress (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    episode_id UUID NOT NULL REFERENCES public.episodes(id) ON DELETE CASCADE,
    
    -- Progress tracking
    progress_seconds INTEGER DEFAULT 0, -- how far into episode
    duration_seconds INTEGER, -- total episode length (cached)
    progress_percentage DECIMAL(5,2) DEFAULT 0.0, -- calculated percentage
    
    -- Status
    is_completed BOOLEAN DEFAULT FALSE,
    is_currently_playing BOOLEAN DEFAULT FALSE,
    playback_speed DECIMAL(3,2) DEFAULT 1.0, -- 0.5x, 1x, 1.5x, 2x
    
    -- Timestamps
    started_at TIMESTAMPTZ DEFAULT NOW(),
    last_played_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    
    UNIQUE(user_id, episode_id)
);

-- Podcast ratings/reviews (future feature)
CREATE TABLE IF NOT EXISTS public.user_podcast_ratings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    podcast_id UUID NOT NULL REFERENCES public.podcasts(id) ON DELETE CASCADE,
    rating INTEGER CHECK (rating >= 1 AND rating <= 5),
    review_text TEXT,
    is_public BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(user_id, podcast_id)
);

-- Insert default podcast categories
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
ON CONFLICT (name) DO NOTHING;

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_podcasts_featured ON public.podcasts(is_featured, featured_priority DESC);
CREATE INDEX IF NOT EXISTS idx_podcasts_category ON public.podcasts(category_id);
CREATE INDEX IF NOT EXISTS idx_podcasts_network ON public.podcasts(network_id) WHERE is_network = false;
CREATE INDEX IF NOT EXISTS idx_podcasts_listennotes ON public.podcasts(listennotes_id);
CREATE INDEX IF NOT EXISTS idx_podcasts_search ON public.podcasts USING GIN(search_vector);

CREATE INDEX IF NOT EXISTS idx_episodes_podcast ON public.episodes(podcast_id);
CREATE INDEX IF NOT EXISTS idx_episodes_published ON public.episodes(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_episodes_listennotes ON public.episodes(listennotes_id);
CREATE INDEX IF NOT EXISTS idx_episodes_search ON public.episodes USING GIN(search_vector);

CREATE INDEX IF NOT EXISTS idx_user_follows_user ON public.user_podcast_follows(user_id);
CREATE INDEX IF NOT EXISTS idx_user_follows_podcast ON public.user_podcast_follows(podcast_id);

CREATE INDEX IF NOT EXISTS idx_user_saves_user ON public.user_episode_saves(user_id, saved_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_saves_episode ON public.user_episode_saves(episode_id);

CREATE INDEX IF NOT EXISTS idx_user_progress_user ON public.user_listening_progress(user_id, last_played_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_progress_episode ON public.user_listening_progress(episode_id);
CREATE INDEX IF NOT EXISTS idx_user_progress_current ON public.user_listening_progress(user_id, is_currently_playing) WHERE is_currently_playing = true;

-- Enable Row Level Security
ALTER TABLE public.podcast_categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.podcasts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.episodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_podcast_follows ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_episode_saves ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_listening_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_podcast_ratings ENABLE ROW LEVEL SECURITY;

-- RLS Policies for public read access
CREATE POLICY "Categories are publicly readable" ON public.podcast_categories FOR SELECT USING (is_active = true);
CREATE POLICY "Podcasts are publicly readable" ON public.podcasts FOR SELECT USING (true);
CREATE POLICY "Episodes are publicly readable" ON public.episodes FOR SELECT USING (true);

-- RLS Policies for user data
CREATE POLICY "Users can manage their own follows" ON public.user_podcast_follows FOR ALL USING (user_id = auth.uid());
CREATE POLICY "Users can manage their own saves" ON public.user_episode_saves FOR ALL USING (user_id = auth.uid());
CREATE POLICY "Users can manage their own progress" ON public.user_listening_progress FOR ALL USING (user_id = auth.uid());
CREATE POLICY "Users can manage their own ratings" ON public.user_podcast_ratings FOR ALL USING (user_id = auth.uid());

-- Functions for search vectors
CREATE OR REPLACE FUNCTION update_podcast_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector := to_tsvector('english', 
        COALESCE(NEW.title, '') || ' ' || 
        COALESCE(NEW.description, '') || ' ' || 
        COALESCE(NEW.publisher, '')
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION update_episode_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector := to_tsvector('english', 
        COALESCE(NEW.title, '') || ' ' || 
        COALESCE(NEW.description, '')
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create triggers for search vectors
CREATE TRIGGER podcast_search_vector_trigger
    BEFORE INSERT OR UPDATE ON public.podcasts
    FOR EACH ROW EXECUTE FUNCTION update_podcast_search_vector();

CREATE TRIGGER episode_search_vector_trigger
    BEFORE INSERT OR UPDATE ON public.episodes
    FOR EACH ROW EXECUTE FUNCTION update_episode_search_vector();

-- Function to update podcast follower counts
CREATE OR REPLACE FUNCTION update_podcast_follower_count()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE public.podcasts SET follower_count = follower_count + 1 WHERE id = NEW.podcast_id;
    ELSIF TG_OP = 'DELETE' THEN
        UPDATE public.podcasts SET follower_count = follower_count - 1 WHERE id = OLD.podcast_id;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Trigger for follower count updates
CREATE TRIGGER update_follower_count_trigger
    AFTER INSERT OR DELETE ON public.user_podcast_follows
    FOR EACH ROW EXECUTE FUNCTION update_podcast_follower_count();