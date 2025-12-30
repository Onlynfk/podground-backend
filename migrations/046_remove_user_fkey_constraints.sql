-- Remove user_id foreign key constraints from listening tables
-- These tables should not have FK constraints to any users table
-- since Supabase Auth manages users in auth.users

-- Drop foreign key constraint from user_listening_progress if it exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_name = 'user_listening_progress'
        AND constraint_name = 'user_listening_progress_user_id_fkey'
        AND constraint_type = 'FOREIGN KEY'
    ) THEN
        ALTER TABLE public.user_listening_progress
        DROP CONSTRAINT user_listening_progress_user_id_fkey;
        RAISE NOTICE 'Dropped user_listening_progress_user_id_fkey constraint';
    END IF;
END $$;

-- Drop foreign key constraint from user_episode_saves if it exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_name = 'user_episode_saves'
        AND constraint_name = 'user_episode_saves_user_id_fkey'
        AND constraint_type = 'FOREIGN KEY'
    ) THEN
        ALTER TABLE public.user_episode_saves
        DROP CONSTRAINT user_episode_saves_user_id_fkey;
        RAISE NOTICE 'Dropped user_episode_saves_user_id_fkey constraint';
    END IF;
END $$;

-- Drop foreign key constraint from user_podcast_follows if it exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_name = 'user_podcast_follows'
        AND constraint_name = 'user_podcast_follows_user_id_fkey'
        AND constraint_type = 'FOREIGN KEY'
    ) THEN
        ALTER TABLE public.user_podcast_follows
        DROP CONSTRAINT user_podcast_follows_user_id_fkey;
        RAISE NOTICE 'Dropped user_podcast_follows_user_id_fkey constraint';
    END IF;
END $$;

-- Drop foreign key constraint from user_podcast_ratings if it exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_name = 'user_podcast_ratings'
        AND constraint_name = 'user_podcast_ratings_user_id_fkey'
        AND constraint_type = 'FOREIGN KEY'
    ) THEN
        ALTER TABLE public.user_podcast_ratings
        DROP CONSTRAINT user_podcast_ratings_user_id_fkey;
        RAISE NOTICE 'Dropped user_podcast_ratings_user_id_fkey constraint';
    END IF;
END $$;

-- Note: We're NOT adding new FK constraints because:
-- 1. Supabase Auth users are in auth.users (different schema)
-- 2. PostgREST/Supabase RLS already handles user validation
-- 3. The user_id column is validated at the application level
-- 4. RLS policies ensure users can only access their own data
