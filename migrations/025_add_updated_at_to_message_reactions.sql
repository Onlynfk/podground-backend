-- Migration: Add updated_at column to message_reactions table
-- This fixes the error: record "new" has no field "updated_at"

-- Add updated_at column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'message_reactions'
        AND column_name = 'updated_at'
    ) THEN
        ALTER TABLE message_reactions
        ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();

        -- Update existing rows to have updated_at = created_at
        UPDATE message_reactions
        SET updated_at = created_at
        WHERE updated_at IS NULL;
    END IF;
END $$;

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
