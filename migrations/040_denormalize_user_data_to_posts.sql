-- Migration: Denormalize user data into posts table for performance
-- This eliminates N+1 queries for user data in feed queries (~400-800ms improvement)

-- Add denormalized user columns to posts table
ALTER TABLE public.posts
ADD COLUMN IF NOT EXISTS author_name VARCHAR(255),
ADD COLUMN IF NOT EXISTS author_avatar_url TEXT,
ADD COLUMN IF NOT EXISTS author_podcast_name VARCHAR(500),
ADD COLUMN IF NOT EXISTS author_podcast_id UUID,
ADD COLUMN IF NOT EXISTS author_bio TEXT;

-- Create index on author_name for search functionality
CREATE INDEX IF NOT EXISTS idx_posts_author_name ON public.posts(author_name);

-- Function to get user's name from multiple sources
CREATE OR REPLACE FUNCTION get_user_name(p_user_id UUID)
RETURNS VARCHAR(255) AS $$
DECLARE
    v_name VARCHAR(255);
BEGIN
    -- Try user_signup_tracking first
    SELECT name INTO v_name
    FROM public.user_signup_tracking
    WHERE user_id = p_user_id
    LIMIT 1;

    IF v_name IS NOT NULL AND v_name != '' THEN
        RETURN v_name;
    END IF;

    -- Try auth.users metadata
    SELECT
        COALESCE(
            (raw_user_meta_data->>'name')::TEXT,
            (raw_user_meta_data->>'full_name')::TEXT,
            (raw_user_meta_data->>'first_name')::TEXT,
            split_part(email, '@', 1)
        )
    INTO v_name
    FROM auth.users
    WHERE id = p_user_id;

    RETURN COALESCE(v_name, 'Unknown User');
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to get user's podcast info
CREATE OR REPLACE FUNCTION get_user_podcast_info(p_user_id UUID)
RETURNS TABLE(podcast_id UUID, podcast_name VARCHAR(500)) AS $$
BEGIN
    RETURN QUERY
    SELECT p.id, p.title
    FROM public.podcast_claims pc
    JOIN public.podcasts p ON p.listennotes_id = pc.listennotes_id
    WHERE pc.user_id = p_user_id
      AND pc.is_verified = TRUE
      AND pc.claim_status = 'verified'
    LIMIT 1;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to sync user data to posts
CREATE OR REPLACE FUNCTION sync_user_data_to_post(p_post_id UUID, p_user_id UUID)
RETURNS VOID AS $$
DECLARE
    v_name VARCHAR(255);
    v_avatar_url TEXT;
    v_bio TEXT;
    v_podcast_id UUID;
    v_podcast_name VARCHAR(500);
BEGIN
    -- Get user name
    v_name := get_user_name(p_user_id);

    -- Get user metadata (avatar, bio)
    SELECT
        (raw_user_meta_data->>'avatar_url')::TEXT,
        (raw_user_meta_data->>'bio')::TEXT
    INTO v_avatar_url, v_bio
    FROM auth.users
    WHERE id = p_user_id;

    -- Get podcast info
    SELECT podcast_id, podcast_name
    INTO v_podcast_id, v_podcast_name
    FROM get_user_podcast_info(p_user_id);

    -- Update post with denormalized data
    UPDATE public.posts
    SET
        author_name = v_name,
        author_avatar_url = v_avatar_url,
        author_podcast_name = v_podcast_name,
        author_podcast_id = v_podcast_id,
        author_bio = v_bio,
        updated_at = NOW()
    WHERE id = p_post_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger function to sync user data on post insert
CREATE OR REPLACE FUNCTION trigger_sync_user_data_on_post_insert()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM sync_user_data_to_post(NEW.id, NEW.user_id);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Create trigger for new posts
DROP TRIGGER IF EXISTS sync_user_data_on_post_insert ON public.posts;
CREATE TRIGGER sync_user_data_on_post_insert
    AFTER INSERT ON public.posts
    FOR EACH ROW
    EXECUTE FUNCTION trigger_sync_user_data_on_post_insert();

-- Backfill existing posts with user data (run once during migration)
-- This is done in batches to avoid locking the table for too long
DO $$
DECLARE
    v_batch_size INT := 100;
    v_offset INT := 0;
    v_post RECORD;
BEGIN
    LOOP
        -- Process posts in batches
        FOR v_post IN
            SELECT id, user_id
            FROM public.posts
            WHERE deleted_at IS NULL
              AND author_name IS NULL  -- Only update posts without denormalized data
            ORDER BY created_at DESC
            LIMIT v_batch_size
            OFFSET v_offset
        LOOP
            PERFORM sync_user_data_to_post(v_post.id, v_post.user_id);
        END LOOP;

        -- Check if we processed any rows
        IF NOT FOUND THEN
            EXIT;
        END IF;

        v_offset := v_offset + v_batch_size;
    END LOOP;
END $$;

-- Grant necessary permissions
GRANT EXECUTE ON FUNCTION get_user_name(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION get_user_podcast_info(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION sync_user_data_to_post(UUID, UUID) TO authenticated;

-- Add comment to document the denormalization strategy
COMMENT ON COLUMN public.posts.author_name IS
'Denormalized user name from auth.users or user_signup_tracking.
Kept in sync via trigger on post insert.
Eliminates N+1 queries for user data in feed queries.';

COMMENT ON COLUMN public.posts.author_podcast_name IS
'Denormalized podcast name from podcast_claims and podcasts tables.
Kept in sync via trigger on post insert.';

-- Note: To manually refresh denormalized data for a specific post:
-- SELECT sync_user_data_to_post('post_id', 'user_id');

-- Note: To manually refresh all posts for a specific user (e.g., when they update their profile):
-- UPDATE public.posts
-- SET author_name = get_user_name(user_id),
--     author_avatar_url = (SELECT raw_user_meta_data->>'avatar_url' FROM auth.users WHERE id = user_id),
--     author_bio = (SELECT raw_user_meta_data->>'bio' FROM auth.users WHERE id = user_id)
-- WHERE user_id = 'target_user_id';
