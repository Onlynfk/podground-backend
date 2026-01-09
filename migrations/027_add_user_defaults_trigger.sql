-- Migration: Add automatic default role and subscription assignment for new users
-- This ensures every new user gets default 'podcaster' role and 'free' subscription

-- Function to assign defaults to new users
CREATE OR REPLACE FUNCTION assign_user_defaults()
RETURNS TRIGGER AS $$
BEGIN
    -- Insert default role (podcaster) if not exists
    INSERT INTO public.user_roles (user_id, role, granted_at, is_active)
    VALUES (NEW.id, 'podcaster', NOW(), TRUE)
    ON CONFLICT (user_id, role) DO NOTHING;
    
    -- Insert default subscription (free) if not exists  
    INSERT INTO public.user_subscriptions (user_id, plan_id, status, starts_at)
    VALUES (
        NEW.id,
        (SELECT id FROM public.subscription_plans WHERE name = 'free' LIMIT 1),
        'active',
        NOW()
    )
    ON CONFLICT (user_id) DO NOTHING;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Create trigger that fires when new user is created in auth.users
CREATE TRIGGER trigger_assign_user_defaults
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION assign_user_defaults();

-- Grant execute permission to the function
GRANT EXECUTE ON FUNCTION assign_user_defaults() TO service_role;

-- Add comment
COMMENT ON FUNCTION assign_user_defaults() IS 'Automatically assigns default podcaster role and free subscription to new users';

-- Verify existing users have defaults (backfill any gaps)
-- This handles any users who might have been created between migrations
DO $$
BEGIN
    -- Add missing default roles
    INSERT INTO public.user_roles (user_id, role, granted_at, is_active)
    SELECT 
        au.id,
        'podcaster',
        NOW(),
        TRUE
    FROM auth.users au
    WHERE NOT EXISTS (
        SELECT 1 FROM public.user_roles ur WHERE ur.user_id = au.id
    );
    
    -- Add missing default subscriptions
    INSERT INTO public.user_subscriptions (user_id, plan_id, status, starts_at)
    SELECT 
        au.id,
        (SELECT id FROM public.subscription_plans WHERE name = 'free' LIMIT 1),
        'active',
        NOW()
    FROM auth.users au
    WHERE NOT EXISTS (
        SELECT 1 FROM public.user_subscriptions us WHERE us.user_id = au.id
    );
    
    -- Log results
    RAISE NOTICE 'User defaults assignment completed';
END
$$;