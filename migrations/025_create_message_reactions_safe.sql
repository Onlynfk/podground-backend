-- Migration: Create message_reactions table for emoji reactions on messages
-- Description: Allows users to add emoji reactions to messages in conversations

-- Drop existing table if needed (comment out if you want to preserve existing data)
-- DROP TABLE IF EXISTS message_reactions CASCADE;

-- Create message_reactions table
CREATE TABLE IF NOT EXISTS message_reactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    reaction_type VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Add unique constraint if it doesn't exist
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'unique_user_message_reaction'
    ) THEN
        ALTER TABLE message_reactions 
        ADD CONSTRAINT unique_user_message_reaction UNIQUE (message_id, user_id);
    END IF;
END $$;

-- Add check constraint if it doesn't exist
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'valid_reaction_type'
    ) THEN
        ALTER TABLE message_reactions 
        ADD CONSTRAINT valid_reaction_type CHECK (
            reaction_type IN (
                -- Emoji reactions
                '👍', '👎', '❤️', '😂', '😢', '😡', '😮', '🔥', '💯', '🎉',
                '😍', '🤔', '👏', '😅', '😊', '🙏', '💪', '👌', '🤝', '✨',
                -- Text reaction names
                'like', 'love', 'laugh', 'sad', 'angry', 'wow', 'fire', 'hundred', 'party'
            )
        );
    END IF;
END $$;

-- Create indexes if they don't exist
CREATE INDEX IF NOT EXISTS idx_message_reactions_message_id ON message_reactions(message_id);
CREATE INDEX IF NOT EXISTS idx_message_reactions_user_id ON message_reactions(user_id);
CREATE INDEX IF NOT EXISTS idx_message_reactions_type ON message_reactions(reaction_type);
CREATE INDEX IF NOT EXISTS idx_message_reactions_created_at ON message_reactions(created_at DESC);

-- Create or replace updated_at trigger function
CREATE OR REPLACE FUNCTION update_message_reactions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Drop trigger if exists and recreate
DROP TRIGGER IF EXISTS update_message_reactions_updated_at ON message_reactions;

CREATE TRIGGER update_message_reactions_updated_at
    BEFORE UPDATE ON message_reactions
    FOR EACH ROW
    EXECUTE FUNCTION update_message_reactions_updated_at();

-- Enable Row Level Security
ALTER TABLE message_reactions ENABLE ROW LEVEL SECURITY;

-- Drop existing policies if they exist
DROP POLICY IF EXISTS "Users can view message reactions in their conversations" ON message_reactions;
DROP POLICY IF EXISTS "Users can add reactions to messages in their conversations" ON message_reactions;
DROP POLICY IF EXISTS "Users can update their own reactions" ON message_reactions;
DROP POLICY IF EXISTS "Users can delete their own reactions" ON message_reactions;

-- Create RLS Policies

-- Policy: Users can view reactions on messages they have access to
CREATE POLICY "Users can view message reactions in their conversations"
    ON message_reactions
    FOR SELECT
    TO authenticated
    USING (
        EXISTS (
            SELECT 1 
            FROM messages m
            JOIN conversation_participants cp ON cp.conversation_id = m.conversation_id
            WHERE m.id = message_reactions.message_id
            AND cp.user_id = auth.uid()
            AND cp.left_at IS NULL
        )
    );

-- Policy: Users can add reactions to messages in their conversations
CREATE POLICY "Users can add reactions to messages in their conversations"
    ON message_reactions
    FOR INSERT
    TO authenticated
    WITH CHECK (
        auth.uid() = user_id
        AND EXISTS (
            SELECT 1 
            FROM messages m
            JOIN conversation_participants cp ON cp.conversation_id = m.conversation_id
            WHERE m.id = message_reactions.message_id
            AND cp.user_id = auth.uid()
            AND cp.left_at IS NULL
        )
    );

-- Policy: Users can update their own reactions
CREATE POLICY "Users can update their own reactions"
    ON message_reactions
    FOR UPDATE
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Policy: Users can delete their own reactions
CREATE POLICY "Users can delete their own reactions"
    ON message_reactions
    FOR DELETE
    TO authenticated
    USING (auth.uid() = user_id);

-- Grant permissions
GRANT ALL ON message_reactions TO authenticated;
GRANT ALL ON message_reactions TO service_role;

-- Create or replace function to get reaction summary for a message
CREATE OR REPLACE FUNCTION get_message_reaction_summary(p_message_id UUID)
RETURNS JSON AS $$
DECLARE
    reaction_summary JSON;
BEGIN
    SELECT json_object_agg(
        reaction_type,
        json_build_object(
            'count', reaction_count,
            'users', user_ids
        )
    )
    INTO reaction_summary
    FROM (
        SELECT 
            reaction_type,
            COUNT(*) as reaction_count,
            json_agg(user_id) as user_ids
        FROM message_reactions
        WHERE message_id = p_message_id
        GROUP BY reaction_type
    ) AS grouped_reactions;
    
    RETURN COALESCE(reaction_summary, '{}'::json);
END;
$$ LANGUAGE plpgsql;

-- Create or replace function to get user's reaction for a message
CREATE OR REPLACE FUNCTION get_user_message_reaction(p_message_id UUID, p_user_id UUID)
RETURNS VARCHAR(50) AS $$
BEGIN
    RETURN (
        SELECT reaction_type
        FROM message_reactions
        WHERE message_id = p_message_id
        AND user_id = p_user_id
        LIMIT 1
    );
END;
$$ LANGUAGE plpgsql;

-- Add comments only if they don't exist
COMMENT ON TABLE message_reactions IS 'Stores emoji reactions to messages in conversations';
COMMENT ON COLUMN message_reactions.reaction_type IS 'The emoji or reaction name (e.g., 👍, ❤️, like, love)';