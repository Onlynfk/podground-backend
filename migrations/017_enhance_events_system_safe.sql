-- Enhanced Events System Migration (Safe Version)
-- This version safely handles existing constraints and tables

-- First, let's safely add new columns to existing events table
DO $$
BEGIN
    -- Add new columns if they don't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='event_date') THEN
        ALTER TABLE public.events ADD COLUMN event_date TIMESTAMPTZ;
        -- Copy from start_date if it exists
        UPDATE public.events SET event_date = start_date WHERE start_date IS NOT NULL;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='category') THEN
        ALTER TABLE public.events ADD COLUMN category VARCHAR(100) DEFAULT 'general';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='event_type') THEN
        ALTER TABLE public.events ADD COLUMN event_type VARCHAR(50) DEFAULT 'webinar';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='max_attendees') THEN
        ALTER TABLE public.events ADD COLUMN max_attendees INTEGER DEFAULT 100;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='current_attendees') THEN
        ALTER TABLE public.events ADD COLUMN current_attendees INTEGER DEFAULT 0;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='is_paid') THEN
        ALTER TABLE public.events ADD COLUMN is_paid BOOLEAN DEFAULT FALSE;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='price') THEN
        ALTER TABLE public.events ADD COLUMN price DECIMAL(10,2) DEFAULT 0.00;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='image_url') THEN
        ALTER TABLE public.events ADD COLUMN image_url TEXT;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='meeting_url') THEN
        ALTER TABLE public.events ADD COLUMN meeting_url TEXT;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='replay_video_url') THEN
        ALTER TABLE public.events ADD COLUMN replay_video_url TEXT;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='tags') THEN
        ALTER TABLE public.events ADD COLUMN tags TEXT[] DEFAULT '{}';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='timezone') THEN
        ALTER TABLE public.events ADD COLUMN timezone VARCHAR(100) DEFAULT 'UTC';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='registration_deadline') THEN
        ALTER TABLE public.events ADD COLUMN registration_deadline TIMESTAMPTZ;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='allow_waitlist') THEN
        ALTER TABLE public.events ADD COLUMN allow_waitlist BOOLEAN DEFAULT TRUE;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='status') THEN
        ALTER TABLE public.events ADD COLUMN status VARCHAR(20) DEFAULT 'scheduled';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='updated_at') THEN
        ALTER TABLE public.events ADD COLUMN updated_at TIMESTAMPTZ DEFAULT NOW();
    END IF;
END $$;

-- Create event_attendees table if it doesn't exist
CREATE TABLE IF NOT EXISTS public.event_attendees (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id UUID NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    status VARCHAR(20) DEFAULT 'registered',
    registered_at TIMESTAMPTZ DEFAULT NOW(),
    attended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(event_id, user_id)
);

-- Add missing columns to event_attendees if they don't exist
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='event_attendees' AND column_name='payment_status') THEN
        ALTER TABLE public.event_attendees ADD COLUMN payment_status VARCHAR(20) DEFAULT 'pending';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='event_attendees' AND column_name='payment_id') THEN
        ALTER TABLE public.event_attendees ADD COLUMN payment_id VARCHAR(255);
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='event_attendees' AND column_name='notes') THEN
        ALTER TABLE public.event_attendees ADD COLUMN notes TEXT;
    END IF;
END $$;

-- Safely add constraints after ensuring columns exist
DO $$
BEGIN
    -- Add attendee status constraint if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.constraint_column_usage WHERE constraint_name='valid_attendee_status') THEN
        ALTER TABLE public.event_attendees ADD CONSTRAINT valid_attendee_status 
        CHECK (status IN ('registered', 'waitlisted', 'attended', 'no_show', 'cancelled'));
    END IF;
    
    -- Add payment status constraint if it doesn't exist (only if column exists)
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='event_attendees' AND column_name='payment_status') 
       AND NOT EXISTS (SELECT 1 FROM information_schema.constraint_column_usage WHERE constraint_name='valid_payment_status') THEN
        ALTER TABLE public.event_attendees ADD CONSTRAINT valid_payment_status 
        CHECK (payment_status IN ('pending', 'paid', 'failed', 'refunded', 'waived'));
    END IF;
END $$;

