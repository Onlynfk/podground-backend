-- Migration: Enhance events system with comprehensive features
-- Adds attendee management, tags, calendar integration, and replay functionality

-- Enhance existing events table with new columns
ALTER TABLE public.events 
ADD COLUMN IF NOT EXISTS image_url TEXT,
ADD COLUMN IF NOT EXISTS replay_video_url TEXT,
ADD COLUMN IF NOT EXISTS max_attendees INTEGER DEFAULT 100,
ADD COLUMN IF NOT EXISTS current_attendees INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS price DECIMAL(10,2) DEFAULT 0.00,
ADD COLUMN IF NOT EXISTS is_paid BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS meeting_url TEXT,
ADD COLUMN IF NOT EXISTS calendar_event_id TEXT,
ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}',
ADD COLUMN IF NOT EXISTS event_type VARCHAR(50) DEFAULT 'webinar',
ADD COLUMN IF NOT EXISTS timezone VARCHAR(100) DEFAULT 'UTC',
ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'scheduled',
ADD COLUMN IF NOT EXISTS registration_deadline TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS allow_waitlist BOOLEAN DEFAULT TRUE;

-- Add constraint for event status
ALTER TABLE public.events DROP CONSTRAINT IF EXISTS valid_event_status;
ALTER TABLE public.events ADD CONSTRAINT valid_event_status 
CHECK (status IN ('draft', 'scheduled', 'live', 'completed', 'cancelled'));

-- Add constraint for event type
ALTER TABLE public.events DROP CONSTRAINT IF EXISTS valid_event_type;
ALTER TABLE public.events ADD CONSTRAINT valid_event_type 
CHECK (event_type IN ('webinar', 'workshop', 'networking', 'qa', 'masterclass', 'panel'));

-- Create event attendees table
CREATE TABLE IF NOT EXISTS public.event_attendees (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id UUID NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    status VARCHAR(20) DEFAULT 'registered',
    registered_at TIMESTAMPTZ DEFAULT NOW(),
    attended_at TIMESTAMPTZ,
    check_in_time TIMESTAMPTZ,
    payment_status VARCHAR(20) DEFAULT 'pending',
    stripe_payment_intent_id TEXT,
    notification_preferences JSONB DEFAULT '{"email_reminders": true, "sms_reminders": false}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Ensure unique registration per event
    UNIQUE(event_id, user_id)
);

-- Add constraint for attendee status
ALTER TABLE public.event_attendees ADD CONSTRAINT valid_attendee_status 
CHECK (status IN ('registered', 'waitlisted', 'attended', 'no_show', 'cancelled'));

-- Add constraint for payment status
ALTER TABLE public.event_attendees ADD CONSTRAINT valid_payment_status 
CHECK (payment_status IN ('pending', 'paid', 'failed', 'refunded', 'waived'));

-- Create event tags table
CREATE TABLE IF NOT EXISTS public.event_tags (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    color VARCHAR(7) DEFAULT '#6366f1', -- hex color
    icon_name VARCHAR(50),
    sort_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default event tags
INSERT INTO public.event_tags (name, display_name, description, color, sort_order) VALUES
('community-building', 'Community Building', 'Building and nurturing podcast communities', '#10b981', 1),
('content-creation', 'Content Creation', 'Creating engaging podcast content', '#3b82f6', 2),
('monetization', 'Monetization', 'Strategies for podcast revenue generation', '#f59e0b', 3),
('marketing', 'Marketing', 'Podcast marketing and promotion strategies', '#ef4444', 4),
('production', 'Production', 'Audio production and technical skills', '#8b5cf6', 5),
('networking', 'Networking', 'Building professional connections', '#06b6d4', 6),
('interview-skills', 'Interview Skills', 'Conducting better podcast interviews', '#84cc16', 7),
('analytics', 'Analytics', 'Understanding podcast metrics and growth', '#f97316', 8),
('equipment', 'Equipment', 'Podcast gear and technical setup', '#6b7280', 9),
('storytelling', 'Storytelling', 'Narrative techniques for podcasters', '#ec4899', 10)
ON CONFLICT (name) DO NOTHING;

-- Create event waitlist table
CREATE TABLE IF NOT EXISTS public.event_waitlist (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id UUID NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    position INTEGER,
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    notified_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(event_id, user_id)
);

-- Create event reminders table
CREATE TABLE IF NOT EXISTS public.event_reminders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id UUID NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    reminder_type VARCHAR(20) NOT NULL,
    scheduled_for TIMESTAMPTZ NOT NULL,
    sent_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    CHECK (reminder_type IN ('24h', '1h', '15m', 'custom')),
    CHECK (status IN ('pending', 'sent', 'failed', 'cancelled'))
);

