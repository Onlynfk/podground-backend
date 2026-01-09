-- Delete duplicate podcast categories that have no genre mapping
-- This script identifies categories with duplicate display names
-- and deletes the ones that are not mapped to any genre in category_genre table

-- Step 1: Identify and delete duplicate categories (by display_name) that have no genre mapping
-- Keep the category that either has a genre mapping or was created first
WITH duplicate_categories AS (
    -- Find categories where the display_name appears more than once
    SELECT
        pc.id,
        pc.name,
        pc.display_name,
        pc.created_at,
        CASE WHEN cg.category_id IS NOT NULL THEN 1 ELSE 0 END as has_genre_mapping,
        ROW_NUMBER() OVER (
            PARTITION BY LOWER(TRIM(pc.display_name))
            ORDER BY
                CASE WHEN cg.category_id IS NOT NULL THEN 0 ELSE 1 END, -- Prioritize ones with genre mapping
                pc.created_at ASC -- Then prioritize older entries
        ) as row_num
    FROM public.podcast_categories pc
    LEFT JOIN public.category_genre cg ON pc.id = cg.category_id
    WHERE LOWER(TRIM(pc.display_name)) IN (
        -- Find display names that appear more than once
        SELECT LOWER(TRIM(display_name))
        FROM public.podcast_categories
        GROUP BY LOWER(TRIM(display_name))
        HAVING COUNT(*) > 1
    )
),
categories_to_delete AS (
    -- Select duplicates to delete (row_num > 1 means it's a duplicate)
    -- Only delete if they have no genre mapping
    SELECT id, name, display_name
    FROM duplicate_categories
    WHERE row_num > 1 AND has_genre_mapping = 0
)
DELETE FROM public.podcast_categories
WHERE id IN (SELECT id FROM categories_to_delete)
RETURNING id, name, display_name;

-- Step 2: Clean up any orphaned genre mappings (shouldn't exist due to CASCADE, but just in case)
DELETE FROM public.category_genre cg
WHERE NOT EXISTS (
    SELECT 1 FROM public.podcast_categories pc WHERE pc.id = cg.category_id
);

-- Step 3: Show remaining categories and their genre mapping status
SELECT
    pc.id,
    pc.name,
    pc.display_name,
    COUNT(cg.id) as genre_mappings_count,
    STRING_AGG(cg.genre_id::text, ', ' ORDER BY cg.genre_id) as genre_ids
FROM public.podcast_categories pc
LEFT JOIN public.category_genre cg ON pc.id = cg.category_id
GROUP BY pc.id, pc.name, pc.display_name
ORDER BY pc.name;
