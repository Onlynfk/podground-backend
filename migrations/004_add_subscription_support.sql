-- Migration: Add subscription and role support
-- This adds subscription tiers, role management, and access control

-- Create subscription plans table
CREATE TABLE IF NOT EXISTS public.subscription_plans (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    price_monthly DECIMAL(10,2) DEFAULT 0.00,
    price_yearly DECIMAL(10,2) DEFAULT 0.00,
    features JSONB DEFAULT '[]'::jsonb,
    can_access_premium_resources BOOLEAN DEFAULT FALSE,
    can_access_analytics BOOLEAN DEFAULT FALSE,
    can_create_events BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default subscription plans
INSERT INTO public.subscription_plans (name, display_name, description, price_monthly, price_yearly, features, can_access_premium_resources, can_access_analytics, can_create_events) VALUES
('free', 'Free', 'Basic podcaster features', 0.00, 0.00, '["basic_posts", "basic_connections", "community_access"]'::jsonb, FALSE, FALSE, FALSE),
('pro', 'Pro', 'Full podcaster features', 9.99, 99.99, '["everything_in_free", "premium_resources", "analytics", "event_creation", "priority_support", "advanced_features"]'::jsonb, TRUE, TRUE, TRUE);

-- Create user subscriptions table
CREATE TABLE IF NOT EXISTS public.user_subscriptions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    plan_id INTEGER NOT NULL REFERENCES public.subscription_plans(id),
    status VARCHAR(50) NOT NULL DEFAULT 'active', -- active, cancelled, expired, trial
    starts_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ends_at TIMESTAMPTZ,
    trial_ends_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    stripe_subscription_id VARCHAR(255),
    stripe_customer_id VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id) -- One active subscription per user
);

-- Create user roles table (for admin vs podcaster)
CREATE TABLE IF NOT EXISTS public.user_roles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL DEFAULT 'podcaster', -- admin, podcaster
    granted_by UUID REFERENCES auth.users(id),
    granted_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ, -- NULL = never expires
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, role)
);

-- Add subscription tier to resources table
ALTER TABLE public.resources 
ADD COLUMN IF NOT EXISTS required_plan VARCHAR(50) DEFAULT 'free',
ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE;

-- Add subscription tier to events table  
ALTER TABLE public.events
ADD COLUMN IF NOT EXISTS required_plan VARCHAR(50) DEFAULT 'free',
ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE;

-- Function to get user's current subscription plan
CREATE OR REPLACE FUNCTION get_user_subscription_plan(input_user_id UUID)
RETURNS TABLE(plan_name VARCHAR, plan_id INTEGER, status VARCHAR, is_premium BOOLEAN) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        sp.name,
        sp.id,
        us.status,
        (sp.price_monthly > 0 OR sp.price_yearly > 0) as is_premium
    FROM public.user_subscriptions us
    JOIN public.subscription_plans sp ON us.plan_id = sp.id
    WHERE us.user_id = input_user_id 
    AND us.status = 'active'
    AND (us.ends_at IS NULL OR us.ends_at > NOW())
    LIMIT 1;
    
    -- If no subscription found, return free plan
    IF NOT FOUND THEN
        RETURN QUERY
        SELECT 
            sp.name,
            sp.id,
            'active'::VARCHAR as status,
            FALSE as is_premium
        FROM public.subscription_plans sp
        WHERE sp.name = 'free'
        LIMIT 1;
    END IF;
END;
$$ LANGUAGE plpgsql;


-- Grant permissions
GRANT ALL ON TABLE public.subscription_plans TO authenticated;
GRANT ALL ON TABLE public.user_subscriptions TO authenticated;  
GRANT ALL ON TABLE public.user_roles TO authenticated;
GRANT EXECUTE ON FUNCTION get_user_subscription_plan(UUID) TO authenticated;

-- RLS Policies
ALTER TABLE public.user_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_roles ENABLE ROW LEVEL SECURITY;

-- Users can only see their own subscriptions
CREATE POLICY "Users can view own subscriptions" ON public.user_subscriptions FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users can view own roles" ON public.user_roles FOR SELECT USING (auth.uid() = user_id);

-- Admin policies (service role can manage all)
CREATE POLICY "Service role can manage subscriptions" ON public.user_subscriptions FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Service role can manage roles" ON public.user_roles FOR ALL USING (auth.role() = 'service_role');

-- Create default free subscriptions for existing users
INSERT INTO public.user_subscriptions (user_id, plan_id, status)
SELECT 
    au.id,
    (SELECT id FROM public.subscription_plans WHERE name = 'free' LIMIT 1),
    'active'
FROM auth.users au
WHERE NOT EXISTS (
    SELECT 1 FROM public.user_subscriptions us WHERE us.user_id = au.id
);

-- Create default podcaster roles for existing users  
INSERT INTO public.user_roles (user_id, role)
SELECT 
    au.id,
    'podcaster'
FROM auth.users au
WHERE NOT EXISTS (
    SELECT 1 FROM public.user_roles ur WHERE ur.user_id = au.id
);