-- Create event tags table
CREATE TABLE IF NOT EXISTS public.event_tags (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
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

-- Insert default event tags (with conflict handling)
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

-- Create event reminders table
CREATE TABLE IF NOT EXISTS public.event_reminders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id UUID NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    reminder_type VARCHAR(20) NOT NULL,
    scheduled_for TIMESTAMPTZ NOT NULL,
    sent_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add constraints for reminders
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.constraint_column_usage WHERE constraint_name='valid_reminder_type') THEN
        ALTER TABLE public.event_reminders ADD CONSTRAINT valid_reminder_type
        CHECK (reminder_type IN ('24h', '1h', '15m', 'custom'));
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.constraint_column_usage WHERE constraint_name='valid_reminder_status') THEN
        ALTER TABLE public.event_reminders ADD CONSTRAINT valid_reminder_status
        CHECK (status IN ('pending', 'sent', 'failed', 'cancelled'));
    END IF;
END $$;

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_events_event_date ON public.events(event_date);
CREATE INDEX IF NOT EXISTS idx_events_category ON public.events(category);
CREATE INDEX IF NOT EXISTS idx_events_status ON public.events(status);
CREATE INDEX IF NOT EXISTS idx_events_host_user_id ON public.events(host_user_id);
CREATE INDEX IF NOT EXISTS idx_event_attendees_event_id ON public.event_attendees(event_id);
CREATE INDEX IF NOT EXISTS idx_event_attendees_user_id ON public.event_attendees(user_id);
CREATE INDEX IF NOT EXISTS idx_event_attendees_status ON public.event_attendees(status);
CREATE INDEX IF NOT EXISTS idx_event_reminders_scheduled_for ON public.event_reminders(scheduled_for);
CREATE INDEX IF NOT EXISTS idx_event_reminders_status ON public.event_reminders(status);

-- Enable Row Level Security
ALTER TABLE public.events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.event_attendees ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.event_tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.event_reminders ENABLE ROW LEVEL SECURITY;

-- Create RLS policies (with safe handling for existing policies)
DO $$
BEGIN
    -- Events policies
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'events' AND policyname = 'Events are publicly readable') THEN
        CREATE POLICY "Events are publicly readable" ON public.events
            FOR SELECT USING (true);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'events' AND policyname = 'Users can create events') THEN
        CREATE POLICY "Users can create events" ON public.events
            FOR INSERT WITH CHECK (auth.uid() IS NOT NULL);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'events' AND policyname = 'Users can update their own events') THEN
        CREATE POLICY "Users can update their own events" ON public.events
            FOR UPDATE USING (host_user_id = auth.uid());
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'events' AND policyname = 'Users can delete their own events') THEN
        CREATE POLICY "Users can delete their own events" ON public.events
            FOR DELETE USING (host_user_id = auth.uid());
    END IF;

    -- Event attendees policies
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'event_attendees' AND policyname = 'Users can view event attendees') THEN
        CREATE POLICY "Users can view event attendees" ON public.event_attendees
            FOR SELECT USING (true);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'event_attendees' AND policyname = 'Users can register for events') THEN
        CREATE POLICY "Users can register for events" ON public.event_attendees
            FOR INSERT WITH CHECK (user_id = auth.uid());
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'event_attendees' AND policyname = 'Users can update their own registrations') THEN
        CREATE POLICY "Users can update their own registrations" ON public.event_attendees
            FOR UPDATE USING (user_id = auth.uid());
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'event_attendees' AND policyname = 'Users can delete their own registrations') THEN
        CREATE POLICY "Users can delete their own registrations" ON public.event_attendees
            FOR DELETE USING (user_id = auth.uid());
    END IF;

    -- Event tags policies (public read)
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'event_tags' AND policyname = 'Event tags are publicly readable') THEN
        CREATE POLICY "Event tags are publicly readable" ON public.event_tags
            FOR SELECT USING (is_active = true);
    END IF;

    -- Event reminders policies
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'event_reminders' AND policyname = 'Users can view their own reminders') THEN
        CREATE POLICY "Users can view their own reminders" ON public.event_reminders
            FOR SELECT USING (user_id = auth.uid());
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'event_reminders' AND policyname = 'System can manage reminders') THEN
        CREATE POLICY "System can manage reminders" ON public.event_reminders
            FOR ALL USING (true);
    END IF;
END $$;