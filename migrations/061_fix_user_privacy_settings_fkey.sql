-- Migration: Fix foreign key constraints to point to auth.users instead of "users"
-- The constraints were incorrectly pointing to "users" instead of "auth.users"
-- This also cleans up any orphaned data before applying constraints

-- STEP 1: Clean up orphaned data (users that don't exist in auth.users)

-- Find and delete orphaned user_profiles
DELETE FROM public.user_profiles
WHERE user_id NOT IN (SELECT id FROM auth.users);

-- Find and delete orphaned user_privacy_settings
DELETE FROM public.user_privacy_settings
WHERE user_id NOT IN (SELECT id FROM auth.users);

-- Find and delete orphaned user_notification_preferences
DELETE FROM public.user_notification_preferences
WHERE user_id NOT IN (SELECT id FROM auth.users);

-- Find and delete orphaned user_connections
DELETE FROM public.user_connections
WHERE follower_id NOT IN (SELECT id FROM auth.users)
   OR following_id NOT IN (SELECT id FROM auth.users);

-- Find and delete orphaned user_signup_tracking
DELETE FROM public.user_signup_tracking
WHERE user_id NOT IN (SELECT id FROM auth.users);

-- STEP 2: Fix foreign key constraints

-- Fix user_profiles
ALTER TABLE public.user_profiles
DROP CONSTRAINT IF EXISTS user_profiles_user_id_fkey;

ALTER TABLE public.user_profiles
ADD CONSTRAINT user_profiles_user_id_fkey
FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

-- Fix user_privacy_settings
ALTER TABLE public.user_privacy_settings
DROP CONSTRAINT IF EXISTS user_privacy_settings_user_id_fkey;

ALTER TABLE public.user_privacy_settings
ADD CONSTRAINT user_privacy_settings_user_id_fkey
FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

-- Fix user_notification_preferences
ALTER TABLE public.user_notification_preferences
DROP CONSTRAINT IF EXISTS user_notification_preferences_user_id_fkey;

ALTER TABLE public.user_notification_preferences
ADD CONSTRAINT user_notification_preferences_user_id_fkey
FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

-- Fix user_connections (follower_id)
ALTER TABLE public.user_connections
DROP CONSTRAINT IF EXISTS user_connections_follower_id_fkey;

ALTER TABLE public.user_connections
ADD CONSTRAINT user_connections_follower_id_fkey
FOREIGN KEY (follower_id) REFERENCES auth.users(id) ON DELETE CASCADE;

-- Fix user_connections (following_id)
ALTER TABLE public.user_connections
DROP CONSTRAINT IF EXISTS user_connections_following_id_fkey;

ALTER TABLE public.user_connections
ADD CONSTRAINT user_connections_following_id_fkey
FOREIGN KEY (following_id) REFERENCES auth.users(id) ON DELETE CASCADE;

-- Fix user_signup_tracking
ALTER TABLE public.user_signup_tracking
DROP CONSTRAINT IF EXISTS user_signup_tracking_user_id_fkey;

ALTER TABLE public.user_signup_tracking
ADD CONSTRAINT user_signup_tracking_user_id_fkey
FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;
