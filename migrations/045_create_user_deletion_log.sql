-- Migration: Create User Deletion Log Table
-- Tracks deleted user accounts for audit purposes

-- Create user_deletion_log table
CREATE TABLE IF NOT EXISTS user_deletion_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    email TEXT NOT NULL,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    account_created_at TIMESTAMP WITH TIME ZONE,
    deleted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted_by UUID, -- NULL if self-deleted, admin user ID if admin deleted
    deletion_reason TEXT,
    user_profile_snapshot JSONB, -- Store snapshot of user profile data
    deletion_metadata JSONB DEFAULT '{}'::jsonb, -- Store counts of deleted records
    ip_address TEXT,
    user_agent TEXT
);

-- Create indexes
CREATE INDEX idx_user_deletion_log_user_id ON user_deletion_log(user_id);
CREATE INDEX idx_user_deletion_log_email ON user_deletion_log(email);
CREATE INDEX idx_user_deletion_log_deleted_at ON user_deletion_log(deleted_at DESC);

-- Enable RLS
ALTER TABLE user_deletion_log ENABLE ROW LEVEL SECURITY;

-- RLS Policies - Only admins can access deletion logs
-- For now, no user access (future: add admin role check)
CREATE POLICY "No user access to deletion logs"
    ON user_deletion_log
    FOR ALL
    USING (false);

-- Add comments
COMMENT ON TABLE user_deletion_log IS 'Audit log of deleted user accounts';
COMMENT ON COLUMN user_deletion_log.user_id IS 'Original user ID from auth.users';
COMMENT ON COLUMN user_deletion_log.deleted_by IS 'NULL for self-deletion, admin user ID for admin-initiated deletion';
COMMENT ON COLUMN user_deletion_log.deletion_metadata IS 'JSON object with counts of deleted records (posts, comments, messages, etc.)';
COMMENT ON COLUMN user_deletion_log.user_profile_snapshot IS 'Complete snapshot of user profile data before deletion';
