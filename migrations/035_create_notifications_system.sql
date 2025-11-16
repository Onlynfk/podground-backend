-- Create notifications table for SSE-based real-time notifications
-- Migration: 035_create_notifications_system.sql

-- Create notification types enum
CREATE TYPE notification_type AS ENUM (
    'message',              -- New direct message
    'message_reaction',     -- Reaction to your message
    'post_comment',         -- Comment on your post
    'post_like',            -- Like on your post
    'connection_request',   -- New connection request
    'connection_accepted',  -- Connection request accepted
    'mention'               -- Mentioned in a post or comment
);

-- Create notifications table
CREATE TABLE IF NOT EXISTS notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,  -- Recipient of the notification
    type notification_type NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,

    -- Related entity references
    related_user_id UUID,   -- User who triggered the notification
    related_post_id UUID,
    related_message_id UUID,
    related_comment_id UUID,

    -- Metadata
    data JSONB DEFAULT '{}'::jsonb,  -- Additional flexible data

    -- State
    is_read BOOLEAN DEFAULT FALSE,
    read_at TIMESTAMP WITH TIME ZONE,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Foreign keys
    CONSTRAINT fk_notifications_user FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE,
    CONSTRAINT fk_notifications_related_user FOREIGN KEY (related_user_id) REFERENCES auth.users(id) ON DELETE CASCADE,
    CONSTRAINT fk_notifications_post FOREIGN KEY (related_post_id) REFERENCES posts(id) ON DELETE CASCADE,
    CONSTRAINT fk_notifications_message FOREIGN KEY (related_message_id) REFERENCES messages(id) ON DELETE CASCADE
);

-- Create indexes for efficient queries
CREATE INDEX idx_notifications_user_id ON notifications(user_id);
CREATE INDEX idx_notifications_user_unread ON notifications(user_id, is_read) WHERE is_read = FALSE;
CREATE INDEX idx_notifications_created_at ON notifications(created_at DESC);
CREATE INDEX idx_notifications_type ON notifications(type);

-- Enable Row Level Security
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;

-- RLS Policies
-- Users can only view their own notifications
CREATE POLICY "Users can view own notifications"
    ON notifications
    FOR SELECT
    USING (auth.uid() = user_id);

-- Users can only update their own notifications (for marking as read)
CREATE POLICY "Users can update own notifications"
    ON notifications
    FOR UPDATE
    USING (auth.uid() = user_id);

-- Only service role can insert notifications (backend creates them)
CREATE POLICY "Service role can insert notifications"
    ON notifications
    FOR INSERT
    WITH CHECK (true);

-- Only service role can delete notifications
CREATE POLICY "Service role can delete notifications"
    ON notifications
    FOR DELETE
    USING (true);

-- Create function to mark notification as read
CREATE OR REPLACE FUNCTION mark_notification_read(notification_id UUID)
RETURNS void AS $$
BEGIN
    UPDATE notifications
    SET is_read = TRUE,
        read_at = NOW()
    WHERE id = notification_id
    AND user_id = auth.uid();
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Create function to mark all notifications as read for a user
CREATE OR REPLACE FUNCTION mark_all_notifications_read()
RETURNS void AS $$
BEGIN
    UPDATE notifications
    SET is_read = TRUE,
        read_at = NOW()
    WHERE user_id = auth.uid()
    AND is_read = FALSE;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Create function to get unread count
CREATE OR REPLACE FUNCTION get_unread_notification_count()
RETURNS INTEGER AS $$
BEGIN
    RETURN (
        SELECT COUNT(*)::INTEGER
        FROM notifications
        WHERE user_id = auth.uid()
        AND is_read = FALSE
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Create function to clean old read notifications (keep last 30 days)
CREATE OR REPLACE FUNCTION cleanup_old_notifications()
RETURNS void AS $$
BEGIN
    DELETE FROM notifications
    WHERE is_read = TRUE
    AND read_at < NOW() - INTERVAL '30 days';
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON TABLE notifications IS 'Real-time notifications for users via SSE';
COMMENT ON COLUMN notifications.type IS 'Type of notification';
COMMENT ON COLUMN notifications.data IS 'Additional flexible data as JSON';
COMMENT ON COLUMN notifications.related_user_id IS 'User who triggered this notification';
