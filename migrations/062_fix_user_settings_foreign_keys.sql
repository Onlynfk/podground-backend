-- Migration: Fix foreign key constraints on user settings tables
-- Description: Drop and recreate foreign key constraints to properly reference auth.users

-- Fix user_privacy_settings foreign key
ALTER TABLE user_privacy_settings
DROP CONSTRAINT IF EXISTS user_privacy_settings_user_id_fkey;

ALTER TABLE user_privacy_settings
ADD CONSTRAINT user_privacy_settings_user_id_fkey
FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

-- Fix user_notification_preferences foreign key
ALTER TABLE user_notification_preferences
DROP CONSTRAINT IF EXISTS user_notification_preferences_user_id_fkey;

ALTER TABLE user_notification_preferences
ADD CONSTRAINT user_notification_preferences_user_id_fkey
FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

-- Log completion
DO $$
BEGIN
  RAISE NOTICE 'Fixed foreign key constraints on user settings tables to reference auth.users';
END $$;
