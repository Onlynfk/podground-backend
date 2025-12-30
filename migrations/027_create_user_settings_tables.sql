-- Migration: Create User Settings Tables
-- Description: Creates tables for user notification preferences and privacy settings

-- Create user_notification_preferences table
CREATE TABLE IF NOT EXISTS user_notification_preferences (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,

    -- Activity & Engagement
    new_follower BOOLEAN DEFAULT true,
    replies_to_comments BOOLEAN DEFAULT true,
    direct_messages BOOLEAN DEFAULT true,

    -- Content Updates
    new_episodes_from_followed_shows BOOLEAN DEFAULT true,
    recommended_episodes BOOLEAN DEFAULT true,

    -- Events & Announcements
    upcoming_events_and_workshops BOOLEAN DEFAULT true,
    product_updates_and_new_features BOOLEAN DEFAULT true,
    promotions_and_partner_deals BOOLEAN DEFAULT false,

    -- Notification Methods
    email_notifications BOOLEAN DEFAULT true,
    push_notifications BOOLEAN DEFAULT true,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create user_privacy_settings table
CREATE TABLE IF NOT EXISTS user_privacy_settings (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,

    -- Privacy Controls
    profile_visibility BOOLEAN DEFAULT true,
    search_visibility BOOLEAN DEFAULT true,
    show_activity_status BOOLEAN DEFAULT true,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_user_notification_preferences_user_id ON user_notification_preferences(user_id);
CREATE INDEX IF NOT EXISTS idx_user_privacy_settings_user_id ON user_privacy_settings(user_id);

-- Create trigger to update updated_at timestamp for notification preferences
CREATE OR REPLACE FUNCTION update_user_notification_preferences_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_user_notification_preferences_updated_at
    BEFORE UPDATE ON user_notification_preferences
    FOR EACH ROW
    EXECUTE FUNCTION update_user_notification_preferences_updated_at();

-- Create trigger to update updated_at timestamp for privacy settings
CREATE OR REPLACE FUNCTION update_user_privacy_settings_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_user_privacy_settings_updated_at
    BEFORE UPDATE ON user_privacy_settings
    FOR EACH ROW
    EXECUTE FUNCTION update_user_privacy_settings_updated_at();

-- Enable Row Level Security (RLS)
ALTER TABLE user_notification_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_privacy_settings ENABLE ROW LEVEL SECURITY;

-- Create RLS policies for notification preferences
CREATE POLICY "Users can view their own notification preferences"
    ON user_notification_preferences
    FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can update their own notification preferences"
    ON user_notification_preferences
    FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their own notification preferences"
    ON user_notification_preferences
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Create RLS policies for privacy settings
CREATE POLICY "Users can view their own privacy settings"
    ON user_privacy_settings
    FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can update their own privacy settings"
    ON user_privacy_settings
    FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their own privacy settings"
    ON user_privacy_settings
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Grant necessary permissions
GRANT SELECT, INSERT, UPDATE ON user_notification_preferences TO authenticated;
GRANT SELECT, INSERT, UPDATE ON user_privacy_settings TO authenticated;

-- Comment on tables
COMMENT ON TABLE user_notification_preferences IS 'Stores user notification preferences for various event types';
COMMENT ON TABLE user_privacy_settings IS 'Stores user privacy and visibility settings';
