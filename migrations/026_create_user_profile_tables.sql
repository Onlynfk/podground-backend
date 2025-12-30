-- Migration: Create user profile system tables
-- Description: Tables for user profiles, interests, connections, and activity tracking

-- Create user_profiles table
CREATE TABLE IF NOT EXISTS user_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    bio TEXT,
    location VARCHAR(255),
    avatar_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id)
);

-- Note: topics table already exists from migration 002
-- It has additional columns: slug, description, icon_url, follower_count
-- We'll use the existing table structure

-- Create user_interests junction table
CREATE TABLE IF NOT EXISTS user_interests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    topic_id UUID NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, topic_id)
);

-- Note: user_connections table already exists from migration 002
-- It uses follower_id/following_id instead of requester_id/requestee_id
-- We'll use the existing table structure

-- Create user_activity table for activity feed
CREATE TABLE IF NOT EXISTS user_activity (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    activity_type VARCHAR(50) NOT NULL,
    activity_data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_user_profiles_user_id ON user_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_interests_user_id ON user_interests(user_id);
CREATE INDEX IF NOT EXISTS idx_user_interests_topic_id ON user_interests(topic_id);
-- Indexes for existing user_connections table (uses follower_id/following_id)
CREATE INDEX IF NOT EXISTS idx_user_connections_follower ON user_connections(follower_id);
CREATE INDEX IF NOT EXISTS idx_user_connections_following ON user_connections(following_id);
CREATE INDEX IF NOT EXISTS idx_user_connections_status ON user_connections(status);
CREATE INDEX IF NOT EXISTS idx_user_activity_user_id ON user_activity(user_id);
CREATE INDEX IF NOT EXISTS idx_user_activity_type ON user_activity(activity_type);
CREATE INDEX IF NOT EXISTS idx_user_activity_created_at ON user_activity(created_at DESC);

-- Create updated_at trigger function for user_profiles
CREATE OR REPLACE FUNCTION update_user_profiles_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger for user_profiles updated_at
DROP TRIGGER IF EXISTS update_user_profiles_updated_at ON user_profiles;
CREATE TRIGGER update_user_profiles_updated_at
    BEFORE UPDATE ON user_profiles
    FOR EACH ROW
    EXECUTE FUNCTION update_user_profiles_updated_at();

-- Enable Row Level Security
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_interests ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_activity ENABLE ROW LEVEL SECURITY;

-- RLS Policies for user_profiles
DROP POLICY IF EXISTS "Users can view all profiles" ON user_profiles;
DROP POLICY IF EXISTS "Users can update own profile" ON user_profiles;
DROP POLICY IF EXISTS "Users can insert own profile" ON user_profiles;

CREATE POLICY "Users can view all profiles"
    ON user_profiles FOR SELECT
    TO authenticated
    USING (true);

CREATE POLICY "Users can update own profile"
    ON user_profiles FOR UPDATE
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can insert own profile"
    ON user_profiles FOR INSERT
    TO authenticated
    WITH CHECK (auth.uid() = user_id);

-- RLS Policies for user_interests
DROP POLICY IF EXISTS "Users can view all interests" ON user_interests;
DROP POLICY IF EXISTS "Users can manage own interests" ON user_interests;

CREATE POLICY "Users can view all interests"
    ON user_interests FOR SELECT
    TO authenticated
    USING (true);

CREATE POLICY "Users can manage own interests"
    ON user_interests FOR ALL
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- RLS Policies for user_connections (using existing follower_id/following_id columns)
DROP POLICY IF EXISTS "Users can view their connections" ON user_connections;
DROP POLICY IF EXISTS "Users can manage their connections" ON user_connections;

CREATE POLICY "Users can view their connections"
    ON user_connections FOR SELECT
    TO authenticated
    USING (auth.uid() = follower_id OR auth.uid() = following_id);

CREATE POLICY "Users can manage their connections"
    ON user_connections FOR ALL
    TO authenticated
    USING (auth.uid() = follower_id OR auth.uid() = following_id)
    WITH CHECK (auth.uid() = follower_id OR auth.uid() = following_id);

-- RLS Policies for user_activity
DROP POLICY IF EXISTS "Users can view all activity" ON user_activity;
DROP POLICY IF EXISTS "System can insert activity" ON user_activity;

CREATE POLICY "Users can view all activity"
    ON user_activity FOR SELECT
    TO authenticated
    USING (true);

CREATE POLICY "System can insert activity"
    ON user_activity FOR INSERT
    TO authenticated
    WITH CHECK (true);

-- Topics table is public readable
ALTER TABLE topics ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Anyone can view topics" ON topics;
CREATE POLICY "Anyone can view topics"
    ON topics FOR SELECT
    TO authenticated
    USING (true);

-- Grant permissions
GRANT ALL ON user_profiles TO authenticated, service_role;
GRANT ALL ON topics TO authenticated, service_role;
GRANT ALL ON user_interests TO authenticated, service_role;
GRANT ALL ON user_connections TO authenticated, service_role;
GRANT ALL ON user_activity TO authenticated, service_role;

-- Note: Default topics already inserted in migration 002
-- Skip duplicate insertions

-- Add comments
COMMENT ON TABLE user_profiles IS 'Extended user profile information beyond basic auth data';
COMMENT ON TABLE topics IS 'Available topics/interests for users to select';
COMMENT ON TABLE user_interests IS 'Junction table for user topic interests';
COMMENT ON TABLE user_connections IS 'User connection requests and relationships';
COMMENT ON TABLE user_activity IS 'User activity tracking for feed generation';