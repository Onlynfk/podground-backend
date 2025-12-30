-- Migration: Add auto-follow podcasts for all users who have completed onboarding
-- Date: 2024
-- Description: Insert auto-favorite podcasts into user_podcast_follows for all completed onboarding users

BEGIN;

-- Step 1: Define the auto-favorite podcast IDs (from environment variables)
-- Note: These should match the AUTO_FAVORITE_PODCAST_*_ID values from your environment
DO $$
DECLARE
    auto_podcast_1_id text := '887fc174645b4bfd98b181fed10c8e46';  -- AUTO_FAVORITE_PODCAST_1_ID
    auto_podcast_2_id text := 'abdcce3f264e48f496bac5730fb83e93';  -- AUTO_FAVORITE_PODCAST_2_ID
    completed_user RECORD;
    insert_count INTEGER := 0;
    error_count INTEGER := 0;
    valid_podcast_1_id uuid := NULL;
    valid_podcast_2_id uuid := NULL;
    temp_result RECORD;
BEGIN
    RAISE NOTICE 'Starting auto-follow migration for completed onboarding users...';
    RAISE NOTICE 'Auto-podcast IDs: % and %', auto_podcast_1_id, auto_podcast_2_id;
    
    -- Step 2: Validate and get actual podcast IDs from database
    -- Check podcasts table first (by id)
    BEGIN
        SELECT id INTO valid_podcast_1_id FROM public.podcasts WHERE id = auto_podcast_1_id::uuid;
    EXCEPTION WHEN OTHERS THEN
        valid_podcast_1_id := NULL;
    END;
    
    -- If not found by id, try by listennotes_id
    IF valid_podcast_1_id IS NULL THEN
        BEGIN
            SELECT id INTO valid_podcast_1_id FROM public.podcasts WHERE listennotes_id = auto_podcast_1_id;
        EXCEPTION WHEN OTHERS THEN
            valid_podcast_1_id := NULL;
        END;
    END IF;
    
    -- If still not found, try featured_podcasts table
    IF valid_podcast_1_id IS NULL THEN
        BEGIN
            SELECT id INTO valid_podcast_1_id FROM public.featured_podcasts WHERE podcast_id = auto_podcast_1_id;
        EXCEPTION WHEN OTHERS THEN
            valid_podcast_1_id := NULL;
        END;
    END IF;
    
    -- Same process for podcast 2
    BEGIN
        SELECT id INTO valid_podcast_2_id FROM public.podcasts WHERE id = auto_podcast_2_id::uuid;
    EXCEPTION WHEN OTHERS THEN
        valid_podcast_2_id := NULL;
    END;
    
    IF valid_podcast_2_id IS NULL THEN
        BEGIN
            SELECT id INTO valid_podcast_2_id FROM public.podcasts WHERE listennotes_id = auto_podcast_2_id;
        EXCEPTION WHEN OTHERS THEN
            valid_podcast_2_id := NULL;
        END;
    END IF;
    
    IF valid_podcast_2_id IS NULL THEN
        BEGIN
            SELECT id INTO valid_podcast_2_id FROM public.featured_podcasts WHERE podcast_id = auto_podcast_2_id;
        EXCEPTION WHEN OTHERS THEN
            valid_podcast_2_id := NULL;
        END;
    END IF;
    
    RAISE NOTICE 'Valid podcast IDs found: % and %', valid_podcast_1_id, valid_podcast_2_id;
    
    -- Step 3: Get all users who have completed onboarding
    FOR completed_user IN 
        SELECT DISTINCT id as user_id 
        FROM public.user_onboarding 
        WHERE is_completed = true 
        AND step_5_completed = true
        AND id IS NOT NULL
    LOOP
        RAISE NOTICE 'Processing user: %', completed_user.user_id;
        
        -- Step 4: Insert auto-follow for podcast 1 if valid and not already following
        IF valid_podcast_1_id IS NOT NULL THEN
            BEGIN
                INSERT INTO public.user_podcast_follows (user_id, podcast_id, followed_at, notification_enabled)
                SELECT 
                    completed_user.user_id,
                    valid_podcast_1_id,
                    NOW(),
                    true
                WHERE NOT EXISTS (
                    SELECT 1 FROM public.user_podcast_follows 
                    WHERE user_id = completed_user.user_id 
                    AND podcast_id = valid_podcast_1_id
                );
                
                GET DIAGNOSTICS insert_count = ROW_COUNT;
                IF insert_count > 0 THEN
                    RAISE NOTICE '  ✓ Added auto-follow for podcast 1 (user: %)', completed_user.user_id;
                ELSE
                    RAISE NOTICE '  - User % already follows podcast 1', completed_user.user_id;
                END IF;
                
            EXCEPTION WHEN OTHERS THEN
                error_count := error_count + 1;
                RAISE NOTICE '  ✗ Failed to add podcast 1 for user %: %', completed_user.user_id, SQLERRM;
            END;
        ELSE
            RAISE NOTICE '  - Skipping podcast 1 (invalid ID)';
        END IF;
        
        -- Step 5: Insert auto-follow for podcast 2 if valid and not already following
        IF valid_podcast_2_id IS NOT NULL THEN
            BEGIN
                INSERT INTO public.user_podcast_follows (user_id, podcast_id, followed_at, notification_enabled)
                SELECT 
                    completed_user.user_id,
                    valid_podcast_2_id,
                    NOW(),
                    true
                WHERE NOT EXISTS (
                    SELECT 1 FROM public.user_podcast_follows 
                    WHERE user_id = completed_user.user_id 
                    AND podcast_id = valid_podcast_2_id
                );
                
                GET DIAGNOSTICS insert_count = ROW_COUNT;
                IF insert_count > 0 THEN
                    RAISE NOTICE '  ✓ Added auto-follow for podcast 2 (user: %)', completed_user.user_id;
                ELSE
                    RAISE NOTICE '  - User % already follows podcast 2', completed_user.user_id;
                END IF;
                
            EXCEPTION WHEN OTHERS THEN
                error_count := error_count + 1;
                RAISE NOTICE '  ✗ Failed to add podcast 2 for user %: %', completed_user.user_id, SQLERRM;
            END;
        ELSE
            RAISE NOTICE '  - Skipping podcast 2 (invalid ID)';
        END IF;
    END LOOP;
    
    -- Step 6: Final statistics
    DECLARE
        total_completed_users INTEGER;
        total_follows INTEGER;
        follows_for_podcast_1 INTEGER;
        follows_for_podcast_2 INTEGER;
    BEGIN
        SELECT COUNT(*) INTO total_completed_users 
        FROM public.user_onboarding 
        WHERE is_completed = true AND step_5_completed = true;
        
        SELECT COUNT(*) INTO total_follows 
        FROM public.user_podcast_follows;
        
        SELECT COUNT(*) INTO follows_for_podcast_1 
        FROM public.user_podcast_follows 
        WHERE podcast_id = valid_podcast_1_id;
        
        SELECT COUNT(*) INTO follows_for_podcast_2 
        FROM public.user_podcast_follows 
        WHERE podcast_id = valid_podcast_2_id;
        
        RAISE NOTICE 'Migration completed!';
        RAISE NOTICE 'Statistics:';
        RAISE NOTICE '  - Total completed onboarding users: %', total_completed_users;
        RAISE NOTICE '  - Total follows in system: %', total_follows;
        RAISE NOTICE '  - Users following auto-podcast 1: %', follows_for_podcast_1;
        RAISE NOTICE '  - Users following auto-podcast 2: %', follows_for_podcast_2;
        RAISE NOTICE '  - Errors encountered: %', error_count;
    END;
END $$;

COMMIT;

-- Verification queries to run manually:
-- SELECT COUNT(*) as total_completed_users FROM public.user_onboarding WHERE is_completed = true AND step_5_completed = true;
-- SELECT COUNT(*) as total_follows FROM public.user_podcast_follows;
-- SELECT podcast_id, COUNT(*) as follow_count FROM public.user_podcast_follows GROUP BY podcast_id ORDER BY follow_count DESC;