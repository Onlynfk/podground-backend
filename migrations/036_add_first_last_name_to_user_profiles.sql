-- Migration: Add first_name and last_name to user_profiles
-- Description: Add first_name and last_name columns to user_profiles table for better name management

-- Add first_name and last_name columns to user_profiles
ALTER TABLE public.user_profiles
ADD COLUMN IF NOT EXISTS first_name VARCHAR(100),
ADD COLUMN IF NOT EXISTS last_name VARCHAR(100);

-- Create indexes for name searches (optional but useful for performance)
CREATE INDEX IF NOT EXISTS idx_user_profiles_first_name ON public.user_profiles(first_name);
CREATE INDEX IF NOT EXISTS idx_user_profiles_last_name ON public.user_profiles(last_name);

-- Add comments
COMMENT ON COLUMN public.user_profiles.first_name IS 'User first name';
COMMENT ON COLUMN public.user_profiles.last_name IS 'User last name';
