-- Migration 033: Implement conversation limits system for free users (FIXED)
-- Track conversation usage per 30-day cycle from user signup

-- Create table to track conversation limits and usage
CREATE TABLE IF NOT EXISTS public.user_conversation_limits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    
    -- Current 30-day cycle info
    cycle_start_date TIMESTAMPTZ NOT NULL, -- Start of current 30-day cycle
    cycle_end_date TIMESTAMPTZ NOT NULL,   -- End of current 30-day cycle
    
    -- Usage tracking
    conversations_used INTEGER DEFAULT 0,
    max_conversations INTEGER DEFAULT 5,    -- Free plan limit
    
    -- Track individual conversations in this cycle
    conversation_ids TEXT[] DEFAULT ARRAY[]::TEXT[], -- Array of conversation IDs started in this cycle
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Ensure one record per user
    UNIQUE(user_id)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_user_conversation_limits_user ON public.user_conversation_limits(user_id);
CREATE INDEX IF NOT EXISTS idx_user_conversation_limits_cycle ON public.user_conversation_limits(cycle_start_date, cycle_end_date);

-- Enable RLS
ALTER TABLE public.user_conversation_limits ENABLE ROW LEVEL SECURITY;

-- RLS Policy - users can only see/modify their own limits
CREATE POLICY "Users can manage their own conversation limits" 
ON public.user_conversation_limits FOR ALL USING (user_id = auth.uid());

-- Function to get user signup date and plan type
CREATE OR REPLACE FUNCTION get_user_plan_info(user_uuid UUID)
RETURNS TABLE (
    signup_date TIMESTAMPTZ,
    plan_type VARCHAR(20)
) AS $$
BEGIN
    -- Return user signup date and plan type
    -- Use auth.users.created_at as signup date
    -- Check subscriptions for plan type (free is default)
    RETURN QUERY
    SELECT 
        COALESCE(ust.signup_at, au.created_at) as signup_date,
        CASE 
            WHEN sp.name IN ('premium', 'pro') AND us.status = 'active' THEN sp.name
            ELSE 'free'
        END::VARCHAR(20) as plan_type
    FROM auth.users au
    LEFT JOIN public.user_signup_tracking ust ON au.id = ust.user_id
    LEFT JOIN public.user_subscriptions us ON au.id = us.user_id AND us.status = 'active'
    LEFT JOIN public.subscription_plans sp ON us.plan_id = sp.id
    WHERE au.id = user_uuid;
END;
$$ LANGUAGE plpgsql;

-- Function to initialize conversation limits for new users
CREATE OR REPLACE FUNCTION initialize_user_conversation_limits(user_uuid UUID, user_signup_date TIMESTAMPTZ)
RETURNS VOID AS $$
DECLARE
    cycle_start TIMESTAMPTZ;
    cycle_end TIMESTAMPTZ;
BEGIN
    -- Calculate current cycle based on signup date
    -- Each cycle is 30 days from signup date
    cycle_start := user_signup_date + (FLOOR(EXTRACT(EPOCH FROM (NOW() - user_signup_date)) / (30 * 24 * 3600)) * INTERVAL '30 days');
    cycle_end := cycle_start + INTERVAL '30 days';
    
    -- Insert or update conversation limits
    INSERT INTO public.user_conversation_limits (
        user_id, 
        cycle_start_date, 
        cycle_end_date, 
        conversations_used,
        max_conversations
    ) VALUES (
        user_uuid,
        cycle_start,
        cycle_end,
        0,
        5  -- Free plan default
    )
    ON CONFLICT (user_id) DO UPDATE SET
        cycle_start_date = EXCLUDED.cycle_start_date,
        cycle_end_date = EXCLUDED.cycle_end_date,
        updated_at = NOW();
END;
$$ LANGUAGE plpgsql;

-- Function to check if user can start new conversation
CREATE OR REPLACE FUNCTION can_user_start_conversation(user_uuid UUID)
RETURNS BOOLEAN AS $$
DECLARE
    user_limits RECORD;
    current_cycle_start TIMESTAMPTZ;
    current_cycle_end TIMESTAMPTZ;
    user_info RECORD;
BEGIN
    -- Get user signup date and plan
    SELECT * INTO user_info FROM get_user_plan_info(user_uuid);
    
    -- If no user found, deny
    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;
    
    -- Premium/pro users have unlimited conversations
    IF user_info.plan_type != 'free' THEN
        RETURN TRUE;
    END IF;
    
    -- Calculate current cycle
    current_cycle_start := user_info.signup_date + (FLOOR(EXTRACT(EPOCH FROM (NOW() - user_info.signup_date)) / (30 * 24 * 3600)) * INTERVAL '30 days');
    current_cycle_end := current_cycle_start + INTERVAL '30 days';
    
    -- Get user's current limits
    SELECT * INTO user_limits 
    FROM public.user_conversation_limits 
    WHERE user_id = user_uuid;
    
    -- If no limits record, create one and allow
    IF NOT FOUND THEN
        PERFORM initialize_user_conversation_limits(user_uuid, user_info.signup_date);
        RETURN TRUE;
    END IF;
    
    -- Check if we're in a new cycle
    IF NOW() >= user_limits.cycle_end_date THEN
        -- Reset for new cycle
        UPDATE public.user_conversation_limits 
        SET 
            cycle_start_date = current_cycle_start,
            cycle_end_date = current_cycle_end,
            conversations_used = 0,
            conversation_ids = ARRAY[]::TEXT[],
            updated_at = NOW()
        WHERE user_id = user_uuid;
        
        RETURN TRUE;
    END IF;
    
    -- Check if under limit
    RETURN user_limits.conversations_used < user_limits.max_conversations;
