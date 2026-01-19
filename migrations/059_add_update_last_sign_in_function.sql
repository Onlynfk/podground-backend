-- Migration: Add function to update last_sign_in_at in auth.users
-- This function allows the application to update the last_sign_in_at timestamp
-- when users sign in via custom verification codes (not through native Supabase auth flows)

-- Create function to update last_sign_in_at
CREATE OR REPLACE FUNCTION public.update_user_last_sign_in(user_id_input UUID)
RETURNS VOID AS $$
BEGIN
    -- Update the last_sign_in_at timestamp in auth.users
    UPDATE auth.users
    SET last_sign_in_at = NOW()
    WHERE id = user_id_input;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Grant execute permission to authenticated users and service role
GRANT EXECUTE ON FUNCTION public.update_user_last_sign_in(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION public.update_user_last_sign_in(UUID) TO service_role;

-- Comment on function
COMMENT ON FUNCTION public.update_user_last_sign_in(UUID) IS
'Updates the last_sign_in_at timestamp for a user in auth.users table. Used when custom authentication flows (like verification codes) are used instead of native Supabase auth.';
