-- Migration: Create episode listens tracking table
-- Description: Track when users start listening to episodes (for notifications and analytics)

CREATE TABLE IF NOT EXISTS public.episode_listens (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    episode_id UUID NOT NULL REFERENCES public.episodes(id) ON DELETE CASCADE,
    podcast_id UUID NOT NULL REFERENCES public.podcasts(id) ON DELETE CASCADE,
    listened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, episode_id)  -- One listen record per user per episode
);

-- Create indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_episode_listens_user_id ON public.episode_listens(user_id);
CREATE INDEX IF NOT EXISTS idx_episode_listens_episode_id ON public.episode_listens(episode_id);
CREATE INDEX IF NOT EXISTS idx_episode_listens_podcast_id ON public.episode_listens(podcast_id);
CREATE INDEX IF NOT EXISTS idx_episode_listens_listened_at ON public.episode_listens(listened_at DESC);

-- Add RLS policies
ALTER TABLE public.episode_listens ENABLE ROW LEVEL SECURITY;

-- Users can view their own listens
CREATE POLICY "Users can view their own episode listens"
    ON public.episode_listens
    FOR SELECT
    USING (auth.uid() = user_id);

-- Users can insert their own listens
CREATE POLICY "Users can insert their own episode listens"
    ON public.episode_listens
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Service role can manage all listens
CREATE POLICY "Service role can manage all episode listens"
    ON public.episode_listens
    FOR ALL
    USING (auth.role() = 'service_role');

-- Add comments
COMMENT ON TABLE public.episode_listens IS 'Tracks when users start listening to podcast episodes';
COMMENT ON COLUMN public.episode_listens.listened_at IS 'Timestamp when user started listening to the episode';