END;
$$ LANGUAGE plpgsql;

-- Function to record new conversation
CREATE OR REPLACE FUNCTION record_new_conversation(user_uuid UUID, conversation_id TEXT)
RETURNS BOOLEAN AS $$
DECLARE
    user_limits RECORD;
    user_info RECORD;
BEGIN
    -- Get current limits
    SELECT * INTO user_limits 
    FROM public.user_conversation_limits 
    WHERE user_id = user_uuid;
    
    -- If no record, initialize first
    IF NOT FOUND THEN
        SELECT * INTO user_info FROM get_user_plan_info(user_uuid);
        IF FOUND THEN
            PERFORM initialize_user_conversation_limits(user_uuid, user_info.signup_date);
        END IF;
    END IF;
    
    -- Add conversation and increment count
    UPDATE public.user_conversation_limits 
    SET 
        conversations_used = conversations_used + 1,
        conversation_ids = array_append(conversation_ids, conversation_id),
        updated_at = NOW()
    WHERE user_id = user_uuid;
    
    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- Function to get user conversation status
CREATE OR REPLACE FUNCTION get_user_conversation_status(user_uuid UUID)
RETURNS TABLE (
    conversations_used INTEGER,
    max_conversations INTEGER,
    conversations_remaining INTEGER,
    cycle_start_date TIMESTAMPTZ,
    cycle_end_date TIMESTAMPTZ,
    days_until_reset INTEGER,
    can_start_new BOOLEAN
) AS $$
DECLARE
    user_info RECORD;
BEGIN
    -- Get user info
    SELECT * INTO user_info FROM get_user_plan_info(user_uuid);
    
    -- If no user found, return empty
    IF NOT FOUND THEN
        RETURN;
    END IF;
    
    -- Premium users have unlimited
    IF user_info.plan_type != 'free' THEN
        RETURN QUERY SELECT 
            0::INTEGER, 
            999999::INTEGER, 
            999999::INTEGER, 
            NOW()::TIMESTAMPTZ, 
            (NOW() + INTERVAL '30 days')::TIMESTAMPTZ, 
            30::INTEGER, 
            TRUE::BOOLEAN;
        RETURN;
    END IF;
    
    -- Ensure limits are initialized
    PERFORM initialize_user_conversation_limits(user_uuid, user_info.signup_date);
    
    -- Return current status
    RETURN QUERY 
    SELECT 
        ucl.conversations_used,
        ucl.max_conversations,
        GREATEST(0, ucl.max_conversations - ucl.conversations_used) as conversations_remaining,
        ucl.cycle_start_date,
        ucl.cycle_end_date,
        GREATEST(0, EXTRACT(DAYS FROM (ucl.cycle_end_date - NOW()))::INTEGER) as days_until_reset,
        (ucl.conversations_used < ucl.max_conversations)::BOOLEAN as can_start_new
    FROM public.user_conversation_limits ucl
    WHERE ucl.user_id = user_uuid;
END;
$$ LANGUAGE plpgsql;

-- Initialize limits for existing users (using auth.users table)
INSERT INTO public.user_conversation_limits (user_id, cycle_start_date, cycle_end_date, conversations_used, max_conversations)
SELECT 
    au.id,
    COALESCE(ust.signup_at, au.created_at) + (FLOOR(EXTRACT(EPOCH FROM (NOW() - COALESCE(ust.signup_at, au.created_at))) / (30 * 24 * 3600)) * INTERVAL '30 days') as cycle_start,
    COALESCE(ust.signup_at, au.created_at) + ((FLOOR(EXTRACT(EPOCH FROM (NOW() - COALESCE(ust.signup_at, au.created_at))) / (30 * 24 * 3600)) + 1) * INTERVAL '30 days') as cycle_end,
    0 as conversations_used,
    CASE 
        WHEN sp.name IN ('premium', 'pro') AND us.status = 'active' THEN 999999
        ELSE 5
    END as max_conversations
FROM auth.users au
LEFT JOIN public.user_signup_tracking ust ON au.id = ust.user_id
LEFT JOIN public.user_subscriptions us ON au.id = us.user_id AND us.status = 'active'
LEFT JOIN public.subscription_plans sp ON us.plan_id = sp.id
ON CONFLICT (user_id) DO NOTHING;