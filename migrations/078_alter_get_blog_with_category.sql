CREATE OR REPLACE FUNCTION public.get_blogs_with_categories(
    p_limit INT,
    p_offset INT
)
RETURNS TABLE (
    id UUID,
    slug TEXT,
    title TEXT,
    summary TEXT,
    content TEXT,
    created_at TIMESTAMPTZ,
    author TEXT,
    categories JSON,
    is_featured BOOLEAN
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        r.id,
        r.id::TEXT AS slug,
        r.title::TEXT as title,
        r.description AS summary,
        r.content::TEXT AS content,
        r.created_at,
        'Podground Team' AS author,
        COALESCE(
            (
                SELECT json_agg(
                    json_build_object('id', bc.id, 'name', bc.name)
                )
                FROM blog_resource_categories brc
                JOIN blog_categories bc
                  ON brc.category_id = bc.id
                WHERE brc.resource_id = r.id
            ),
            '[]'::JSON
        ),
    r.is_featured
    FROM resources r
    WHERE r.is_blog = TRUE
      AND r.type = 'article'
    ORDER BY r.created_at DESC
    LIMIT p_limit
    OFFSET p_offset;
END;
$$;
