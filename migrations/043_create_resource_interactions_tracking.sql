-- Migration: Create resource interactions tracking system
-- Description: Track user interactions with articles and videos (views, downloads, video playback events)

-- Create resource_interactions table
CREATE TABLE IF NOT EXISTS public.resource_interactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    resource_id UUID NOT NULL REFERENCES public.resources(id) ON DELETE CASCADE,
    interaction_type VARCHAR(50) NOT NULL,
    interaction_data JSONB DEFAULT '{}',
    session_id VARCHAR(255), -- To group related interactions in a single session
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add constraint for valid interaction types
ALTER TABLE public.resource_interactions ADD CONSTRAINT valid_interaction_type
CHECK (interaction_type IN (
    'article_opened',
    'article_read_progress',
    'article_completed',
    'guide_downloaded',
    'video_started',
    'video_played',
    'video_paused',
    'video_seeked',
    'video_progress',
    'video_completed'
));

-- Create user_resource_stats table for aggregated statistics
CREATE TABLE IF NOT EXISTS public.user_resource_stats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    resource_id UUID NOT NULL REFERENCES public.resources(id) ON DELETE CASCADE,
    total_views INTEGER DEFAULT 0,
    total_watch_time INTEGER DEFAULT 0, -- in seconds for videos
    total_read_time INTEGER DEFAULT 0, -- in seconds for articles
    completion_percentage INTEGER DEFAULT 0,
    is_completed BOOLEAN DEFAULT FALSE,
    last_position INTEGER DEFAULT 0, -- last video position in seconds or article scroll position
    first_viewed_at TIMESTAMPTZ DEFAULT NOW(),
    last_viewed_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, resource_id)
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_resource_interactions_user_id ON public.resource_interactions(user_id);
CREATE INDEX IF NOT EXISTS idx_resource_interactions_resource_id ON public.resource_interactions(resource_id);
CREATE INDEX IF NOT EXISTS idx_resource_interactions_type ON public.resource_interactions(interaction_type);
CREATE INDEX IF NOT EXISTS idx_resource_interactions_created_at ON public.resource_interactions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_resource_interactions_session ON public.resource_interactions(session_id);

CREATE INDEX IF NOT EXISTS idx_user_resource_stats_user_id ON public.user_resource_stats(user_id);
CREATE INDEX IF NOT EXISTS idx_user_resource_stats_resource_id ON public.user_resource_stats(resource_id);
CREATE INDEX IF NOT EXISTS idx_user_resource_stats_completed ON public.user_resource_stats(is_completed);
CREATE INDEX IF NOT EXISTS idx_user_resource_stats_last_viewed ON public.user_resource_stats(last_viewed_at DESC);

-- Enable RLS
ALTER TABLE public.resource_interactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_resource_stats ENABLE ROW LEVEL SECURITY;

-- RLS Policies for resource_interactions
DROP POLICY IF EXISTS "Users can view own interactions" ON public.resource_interactions;
DROP POLICY IF EXISTS "Users can insert own interactions" ON public.resource_interactions;

CREATE POLICY "Users can view own interactions"
    ON public.resource_interactions FOR SELECT
    TO authenticated
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own interactions"
    ON public.resource_interactions FOR INSERT
    TO authenticated
    WITH CHECK (auth.uid() = user_id);

-- RLS Policies for user_resource_stats
DROP POLICY IF EXISTS "Users can view own stats" ON public.user_resource_stats;
DROP POLICY IF EXISTS "Users can manage own stats" ON public.user_resource_stats;

CREATE POLICY "Users can view own stats"
    ON public.user_resource_stats FOR SELECT
    TO authenticated
    USING (auth.uid() = user_id);

CREATE POLICY "Users can manage own stats"
    ON public.user_resource_stats FOR ALL
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_resource_interactions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION update_user_resource_stats_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create triggers for updated_at
DROP TRIGGER IF EXISTS update_resource_interactions_updated_at ON public.resource_interactions;
CREATE TRIGGER update_resource_interactions_updated_at
    BEFORE UPDATE ON public.resource_interactions
    FOR EACH ROW
    EXECUTE FUNCTION update_resource_interactions_updated_at();

DROP TRIGGER IF EXISTS update_user_resource_stats_updated_at ON public.user_resource_stats;
CREATE TRIGGER update_user_resource_stats_updated_at
    BEFORE UPDATE ON public.user_resource_stats
    FOR EACH ROW
    EXECUTE FUNCTION update_user_resource_stats_updated_at();

-- Grant permissions
GRANT SELECT, INSERT ON TABLE public.resource_interactions TO authenticated, service_role;
GRANT ALL ON TABLE public.user_resource_stats TO authenticated, service_role;

-- Add comments
COMMENT ON TABLE public.resource_interactions IS 'Tracks individual user interactions with resources (articles, videos, guides)';
COMMENT ON TABLE public.user_resource_stats IS 'Aggregated statistics for user resource consumption';
COMMENT ON COLUMN public.resource_interactions.interaction_type IS 'Type of interaction: article_opened, video_played, video_paused, etc.';
COMMENT ON COLUMN public.resource_interactions.interaction_data IS 'Additional data like video position, article scroll percentage, etc.';
COMMENT ON COLUMN public.resource_interactions.session_id IS 'Groups related interactions within a single viewing session';
COMMENT ON COLUMN public.user_resource_stats.completion_percentage IS 'Percentage of resource completed (0-100)';
COMMENT ON COLUMN public.user_resource_stats.last_position IS 'Last known position - video seconds or article scroll position';
