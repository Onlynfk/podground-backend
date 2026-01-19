-- Podcast System Redesign Migration
-- Implements PostgreSQL-based caching strategy with minimal storage

-- 1. Add new columns to existing podcasts table
ALTER TABLE public.podcasts 
ADD COLUMN IF NOT EXISTS is_claimed BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS claimed_by_user_id UUID REFERENCES auth.users(id),
ADD COLUMN IF NOT EXISTS is_cached BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS cached_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS cache_expires_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS first_episode_date TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS latest_episode_date TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS episode_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS website_url TEXT,
ADD COLUMN IF NOT EXISTS listen_score INTEGER; -- ListenNotes listen score

-- Create index for claimed podcasts
CREATE INDEX IF NOT EXISTS idx_podcasts_claimed ON public.podcasts(claimed_by_user_id) WHERE is_claimed = TRUE;

-- Create index for cached podcasts
CREATE INDEX IF NOT EXISTS idx_podcasts_cached ON public.podcasts(is_cached, cache_expires_at) WHERE is_cached = TRUE;

-- 2. Create podcast search cache table
CREATE TABLE IF NOT EXISTS public.podcast_search_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Search parameters (composite key)
    search_query TEXT NOT NULL,
    genre_id INTEGER, -- ListenNotes genre ID
    sort_by VARCHAR(50) DEFAULT 'relevance',
    
    -- Cached result
    listennotes_id VARCHAR(50) NOT NULL,
    title VARCHAR(500) NOT NULL,
    publisher VARCHAR(255),
    description TEXT,
    image_url TEXT,
    total_episodes INTEGER,
    first_episode_date TIMESTAMPTZ,
    latest_episode_date TIMESTAMPTZ,
    listen_score INTEGER,
    
    -- Cache metadata
    cached_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '24 hours',
    
    -- Create composite unique constraint
    UNIQUE(search_query, genre_id, sort_by, listennotes_id)
);

-- Create indexes for search cache
CREATE INDEX IF NOT EXISTS idx_search_cache_query ON public.podcast_search_cache(search_query, genre_id, sort_by);
CREATE INDEX IF NOT EXISTS idx_search_cache_expires ON public.podcast_search_cache(expires_at);

-- 3. Create episode cache table (for followed podcasts only)
CREATE TABLE IF NOT EXISTS public.episode_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Episode identifiers
    listennotes_episode_id VARCHAR(50) UNIQUE NOT NULL,
    podcast_listennotes_id VARCHAR(50) NOT NULL,
    
    -- Episode data
    title VARCHAR(500) NOT NULL,
    description TEXT,
    audio_url TEXT NOT NULL,
    image_url TEXT,
    duration_seconds INTEGER,
    published_at TIMESTAMPTZ,
    
    -- Cache metadata
    cached_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '7 days',
    
    -- Index for finding episodes by podcast
    INDEX idx_episode_cache_podcast (podcast_listennotes_id),
    INDEX idx_episode_cache_expires (expires_at)
);

-- 4. Merge featured_podcasts into main podcasts table
-- First, update podcasts table with featured podcast data if it exists
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'featured_podcasts') THEN
        -- Update existing podcasts with featured data
        UPDATE public.podcasts p
        SET 
            is_featured = TRUE,
            featured_priority = fp.priority,
            title = COALESCE(p.title, fp.title),
            publisher = COALESCE(p.publisher, fp.publisher),
            description = COALESCE(p.description, fp.description),
            image_url = COALESCE(p.image_url, fp.image_url)
        FROM featured_podcasts fp
        WHERE p.listennotes_id = fp.podcast_id;
        
        -- Insert featured podcasts that don't exist yet
        INSERT INTO public.podcasts (
            listennotes_id,
            title,
            publisher,
            description,
            image_url,
            is_featured,
            featured_priority
        )
        SELECT 
            fp.podcast_id,
            fp.title,
            fp.publisher,
            fp.description,
            fp.image_url,
            TRUE,
            fp.priority
        FROM featured_podcasts fp
        LEFT JOIN public.podcasts p ON p.listennotes_id = fp.podcast_id
        WHERE p.id IS NULL;
        
        -- Drop the featured_podcasts table
        DROP TABLE featured_podcasts;
    END IF;
END $$;

-- 5. Create function to clean up expired cache entries
CREATE OR REPLACE FUNCTION cleanup_expired_cache()
RETURNS void AS $$
BEGIN
    -- Delete expired search cache entries
    DELETE FROM public.podcast_search_cache
    WHERE expires_at < NOW();
    
    -- Delete expired episode cache entries
    DELETE FROM public.episode_cache
    WHERE expires_at < NOW();
    
    -- Update podcast cache status
    UPDATE public.podcasts
    SET is_cached = FALSE
    WHERE is_cached = TRUE AND cache_expires_at < NOW();
END;
$$ LANGUAGE plpgsql;

-- 6. Create function to cache podcast from ListenNotes data
CREATE OR REPLACE FUNCTION cache_podcast_from_api(
    p_listennotes_id VARCHAR(50),
    p_title VARCHAR(500),
    p_publisher VARCHAR(255),
    p_description TEXT,
    p_image_url TEXT,
    p_rss_url TEXT,
    p_website_url TEXT,
    p_total_episodes INTEGER,
    p_first_episode_date TIMESTAMPTZ,
    p_latest_episode_date TIMESTAMPTZ,
    p_listen_score INTEGER,
    p_genre_id INTEGER
) RETURNS UUID AS $$
DECLARE
    v_podcast_id UUID;
    v_category_id UUID;
