-- Migration 042: Fix sync_user_data_to_post to use user_profiles table
-- The function was only looking at auth.users.raw_user_meta_data
-- but avatar_url and bio are actually stored in user_profiles table

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

    -- Get user metadata (avatar, bio) from user_profiles table first
    -- Fallback to auth.users.raw_user_meta_data if not found
    SELECT
        avatar_url,
        bio
    INTO v_avatar_url, v_bio
    FROM public.user_profiles
    WHERE user_id = p_user_id;

    -- If not found in user_profiles, try auth.users (fallback)
    IF v_avatar_url IS NULL OR v_bio IS NULL THEN
        SELECT
            COALESCE(v_avatar_url, (raw_user_meta_data->>'avatar_url')::TEXT),
            COALESCE(v_bio, (raw_user_meta_data->>'bio')::TEXT)
        INTO v_avatar_url, v_bio
        FROM auth.users
        WHERE id = p_user_id;
    END IF;

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

COMMENT ON FUNCTION sync_user_data_to_post(UUID, UUID) IS
'Syncs user data from user_profiles (primary) and auth.users (fallback) to posts table.
Used by trigger on post insert and for manual backfill operations.';
