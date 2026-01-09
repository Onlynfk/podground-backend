-- Fix ALL user_id foreign key constraints to point to auth.users (not public.users)
-- This includes listening tables AND user_connections table
-- This migration safely cleans up orphaned records before adding constraints

-- Fix user_listening_progress
DO $$
BEGIN
    -- Drop existing constraint if it exists
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'user_listening_progress'
        AND constraint_name = 'user_listening_progress_user_id_fkey'
    ) THEN
        ALTER TABLE public.user_listening_progress
        DROP CONSTRAINT user_listening_progress_user_id_fkey;
        RAISE NOTICE 'Dropped old user_listening_progress_user_id_fkey';
    END IF;

    -- Clean up orphaned records (user_ids not in auth.users)
    DELETE FROM public.user_listening_progress
    WHERE user_id NOT IN (SELECT id FROM auth.users);
    RAISE NOTICE 'Cleaned up orphaned user_listening_progress records';

    -- Add correct constraint pointing to auth.users
    ALTER TABLE public.user_listening_progress
    ADD CONSTRAINT user_listening_progress_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

    RAISE NOTICE 'Added correct FK constraint: user_listening_progress -> auth.users';
END $$;

-- Fix user_episode_saves
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'user_episode_saves'
        AND constraint_name = 'user_episode_saves_user_id_fkey'
    ) THEN
        ALTER TABLE public.user_episode_saves
        DROP CONSTRAINT user_episode_saves_user_id_fkey;
        RAISE NOTICE 'Dropped old user_episode_saves_user_id_fkey';
    END IF;

    -- Clean up orphaned records
    DELETE FROM public.user_episode_saves
    WHERE user_id NOT IN (SELECT id FROM auth.users);
    RAISE NOTICE 'Cleaned up orphaned user_episode_saves records';

    ALTER TABLE public.user_episode_saves
    ADD CONSTRAINT user_episode_saves_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

    RAISE NOTICE 'Added correct FK constraint: user_episode_saves -> auth.users';
END $$;

-- Fix user_podcast_follows
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'user_podcast_follows'
        AND constraint_name = 'user_podcast_follows_user_id_fkey'
    ) THEN
        ALTER TABLE public.user_podcast_follows
        DROP CONSTRAINT user_podcast_follows_user_id_fkey;
        RAISE NOTICE 'Dropped old user_podcast_follows_user_id_fkey';
    END IF;

    -- Clean up orphaned records
    DELETE FROM public.user_podcast_follows
    WHERE user_id NOT IN (SELECT id FROM auth.users);
    RAISE NOTICE 'Cleaned up orphaned user_podcast_follows records';

    ALTER TABLE public.user_podcast_follows
    ADD CONSTRAINT user_podcast_follows_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

    RAISE NOTICE 'Added correct FK constraint: user_podcast_follows -> auth.users';
END $$;

-- Fix user_podcast_ratings
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'user_podcast_ratings'
        AND constraint_name = 'user_podcast_ratings_user_id_fkey'
    ) THEN
        ALTER TABLE public.user_podcast_ratings
        DROP CONSTRAINT user_podcast_ratings_user_id_fkey;
        RAISE NOTICE 'Dropped old user_podcast_ratings_user_id_fkey';
    END IF;

    -- Clean up orphaned records
    DELETE FROM public.user_podcast_ratings
    WHERE user_id NOT IN (SELECT id FROM auth.users);
    RAISE NOTICE 'Cleaned up orphaned user_podcast_ratings records';

    ALTER TABLE public.user_podcast_ratings
    ADD CONSTRAINT user_podcast_ratings_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

    RAISE NOTICE 'Added correct FK constraint: user_podcast_ratings -> auth.users';
END $$;

-- Fix user_connections (follower_id)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'user_connections'
        AND constraint_name = 'user_connections_follower_id_fkey'
    ) THEN
        ALTER TABLE public.user_connections
        DROP CONSTRAINT user_connections_follower_id_fkey;
        RAISE NOTICE 'Dropped old user_connections_follower_id_fkey';
    END IF;

    -- Clean up orphaned records (follower_id not in auth.users)
    DELETE FROM public.user_connections
    WHERE follower_id NOT IN (SELECT id FROM auth.users);
    RAISE NOTICE 'Cleaned up orphaned user_connections records (follower_id)';

    ALTER TABLE public.user_connections
    ADD CONSTRAINT user_connections_follower_id_fkey
    FOREIGN KEY (follower_id) REFERENCES auth.users(id) ON DELETE CASCADE;

    RAISE NOTICE 'Added correct FK constraint: user_connections.follower_id -> auth.users';
END $$;

-- Fix user_connections (following_id)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'user_connections'
        AND constraint_name = 'user_connections_following_id_fkey'
    ) THEN
        ALTER TABLE public.user_connections
        DROP CONSTRAINT user_connections_following_id_fkey;
        RAISE NOTICE 'Dropped old user_connections_following_id_fkey';
    END IF;

    -- Clean up orphaned records (following_id not in auth.users)
    DELETE FROM public.user_connections
    WHERE following_id NOT IN (SELECT id FROM auth.users);
    RAISE NOTICE 'Cleaned up orphaned user_connections records (following_id)';

    ALTER TABLE public.user_connections
    ADD CONSTRAINT user_connections_following_id_fkey
    FOREIGN KEY (following_id) REFERENCES auth.users(id) ON DELETE CASCADE;

    RAISE NOTICE 'Added correct FK constraint: user_connections.following_id -> auth.users';
END $$;

-- Note: This migration fixes all user-related FK constraints to point to auth.users
-- Orphaned records (with user_ids not in auth.users) are deleted before adding constraints
-- Supabase Auth manages users in auth.users (different schema from public)
-- RLS policies ensure users can only access their own data
