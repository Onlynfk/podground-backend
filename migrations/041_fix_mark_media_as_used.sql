-- Migration: Fix mark_temp_media_as_used to work with service account
-- The original function required auth.uid() which doesn't work when called from backend
-- This caused post media to never be marked as used, making them vulnerable to cleanup

-- Drop the old function
DROP FUNCTION IF EXISTS mark_temp_media_as_used(TEXT[]);

-- Create new version that accepts user_id as parameter
CREATE OR REPLACE FUNCTION mark_temp_media_as_used(media_urls TEXT[], p_user_id UUID)
RETURNS INTEGER AS $$
DECLARE
    v_updated_count INTEGER;
BEGIN
    -- Update temp media records to mark them as used
    UPDATE public.temp_media_uploads
    SET is_used = TRUE, updated_at = NOW()
    WHERE file_url = ANY(media_urls)
    AND user_id = p_user_id
    AND is_used = FALSE;

    GET DIAGNOSTICS v_updated_count = ROW_COUNT;

    RETURN v_updated_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Grant permissions
GRANT EXECUTE ON FUNCTION mark_temp_media_as_used(TEXT[], UUID) TO authenticated;

-- Add comment
COMMENT ON FUNCTION mark_temp_media_as_used(TEXT[], UUID) IS
'Marks temporary media uploads as used when they are attached to a post.
Accepts user_id as parameter to work with service account calls.
Returns the number of records updated.';
