-- Migration: Add temporary media storage for upload management
-- This addresses the orphaned files and storage cost considerations

-- Table for tracking temporary uploaded media before post creation
CREATE TABLE IF NOT EXISTS public.temp_media_uploads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    original_filename VARCHAR(500) NOT NULL,
    file_url TEXT NOT NULL,
    thumbnail_url TEXT,
    file_type VARCHAR(50) NOT NULL, -- image, video, audio
    file_size BIGINT NOT NULL, -- bytes
    mime_type VARCHAR(100) NOT NULL,
    width INTEGER,
    height INTEGER,
    duration INTEGER, -- seconds for audio/video
    storage_path TEXT NOT NULL, -- for cleanup
    is_used BOOLEAN DEFAULT FALSE, -- marked true when used in a post
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours'),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT valid_file_type CHECK (file_type IN ('image', 'video', 'audio')),
    CONSTRAINT positive_file_size CHECK (file_size > 0)
);

-- Index for cleanup jobs
CREATE INDEX IF NOT EXISTS idx_temp_media_expires_at ON public.temp_media_uploads(expires_at);
CREATE INDEX IF NOT EXISTS idx_temp_media_unused ON public.temp_media_uploads(is_used, expires_at);
CREATE INDEX IF NOT EXISTS idx_temp_media_user_id ON public.temp_media_uploads(user_id);

-- Enable RLS
ALTER TABLE public.temp_media_uploads ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Users can only see their own temporary uploads
CREATE POLICY "Users can manage their own temp media" 
ON public.temp_media_uploads 
FOR ALL 
USING (auth.uid() = user_id)
WITH CHECK (auth.uid() = user_id);

-- Function to mark temp media as used (called when creating posts)
CREATE OR REPLACE FUNCTION mark_temp_media_as_used(media_urls TEXT[])
RETURNS VOID AS $$
BEGIN
    UPDATE public.temp_media_uploads 
    SET is_used = TRUE, updated_at = NOW()
    WHERE file_url = ANY(media_urls)
    AND user_id = auth.uid()
    AND is_used = FALSE;
END;
$$ LANGUAGE plpgsql SECURITY INVOKER;

-- Function to generate secure file paths (user-scoped)
CREATE OR REPLACE FUNCTION generate_secure_media_path(
    user_id UUID, 
    filename TEXT, 
    file_type TEXT
)
RETURNS TEXT AS $$
DECLARE
    file_extension TEXT;
    unique_filename TEXT;
    secure_path TEXT;
BEGIN
    -- Extract file extension
    file_extension := lower(substring(filename from '\.([^.]+)$'));
    
    -- Generate unique filename
    unique_filename := gen_random_uuid()::TEXT || '.' || file_extension;
    
    -- Create user-scoped path: media/{user_id}/{year}/{month}/{filename}
    secure_path := 'media/' || 
                   user_id::TEXT || '/' ||
                   EXTRACT(YEAR FROM NOW())::TEXT || '/' ||
                   LPAD(EXTRACT(MONTH FROM NOW())::TEXT, 2, '0') || '/' ||
                   unique_filename;
    
    RETURN secure_path;
END;
$$ LANGUAGE plpgsql SECURITY INVOKER;

-- Grant permissions
GRANT ALL ON TABLE public.temp_media_uploads TO authenticated;
GRANT EXECUTE ON FUNCTION mark_temp_media_as_used(TEXT[]) TO authenticated;
GRANT EXECUTE ON FUNCTION generate_secure_media_path(UUID, TEXT, TEXT) TO authenticated;

-- Add comment to document the storage strategy
COMMENT ON TABLE public.temp_media_uploads IS
'Temporary storage for uploaded media files before post creation.
Files are marked as used when included in a post.
Uses Cloudflare R2 for actual file storage.';