BEGIN
    -- Get category ID from genre mapping
    SELECT category_id INTO v_category_id
    FROM public.category_genre
    WHERE genre_id = p_genre_id
    LIMIT 1;
    
    -- Insert or update podcast
    INSERT INTO public.podcasts (
        listennotes_id,
        title,
        publisher,
        description,
        image_url,
        rss_url,
        website_url,
        total_episodes,
        first_episode_date,
        latest_episode_date,
        listen_score,
        category_id,
        is_cached,
        cached_at,
        cache_expires_at
    ) VALUES (
        p_listennotes_id,
        p_title,
        p_publisher,
        p_description,
        p_image_url,
        p_rss_url,
        p_website_url,
        p_total_episodes,
        p_first_episode_date,
        p_latest_episode_date,
        p_listen_score,
        v_category_id,
        TRUE,
        NOW(),
        NOW() + INTERVAL '7 days'
    )
    ON CONFLICT (listennotes_id) DO UPDATE
    SET
        title = EXCLUDED.title,
        publisher = EXCLUDED.publisher,
        description = EXCLUDED.description,
        image_url = EXCLUDED.image_url,
        rss_url = EXCLUDED.rss_url,
        website_url = EXCLUDED.website_url,
        total_episodes = EXCLUDED.total_episodes,
        first_episode_date = EXCLUDED.first_episode_date,
        latest_episode_date = EXCLUDED.latest_episode_date,
        listen_score = EXCLUDED.listen_score,
        category_id = EXCLUDED.category_id,
        is_cached = TRUE,
        cached_at = NOW(),
        cache_expires_at = NOW() + INTERVAL '7 days',
        updated_at = NOW()
    RETURNING id INTO v_podcast_id;
    
    RETURN v_podcast_id;
END;
$$ LANGUAGE plpgsql;

-- 7. Update episodes table to work with new system
ALTER TABLE public.episodes
ADD COLUMN IF NOT EXISTS is_cached BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS cached_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS cache_expires_at TIMESTAMPTZ;

-- Create index for cached episodes
CREATE INDEX IF NOT EXISTS idx_episodes_cached ON public.episodes(is_cached, cache_expires_at) WHERE is_cached = TRUE;

-- 8. Create view for user's followed podcasts with cache status
CREATE OR REPLACE VIEW user_followed_podcasts_view AS
SELECT 
    upf.user_id,
    p.id,
    p.listennotes_id,
    p.title,
    p.publisher,
    p.description,
    p.image_url,
    p.total_episodes,
    p.latest_episode_date,
    p.is_cached,
    p.cache_expires_at,
    upf.followed_at,
    upf.notification_enabled,
    CASE 
        WHEN p.is_cached AND p.cache_expires_at > NOW() THEN 'cached'
        ELSE 'needs_refresh'
    END as cache_status
FROM public.user_podcast_follows upf
JOIN public.podcasts p ON upf.podcast_id = p.id;

-- 9. Enable RLS on new tables
ALTER TABLE public.podcast_search_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.episode_cache ENABLE ROW LEVEL SECURITY;

-- RLS policies for search cache (public read)
CREATE POLICY "Search cache is publicly readable" 
ON public.podcast_search_cache 
FOR SELECT 
USING (true);

-- RLS policies for episode cache (public read)
CREATE POLICY "Episode cache is publicly readable" 
ON public.episode_cache 
FOR SELECT 
USING (true);

-- Only service role can manage cache
CREATE POLICY "Service role manages search cache" 
ON public.podcast_search_cache 
FOR ALL 
USING (auth.role() = 'service_role');

CREATE POLICY "Service role manages episode cache" 
ON public.episode_cache 
FOR ALL 
USING (auth.role() = 'service_role');

-- 10. Create scheduled job function (to be called by external scheduler)
CREATE OR REPLACE FUNCTION refresh_followed_podcasts_cache()
RETURNS void AS $$
DECLARE
    v_podcast RECORD;
BEGIN
    -- Get all followed podcasts that need cache refresh
    FOR v_podcast IN 
        SELECT DISTINCT p.listennotes_id
        FROM public.user_podcast_follows upf
        JOIN public.podcasts p ON upf.podcast_id = p.id
        WHERE p.is_cached = FALSE 
           OR p.cache_expires_at < NOW() + INTERVAL '1 day'
    LOOP
        -- This would trigger an API call in the application layer
        -- For now, just mark it as needing refresh
        UPDATE public.podcasts
        SET is_cached = FALSE
        WHERE listennotes_id = v_podcast.listennotes_id;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- Add comment explaining the architecture
COMMENT ON TABLE public.podcast_search_cache IS 'Temporary cache for ListenNotes search results. Expires after 24 hours.';
COMMENT ON TABLE public.episode_cache IS 'Temporary cache for episodes of followed podcasts. Expires after 7 days.';
COMMENT ON COLUMN public.podcasts.is_cached IS 'Whether this podcast data is from cache or permanently stored (featured/claimed)';