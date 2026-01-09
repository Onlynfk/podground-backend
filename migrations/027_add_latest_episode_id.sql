-- Add latest_episode_id field to podcasts table for efficient latest episode lookup
-- This will reference the most recent episode for each podcast

ALTER TABLE public.podcasts 
ADD COLUMN IF NOT EXISTS latest_episode_id UUID REFERENCES public.episodes(id) ON DELETE SET NULL,
ADD COLUMN IF NOT EXISTS latest_episode_updated_at TIMESTAMPTZ;

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_podcasts_latest_episode_id ON public.podcasts(latest_episode_id) WHERE latest_episode_id IS NOT NULL;

-- Function to update latest_episode_id for a podcast
CREATE OR REPLACE FUNCTION update_podcast_latest_episode(p_podcast_id UUID)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    latest_ep_id UUID;
BEGIN
    -- Get the most recent episode ID for this podcast
    SELECT id INTO latest_ep_id
    FROM public.episodes
    WHERE podcast_id = p_podcast_id
      AND published_at IS NOT NULL
    ORDER BY published_at DESC
    LIMIT 1;
    
    -- If no episodes with published_at, fall back to created_at
    IF latest_ep_id IS NULL THEN
        SELECT id INTO latest_ep_id
        FROM public.episodes
        WHERE podcast_id = p_podcast_id
        ORDER BY created_at DESC
        LIMIT 1;
    END IF;
    
    -- Update the podcast with the latest episode ID
    IF latest_ep_id IS NOT NULL THEN
        UPDATE public.podcasts
        SET latest_episode_id = latest_ep_id,
            updated_at = NOW()
        WHERE id = p_podcast_id;
    END IF;
    
    RETURN latest_ep_id;
END;
$$;

-- Function to automatically update latest_episode_id when episodes are inserted/updated
CREATE OR REPLACE FUNCTION trigger_update_latest_episode()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    -- Update the podcast's latest episode when an episode is inserted or updated
    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' THEN
        PERFORM update_podcast_latest_episode(NEW.podcast_id);
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM update_podcast_latest_episode(OLD.podcast_id);
        RETURN OLD;
    END IF;
    RETURN NULL;
END;
$$;

-- Create trigger to automatically update latest_episode_id
DROP TRIGGER IF EXISTS episodes_update_latest_episode_trigger ON public.episodes;
CREATE TRIGGER episodes_update_latest_episode_trigger
    AFTER INSERT OR UPDATE OR DELETE ON public.episodes
    FOR EACH ROW
    EXECUTE FUNCTION trigger_update_latest_episode();

-- Populate latest_episode_id for existing podcasts
DO $$
DECLARE
    podcast_record RECORD;
BEGIN
    FOR podcast_record IN 
        SELECT id FROM public.podcasts WHERE latest_episode_id IS NULL
    LOOP
        PERFORM update_podcast_latest_episode(podcast_record.id);
    END LOOP;
END;
$$;