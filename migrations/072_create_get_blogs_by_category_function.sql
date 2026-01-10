CREATE OR REPLACE FUNCTION public.get_blogs_by_category(
    p_category_id UUID,
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
    categories JSON
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        r.id,
        r.id::TEXT AS slug,
        r.title,
        r.description AS summary,
        NULL::TEXT AS content,
        r.created_at,
        'Podground Team' AS author,
        COALESCE(
            (
                SELECT json_agg(
                    json_build_object('id', bc.id, 'name', bc.name)
                )
                FROM blog_resource_categories brc2
                JOIN blog_categories bc
                  ON bc.id = brc2.category_id
                WHERE brc2.resource_id = r.id
            ),
            '[]'::JSON
        )
    FROM resources r
    WHERE r.is_blog = TRUE
      AND r.type = 'article'
      AND EXISTS (
          SELECT 1
          FROM blog_resource_categories brc1
          WHERE brc1.resource_id = r.id
            AND brc1.category_id = p_category_id
      )
    ORDER BY r.created_at DESC
    LIMIT p_limit
    OFFSET p_offset;
END;
$$;

