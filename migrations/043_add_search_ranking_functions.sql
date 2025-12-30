-- Migration 043: Add ranked search functions for podcasts and episodes
-- These functions search ONLY on title/name fields with phrase matching

-- Function to search podcasts with relevance ranking (title only)
CREATE OR REPLACE FUNCTION search_podcasts_ranked(
    search_query TEXT,
    result_limit INTEGER DEFAULT 10,
    result_offset INTEGER DEFAULT 0
)
RETURNS TABLE (
    id UUID,
    listennotes_id VARCHAR(50),
    title VARCHAR(500),
    description TEXT,
    image_url TEXT,
    publisher VARCHAR(255),
    ts_rank_score REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        p.id,
        p.listennotes_id,
        p.title,
        p.description,
        p.image_url,
        p.publisher,
        1.0::REAL AS ts_rank_score
    FROM public.podcasts p
    WHERE LOWER(p.title) LIKE '%' || LOWER(search_query) || '%'
    ORDER BY
        CASE
            WHEN LOWER(p.title) = LOWER(search_query) THEN 1  -- Exact match
            ELSE 2  -- Phrase match
        END
    LIMIT result_limit
    OFFSET result_offset;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION search_podcasts_ranked(TEXT, INTEGER, INTEGER) IS
'Search podcasts by title only (exact and phrase matching).
Returns results ordered by match type (exact first, then phrase matches).';


-- Function to search episodes with relevance ranking (title only)
CREATE OR REPLACE FUNCTION search_episodes_ranked(
    search_query TEXT,
    result_limit INTEGER DEFAULT 10,
    result_offset INTEGER DEFAULT 0
)
RETURNS TABLE (
    id UUID,
    listennotes_id VARCHAR(50),
    title VARCHAR(500),
    description TEXT,
    image_url TEXT,
    podcast_id UUID,
    podcasts JSONB,
    ts_rank_score REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        e.id,
        e.listennotes_id,
        e.title,
        e.description,
        e.image_url,
        e.podcast_id,
        jsonb_build_object(
            'title', pod.title,
            'image_url', pod.image_url,
            'listennotes_id', pod.listennotes_id
        ) AS podcasts,
        1.0::REAL AS ts_rank_score
    FROM public.episodes e
    LEFT JOIN public.podcasts pod ON e.podcast_id = pod.id
    WHERE LOWER(e.title) LIKE '%' || LOWER(search_query) || '%'
    ORDER BY
        CASE
            WHEN LOWER(e.title) = LOWER(search_query) THEN 1  -- Exact match
            ELSE 2  -- Phrase match
        END
    LIMIT result_limit
    OFFSET result_offset;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION search_episodes_ranked(TEXT, INTEGER, INTEGER) IS
'Search episodes by title only (exact and phrase matching).
Returns results ordered by match type (exact first, then phrase matches).
Includes podcast information as JSONB.';
