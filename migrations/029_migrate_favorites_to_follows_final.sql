-- Migration: Migrate user_favorite_podcasts to user_podcast_follows and drop favorites table
-- Date: 2024
-- Description: Consolidate favorites and follows into single user_podcast_follows table

BEGIN;

-- Step 0: Check if user_favorite_podcasts table exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_name = 'user_favorite_podcasts' 
        AND table_schema = 'public'
    ) THEN
        RAISE NOTICE 'Table user_favorite_podcasts does not exist. Migration not needed.';
        RETURN;
    END IF;
    
    RAISE NOTICE 'Found user_favorite_podcasts table. Proceeding with migration...';
END $$;

-- Step 1: Check column types and display them
DO $$
DECLARE
    favorites_user_id_type text;
    favorites_podcast_id_type text;
    follows_user_id_type text;
    follows_podcast_id_type text;
BEGIN
    -- Get column types for user_favorite_podcasts
    SELECT data_type INTO favorites_user_id_type
    FROM information_schema.columns 
    WHERE table_name = 'user_favorite_podcasts' 
    AND column_name = 'user_id' 
    AND table_schema = 'public';
    
    SELECT data_type INTO favorites_podcast_id_type
    FROM information_schema.columns 
    WHERE table_name = 'user_favorite_podcasts' 
    AND column_name = 'podcast_id' 
    AND table_schema = 'public';
    
    -- Get column types for user_podcast_follows
    SELECT data_type INTO follows_user_id_type
    FROM information_schema.columns 
    WHERE table_name = 'user_podcast_follows' 
    AND column_name = 'user_id' 
    AND table_schema = 'public';
    
    SELECT data_type INTO follows_podcast_id_type
    FROM information_schema.columns 
    WHERE table_name = 'user_podcast_follows' 
    AND column_name = 'podcast_id' 
    AND table_schema = 'public';
    
    RAISE NOTICE 'Column types:';
    RAISE NOTICE '  user_favorite_podcasts.user_id: %', favorites_user_id_type;
    RAISE NOTICE '  user_favorite_podcasts.podcast_id: %', favorites_podcast_id_type;
    RAISE NOTICE '  user_podcast_follows.user_id: %', follows_user_id_type;
    RAISE NOTICE '  user_podcast_follows.podcast_id: %', follows_podcast_id_type;
END $$;

-- Step 2: Migrate data with proper type casting
DO $$
DECLARE
    insert_count INTEGER := 0;
    error_count INTEGER := 0;
    rec RECORD;
BEGIN
    RAISE NOTICE 'Starting data migration with type conversion...';
    
    -- Insert records one by one with error handling
    FOR rec IN 
        SELECT DISTINCT user_id, podcast_id, created_at 
        FROM public.user_favorite_podcasts 
        WHERE user_id IS NOT NULL AND podcast_id IS NOT NULL
    LOOP
        BEGIN
            -- Try to insert with type conversion
            INSERT INTO public.user_podcast_follows (user_id, podcast_id, followed_at, notification_enabled)
            SELECT 
                rec.user_id::uuid,
                rec.podcast_id::uuid,
                COALESCE(rec.created_at, NOW()),
                true
            WHERE NOT EXISTS (
                SELECT 1 FROM public.user_podcast_follows 
                WHERE user_id = rec.user_id::uuid 
                AND podcast_id = rec.podcast_id::uuid
            );
            
            GET DIAGNOSTICS insert_count = ROW_COUNT;
            IF insert_count > 0 THEN
                RAISE NOTICE 'Migrated: user_id=%, podcast_id=%', rec.user_id, rec.podcast_id;
            END IF;
            
        EXCEPTION 
            WHEN OTHERS THEN
                error_count := error_count + 1;
                RAISE NOTICE 'Failed to migrate record (user_id=%, podcast_id=%): %', rec.user_id, rec.podcast_id, SQLERRM;
        END;
    END LOOP;
    
    RAISE NOTICE 'Migration completed with % errors', error_count;
END $$;

-- Step 3: Display migration statistics
DO $$
DECLARE
    favorites_count INTEGER;
    follows_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO favorites_count FROM public.user_favorite_podcasts;
    SELECT COUNT(*) INTO follows_count FROM public.user_podcast_follows;
    
    RAISE NOTICE 'Migration statistics:';
    RAISE NOTICE '  - Original favorites records: %', favorites_count;
    RAISE NOTICE '  - Total follows records after migration: %', follows_count;
END $$;

-- Step 4: Drop foreign key constraints if they exist
DO $$
DECLARE
    constraint_rec RECORD;
BEGIN
    FOR constraint_rec IN 
        SELECT constraint_name 
        FROM information_schema.table_constraints 
        WHERE table_name = 'user_favorite_podcasts' 
        AND table_schema = 'public'
        AND constraint_type = 'FOREIGN KEY'
    LOOP
        EXECUTE 'ALTER TABLE public.user_favorite_podcasts DROP CONSTRAINT ' || constraint_rec.constraint_name;
        RAISE NOTICE 'Dropped constraint: %', constraint_rec.constraint_name;
    END LOOP;
END $$;

-- Step 5: Drop the table
DO $$
BEGIN
    DROP TABLE IF EXISTS public.user_favorite_podcasts CASCADE;
    RAISE NOTICE 'Dropped table: user_favorite_podcasts';
END $$;

-- Step 6: Add comment and setup RLS
DO $$
BEGIN
    -- Add comment
    COMMENT ON TABLE public.user_podcast_follows IS 
    'User podcast follows - consolidated table that replaced user_favorite_podcasts. Migrated on 2024 to eliminate duplicate favorites/follows functionality.';
    
    -- Enable RLS
    ALTER TABLE public.user_podcast_follows ENABLE ROW LEVEL SECURITY;
    
    -- Create policy if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies 
        WHERE tablename = 'user_podcast_follows' 
        AND policyname = 'Users can manage their own follows'
    ) THEN
        CREATE POLICY "Users can manage their own follows" 
        ON public.user_podcast_follows 
        FOR ALL 
        USING (auth.uid() = user_id);
        RAISE NOTICE 'Created RLS policy: Users can manage their own follows';
    ELSE
        RAISE NOTICE 'RLS policy already exists: Users can manage their own follows';
    END IF;
    
    RAISE NOTICE 'Migration completed successfully!';
    RAISE NOTICE 'Verify with: SELECT COUNT(*) FROM public.user_podcast_follows;';
END $$;

COMMIT;