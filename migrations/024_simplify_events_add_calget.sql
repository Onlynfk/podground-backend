-- Migration: Simplify events system - remove registration/attendees, add Calget link
-- This migration adds external calendar link support and removes internal registration system

-- Add calget_link column to events table
ALTER TABLE public.events 
ADD COLUMN IF NOT EXISTS calget_link TEXT;

-- Add comment for clarity
COMMENT ON COLUMN public.events.calget_link IS 'External Calget calendar page URL for event registration/details';

-- Drop event_attendees table as we no longer need internal registration
DROP TABLE IF EXISTS public.event_attendees CASCADE;

-- Remove unused columns related to internal registration
ALTER TABLE public.events 
DROP COLUMN IF EXISTS attendee_count,
DROP COLUMN IF EXISTS max_attendees,
DROP COLUMN IF EXISTS current_attendees,
DROP COLUMN IF EXISTS registration_deadline,
DROP COLUMN IF EXISTS allow_waitlist;

-- Update event type constraint if needed (optional - keep existing event types)
-- The event types can remain the same as they describe the type of event, not registration method

-- Create index on calget_link for potential filtering
CREATE INDEX IF NOT EXISTS idx_events_calget_link ON public.events(calget_link) WHERE calget_link IS NOT NULL;

-- Update some sample events with Calget links (optional - for testing)
-- UPDATE public.events 
-- SET calget_link = 'https://calget.com/event/sample-event-id'
-- WHERE id = 'some-uuid' AND calget_link IS NULL;