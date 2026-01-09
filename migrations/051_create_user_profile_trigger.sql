-- Migration: Auto-create user_profiles when auth users are created
-- Description: Ensures every auth.users record has a corresponding user_profiles record

-- Function to create user profile for new users
CREATE OR REPLACE FUNCTION create_user_profile_for_new_user()
RETURNS TRIGGER AS $$
BEGIN
    -- Insert user profile record for the new auth user
    INSERT INTO public.user_profiles (user_id, created_at, updated_at)
    VALUES (NEW.id, NOW(), NOW())
    ON CONFLICT (user_id) DO NOTHING;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Create trigger that fires when new user is created in auth.users
DROP TRIGGER IF EXISTS trigger_create_user_profile_on_signup ON auth.users;
CREATE TRIGGER trigger_create_user_profile_on_signup
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION create_user_profile_for_new_user();

-- Grant execute permission to the function
GRANT EXECUTE ON FUNCTION create_user_profile_for_new_user() TO service_role;

-- Add comment
COMMENT ON FUNCTION create_user_profile_for_new_user() IS 'Automatically creates a user_profiles record when a new user signs up';

-- Backfill: Create user_profiles for existing auth users that don't have one
DO $$
DECLARE
    missing_profiles_count INTEGER;
BEGIN
    -- Create missing user profiles
    INSERT INTO public.user_profiles (user_id, created_at, updated_at)
    SELECT
        au.id,
        au.created_at,  -- Use the auth user's creation time
        NOW()
    FROM auth.users au
    WHERE NOT EXISTS (
        SELECT 1 FROM public.user_profiles up WHERE up.user_id = au.id
    );

    -- Get count of profiles created
    GET DIAGNOSTICS missing_profiles_count = ROW_COUNT;

    -- Log results
    RAISE NOTICE 'Created % missing user profile(s)', missing_profiles_count;
END
$$;