-- Create event feedback table
CREATE TABLE IF NOT EXISTS public.event_feedback (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id UUID NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    rating INTEGER CHECK (rating >= 1 AND rating <= 5),
    feedback_text TEXT,
    would_recommend BOOLEAN,
    topics_rating JSONB, -- {"content": 5, "presentation": 4, "networking": 3}
    submitted_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(event_id, user_id)
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_events_date_status ON public.events(event_date, status);
CREATE INDEX IF NOT EXISTS idx_events_host_user_id ON public.events(host_user_id);
CREATE INDEX IF NOT EXISTS idx_events_tags ON public.events USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_events_location ON public.events(location);
CREATE INDEX IF NOT EXISTS idx_events_is_paid ON public.events(is_paid);

CREATE INDEX IF NOT EXISTS idx_event_attendees_event_id ON public.event_attendees(event_id);
CREATE INDEX IF NOT EXISTS idx_event_attendees_user_id ON public.event_attendees(user_id);
CREATE INDEX IF NOT EXISTS idx_event_attendees_status ON public.event_attendees(status);
CREATE INDEX IF NOT EXISTS idx_event_attendees_registered_at ON public.event_attendees(registered_at);

CREATE INDEX IF NOT EXISTS idx_event_tags_name ON public.event_tags(name);
CREATE INDEX IF NOT EXISTS idx_event_tags_is_active ON public.event_tags(is_active);

CREATE INDEX IF NOT EXISTS idx_event_waitlist_event_id ON public.event_waitlist(event_id);
CREATE INDEX IF NOT EXISTS idx_event_waitlist_position ON public.event_waitlist(event_id, position);

CREATE INDEX IF NOT EXISTS idx_event_reminders_scheduled ON public.event_reminders(scheduled_for, status);

-- Enable RLS on new tables
ALTER TABLE public.event_attendees ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.event_tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.event_waitlist ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.event_reminders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.event_feedback ENABLE ROW LEVEL SECURITY;

-- RLS Policies for event_attendees
CREATE POLICY "Users can see their own event registrations" ON public.event_attendees
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can register for events" ON public.event_attendees
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own registrations" ON public.event_attendees
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Event hosts can see their event attendees" ON public.event_attendees
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.events e 
            WHERE e.id = event_id AND e.host_user_id = auth.uid()
        )
    );

-- RLS Policies for event_tags (public read)
CREATE POLICY "Anyone can view active event tags" ON public.event_tags
    FOR SELECT USING (is_active = true);

-- RLS Policies for event_waitlist
CREATE POLICY "Users can see their own waitlist entries" ON public.event_waitlist
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can join waitlists" ON public.event_waitlist
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can leave waitlists" ON public.event_waitlist
    FOR DELETE USING (auth.uid() = user_id);

-- RLS Policies for event_reminders
CREATE POLICY "Users can see their own reminders" ON public.event_reminders
    FOR SELECT USING (auth.uid() = user_id);

-- RLS Policies for event_feedback
CREATE POLICY "Users can see their own feedback" ON public.event_feedback
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can submit feedback" ON public.event_feedback
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own feedback" ON public.event_feedback
    FOR UPDATE USING (auth.uid() = user_id);

