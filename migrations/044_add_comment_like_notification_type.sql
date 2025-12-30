-- Add comment_like to notification_type enum
-- Migration: 044_add_comment_like_notification_type.sql

-- Add the new enum value
ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'comment_like';

COMMENT ON TYPE notification_type IS 'Notification types: message, message_reaction, post_comment, post_like, comment_like, connection_request, connection_accepted, mention';
