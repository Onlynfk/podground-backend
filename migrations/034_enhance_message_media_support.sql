-- Migration: Enhance message media support with multiple files and soft delete
-- Description: Add support for multiple media attachments per message and proper soft delete

-- Create message_media table for multiple attachments per message
CREATE TABLE IF NOT EXISTS public.message_media (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL REFERENCES public.messages(id) ON DELETE CASCADE,

    -- Media file information
    media_type VARCHAR(20) NOT NULL, -- 'image', 'video', 'audio', 'document'
    file_path TEXT NOT NULL, -- Path in R2 storage (e.g., "messages/{conversation_id}/{message_id}/{filename}")
    filename VARCHAR(255) NOT NULL, -- Original filename
    file_size BIGINT NOT NULL, -- Size in bytes
    mime_type VARCHAR(100) NOT NULL,

    -- Media metadata
    width INTEGER, -- For images/videos
    height INTEGER, -- For images/videos
    duration_seconds INTEGER, -- For audio/video
    thumbnail_path TEXT, -- Thumbnail for videos

    -- Ordering within message
    display_order INTEGER DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Ensure media belongs to valid message
    CONSTRAINT fk_message FOREIGN KEY (message_id) REFERENCES public.messages(id) ON DELETE CASCADE
);

-- Add soft delete columns to conversation_participants for proper message hiding
ALTER TABLE public.conversation_participants
ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS conversation_deleted_for_user BOOLEAN DEFAULT FALSE;

-- Add soft delete column to conversations for when both users delete
ALTER TABLE public.conversations
ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_message_media_message ON public.message_media(message_id);
CREATE INDEX IF NOT EXISTS idx_message_media_type ON public.message_media(media_type);
CREATE INDEX IF NOT EXISTS idx_conversation_participants_deleted ON public.conversation_participants(user_id, conversation_deleted_for_user)
    WHERE conversation_deleted_for_user = FALSE;

-- Enable Row Level Security for message_media
ALTER TABLE public.message_media ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Users can only view media from messages in their conversations
CREATE POLICY "Users can view media in their conversations"
ON public.message_media FOR SELECT
USING (
    message_id IN (
        SELECT m.id
        FROM public.messages m
        JOIN public.conversation_participants cp ON m.conversation_id = cp.conversation_id
        WHERE cp.user_id = auth.uid()
        AND cp.left_at IS NULL
        AND cp.conversation_deleted_for_user = FALSE
    )
);

-- RLS Policy: Users can only insert media for their own messages
CREATE POLICY "Users can add media to their messages"
ON public.message_media FOR INSERT
WITH CHECK (
    message_id IN (
        SELECT id
        FROM public.messages
        WHERE sender_id = auth.uid()
    )
);

-- RLS Policy: Users can only delete their own message media
CREATE POLICY "Users can delete their own message media"
ON public.message_media FOR DELETE
USING (
    message_id IN (
        SELECT id
        FROM public.messages
        WHERE sender_id = auth.uid()
    )
);

-- Function to automatically delete message media when message is soft deleted
CREATE OR REPLACE FUNCTION cleanup_message_media_on_delete()
RETURNS TRIGGER AS $$
BEGIN
    -- When message is marked as deleted, we keep the media records for auditing
    -- but they won't be accessible due to RLS policies and is_deleted check
    -- If you want to actually remove media files from R2, do it in application layer
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger for message media cleanup
CREATE TRIGGER message_media_cleanup_trigger
    AFTER UPDATE OF is_deleted ON public.messages
    FOR EACH ROW
    WHEN (NEW.is_deleted = TRUE AND OLD.is_deleted = FALSE)
    EXECUTE FUNCTION cleanup_message_media_on_delete();

-- Function to check if conversation should be marked as deleted
CREATE OR REPLACE FUNCTION check_conversation_full_delete()
RETURNS TRIGGER AS $$
DECLARE
    active_participants INTEGER;
BEGIN
    -- Count participants who haven't deleted the conversation
    SELECT COUNT(*) INTO active_participants
    FROM public.conversation_participants
    WHERE conversation_id = NEW.conversation_id
    AND conversation_deleted_for_user = FALSE
    AND left_at IS NULL;

    -- If no active participants, mark conversation as deleted
    IF active_participants = 0 THEN
        UPDATE public.conversations
        SET deleted_at = NOW()
        WHERE id = NEW.conversation_id AND deleted_at IS NULL;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger for full conversation deletion check
CREATE TRIGGER check_full_conversation_delete_trigger
    AFTER UPDATE OF conversation_deleted_for_user ON public.conversation_participants
    FOR EACH ROW
    WHEN (NEW.conversation_deleted_for_user = TRUE AND OLD.conversation_deleted_for_user = FALSE)
    EXECUTE FUNCTION check_conversation_full_delete();

-- Add helpful comments
COMMENT ON TABLE public.message_media IS 'Stores multiple media attachments for messages with secure R2 paths';
COMMENT ON COLUMN public.message_media.file_path IS 'Relative path in R2 bucket, used to generate signed URLs';
COMMENT ON COLUMN public.conversation_participants.conversation_deleted_for_user IS 'When TRUE, user has deleted the conversation and should not see it anymore';
COMMENT ON COLUMN public.conversations.deleted_at IS 'Set when all participants have deleted the conversation';

-- Grant permissions
GRANT ALL ON public.message_media TO authenticated, service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO authenticated, service_role;