-- Grant permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.event_attendees TO authenticated;
GRANT SELECT ON TABLE public.event_tags TO authenticated;
GRANT SELECT, INSERT, DELETE ON TABLE public.event_waitlist TO authenticated;
GRANT SELECT ON TABLE public.event_reminders TO authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.event_feedback TO authenticated;

GRANT ALL ON TABLE public.event_attendees TO service_role;
GRANT ALL ON TABLE public.event_tags TO service_role;
GRANT ALL ON TABLE public.event_waitlist TO service_role;
GRANT ALL ON TABLE public.event_reminders TO service_role;
GRANT ALL ON TABLE public.event_feedback TO service_role;

-- Database functions for event management
CREATE OR REPLACE FUNCTION register_for_event(
    p_event_id UUID,
    p_user_id UUID
) RETURNS TABLE(success BOOLEAN, message TEXT, attendee_id UUID) AS $$
DECLARE
    event_record RECORD;
    attendee_record RECORD;
    new_attendee_id UUID;
BEGIN
    -- Get event details
    SELECT * INTO event_record FROM public.events WHERE id = p_event_id;
    
    IF NOT FOUND THEN
        RETURN QUERY SELECT false, 'Event not found', NULL::UUID;
        RETURN;
    END IF;
    
    -- Check if event is still open for registration
    IF event_record.status NOT IN ('draft', 'scheduled') THEN
        RETURN QUERY SELECT false, 'Event registration is closed', NULL::UUID;
        RETURN;
    END IF;
    
    -- Check if registration deadline has passed
    IF event_record.registration_deadline IS NOT NULL AND NOW() > event_record.registration_deadline THEN
        RETURN QUERY SELECT false, 'Registration deadline has passed', NULL::UUID;
        RETURN;
    END IF;
    
    -- Check if user is already registered
    SELECT * INTO attendee_record FROM public.event_attendees 
    WHERE event_id = p_event_id AND user_id = p_user_id;
    
    IF FOUND THEN
        RETURN QUERY SELECT false, 'Already registered for this event', attendee_record.id;
        RETURN;
    END IF;
    
    -- Check capacity
    IF event_record.current_attendees >= event_record.max_attendees THEN
        -- Add to waitlist if allowed
        IF event_record.allow_waitlist THEN
            INSERT INTO public.event_waitlist (event_id, user_id, position)
            VALUES (p_event_id, p_user_id, 
                (SELECT COALESCE(MAX(position), 0) + 1 FROM public.event_waitlist WHERE event_id = p_event_id)
            );
            RETURN QUERY SELECT true, 'Added to waitlist', NULL::UUID;
            RETURN;
        ELSE
            RETURN QUERY SELECT false, 'Event is full and waitlist is not available', NULL::UUID;
            RETURN;
        END IF;
    END IF;
    
    -- Register user
    INSERT INTO public.event_attendees (event_id, user_id, payment_status)
    VALUES (p_event_id, p_user_id, CASE WHEN event_record.is_paid THEN 'pending' ELSE 'waived' END)
    RETURNING id INTO new_attendee_id;
    
    -- Update attendee count
    UPDATE public.events 
    SET current_attendees = current_attendees + 1
    WHERE id = p_event_id;
    
    RETURN QUERY SELECT true, 'Successfully registered', new_attendee_id;
END;
$$ LANGUAGE plpgsql SECURITY INVOKER;

-- Grant execute permission on function
GRANT EXECUTE ON FUNCTION register_for_event(UUID, UUID) TO authenticated;

-- Add comments for documentation
COMMENT ON TABLE public.event_attendees IS 'Stores event registrations and attendance tracking';
COMMENT ON TABLE public.event_tags IS 'Available tags for categorizing events';
COMMENT ON TABLE public.event_waitlist IS 'Waitlist for events that are at capacity';
COMMENT ON TABLE public.event_reminders IS 'Automated reminders for registered attendees';
COMMENT ON TABLE public.event_feedback IS 'Post-event feedback and ratings from attendees';

COMMENT ON FUNCTION register_for_event(UUID, UUID) IS 'Registers a user for an event with capacity and waitlist management';