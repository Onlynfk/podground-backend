-- Add genre mappings for categories that don't have them yet
-- This script uses category names to look up IDs, so it works on both dev and prod

-- Insert genre mappings for unmapped categories
-- Using subqueries to find category_id by name so this works across environments
INSERT INTO public.category_genre (genre_id, category_id)
SELECT genre_id, category_id FROM (
    VALUES
        -- Books -> Genre 104 (Books)
        (104, (SELECT id FROM public.podcast_categories WHERE name = 'books' LIMIT 1)),

        -- Careers -> Genre 94 (Careers)
        (94, (SELECT id FROM public.podcast_categories WHERE name = 'careers' LIMIT 1)),

        -- Christianity -> Genre 75 (Christianity)
        (75, (SELECT id FROM public.podcast_categories WHERE name = 'christianity' LIMIT 1)),

        -- Documentary -> Genre 244 (Documentary)
        (244, (SELECT id FROM public.podcast_categories WHERE name = 'documentary' LIMIT 1)),

        -- Entrepreneurship -> Genre 171 (Entrepreneurship)
        (171, (SELECT id FROM public.podcast_categories WHERE name = 'entrepreneurship' LIMIT 1)),

        -- Investing -> Genre 98 (Investing)
        (98, (SELECT id FROM public.podcast_categories WHERE name = 'investing' LIMIT 1)),

        -- Language Learning -> Genre 116 (Language Learning)
        (116, (SELECT id FROM public.podcast_categories WHERE name = 'language_learning' LIMIT 1)),

        -- Learn Something New -> Genre 111 (Education) - closest match
        (111, (SELECT id FROM public.podcast_categories WHERE name = 'learn-something-new' LIMIT 1)),

        -- Management -> Genre 97 (Management)
        (97, (SELECT id FROM public.podcast_categories WHERE name = 'management' LIMIT 1)),

        -- Marketing -> Genre 173 (Marketing)
        (173, (SELECT id FROM public.podcast_categories WHERE name = 'marketing' LIMIT 1)),

        -- Mental Health -> Genre 191 (Mental Health)
        (191, (SELECT id FROM public.podcast_categories WHERE name = 'mental_health' LIMIT 1)),

        -- Parenting -> Genre 145 (Parenting)
        (145, (SELECT id FROM public.podcast_categories WHERE name = 'parenting' LIMIT 1)),

        -- Personal Journals -> Genre 124 (Personal Journals)
        (124, (SELECT id FROM public.podcast_categories WHERE name = 'personal_journals' LIMIT 1)),

        -- Relationships -> Genre 245 (Relationships)
        (245, (SELECT id FROM public.podcast_categories WHERE name = 'relationships' LIMIT 1)),

        -- Self-Improvement -> Genre 181 (Self-Improvement)
        (181, (SELECT id FROM public.podcast_categories WHERE name = 'self_improvement' LIMIT 1)),

        -- Sleep -> Genre 88 (Health & Fitness) - closest match as there's no specific sleep genre
        (88, (SELECT id FROM public.podcast_categories WHERE name = 'sleep' LIMIT 1))

        -- Note: 'series' category is intentionally not mapped as it appears to be a meta-category
        -- rather than a content category, and has no clear genre equivalent in ListenNotes
) AS mappings(genre_id, category_id)
WHERE category_id IS NOT NULL  -- Only insert if the category exists
ON CONFLICT (genre_id) DO NOTHING;  -- Skip if genre_id already mapped

-- Show the results
SELECT
    pc.name as category_name,
    pc.display_name,
    cg.genre_id,
    COUNT(cg.id) OVER (PARTITION BY pc.id) as mappings_count
FROM public.podcast_categories pc
LEFT JOIN public.category_genre cg ON pc.id = cg.category_id
WHERE pc.name IN (
    'books', 'careers', 'christianity', 'documentary', 'entrepreneurship',
    'investing', 'language_learning', 'learn-something-new', 'management',
    'marketing', 'mental_health', 'parenting', 'personal_journals',
    'relationships', 'self_improvement', 'sleep', 'series'
)
ORDER BY pc.name;
