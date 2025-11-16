-- Simplify events by removing host_user_id dependency
-- All events are created by PodGround platform

-- Make host_user_id nullable since all events are PodGround events
ALTER TABLE public.events ALTER COLUMN host_user_id DROP NOT NULL;

-- Add a host_name column for display purposes
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='host_name') THEN
        ALTER TABLE public.events ADD COLUMN host_name VARCHAR(255) DEFAULT 'PodGround';
    END IF;
END $$;

-- Update existing events to have PodGround as host
UPDATE public.events SET host_name = 'PodGround' WHERE host_name IS NULL;

-- Drop the foreign key constraint if it exists
ALTER TABLE public.events DROP CONSTRAINT IF EXISTS events_host_user_id_fkey;

-- Update RLS policies to reflect that events are platform-created
DROP POLICY IF EXISTS "Users can create events" ON public.events;
DROP POLICY IF EXISTS "Users can update their own events" ON public.events;
DROP POLICY IF EXISTS "Users can delete their own events" ON public.events;

-- All events are read-only for users (only PodGround admins can create/edit)
CREATE POLICY "Events are read-only for users" ON public.events
    FOR SELECT USING (true);

-- Comment for clarity
COMMENT ON COLUMN public.events.host_user_id IS 'Deprecated - all events are PodGround platform events';
COMMENT ON COLUMN public.events.host_name IS 'Display name of event host (default: PodGround)';