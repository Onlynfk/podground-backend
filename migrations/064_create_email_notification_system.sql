-- Migration: Create email notification system
-- Description: Tables for queuing and logging email notifications with twice-daily batching

-- Table to queue pending email notifications
CREATE TABLE IF NOT EXISTS email_notification_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    notification_type VARCHAR(50) NOT NULL,  -- 'post_reply', 'post_reaction', 'new_message', 'connection_request', 'podcast_follow', 'podcast_listen'
    actor_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,  -- Who triggered this notification (optional)
    resource_id UUID,  -- Post ID, message ID, podcast ID, etc. (optional)
    metadata JSONB DEFAULT '{}',  -- Additional data if needed
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    processed_at TIMESTAMP WITH TIME ZONE,  -- When it was included in a batch
    sent_at TIMESTAMP WITH TIME ZONE  -- When the email was actually sent
);

-- Table to log sent email batches
CREATE TABLE IF NOT EXISTS email_notification_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    notification_count INT NOT NULL DEFAULT 0,
    notification_types JSONB DEFAULT '{}',  -- {'post_reply': 3, 'post_reaction': 5, ...}
    customer_io_response JSONB,  -- Response from Customer.io API
    batch_time TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    sent_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_email_queue_user_id ON email_notification_queue(user_id);
CREATE INDEX IF NOT EXISTS idx_email_queue_processed ON email_notification_queue(processed_at) WHERE processed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_email_queue_type ON email_notification_queue(notification_type);
CREATE INDEX IF NOT EXISTS idx_email_queue_created ON email_notification_queue(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_log_user_id ON email_notification_log(user_id);
CREATE INDEX IF NOT EXISTS idx_email_log_sent_at ON email_notification_log(sent_at DESC);

-- Comments for documentation
COMMENT ON TABLE email_notification_queue IS 'Queue for pending email notifications that will be sent in batches';
COMMENT ON TABLE email_notification_log IS 'Log of sent email notification batches for analytics and debugging';
COMMENT ON COLUMN email_notification_queue.notification_type IS 'Type: post_reply, post_reaction, new_message, connection_request, podcast_follow, podcast_listen';
COMMENT ON COLUMN email_notification_queue.actor_id IS 'User who triggered the notification (who replied, reacted, sent message, etc.)';
COMMENT ON COLUMN email_notification_queue.processed_at IS 'When this notification was processed into a batch (NULL = pending)';

-- Enable Row Level Security
ALTER TABLE email_notification_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_notification_log ENABLE ROW LEVEL SECURITY;

-- RLS Policies for email_notification_queue
-- Users can only view their own notifications
CREATE POLICY "Users can view their own notifications"
    ON email_notification_queue
    FOR SELECT
    USING (auth.uid() = user_id);

-- Service role can do everything (for backend processing)
CREATE POLICY "Service role has full access to notification queue"
    ON email_notification_queue
    FOR ALL
    USING (auth.role() = 'service_role');

-- RLS Policies for email_notification_log
-- Users can only view their own notification logs
CREATE POLICY "Users can view their own notification logs"
    ON email_notification_log
    FOR SELECT
    USING (auth.uid() = user_id);

-- Service role can do everything (for backend processing)
CREATE POLICY "Service role has full access to notification log"
    ON email_notification_log
    FOR ALL
    USING (auth.role() = 'service_role');

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'Created email notification system tables with RLS enabled';
END $$;
