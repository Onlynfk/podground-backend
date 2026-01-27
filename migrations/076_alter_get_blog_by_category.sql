CREATE FUNCTION public.get_blogs_by_category(
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
    image_url TEXT,
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
        r.title::TEXT AS title,
        r.description AS summary,
        NULL::TEXT AS content,
        r.image_url::TEXT AS image_url,
        r.created_at,
        'Podground Team' AS author,
        COALESCE(
            (
                SELECT json_agg(
                    json_build_object('id', bc.id, 'name', bc.name)
                )
                FROM blog_resource_categories brc2
                JOIN blog_categories bc ON bc.id = brc2.category_id
                WHERE brc2.resource_id = r.id
            ),
            '[]'::JSON
        ),
        r.is_featured
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
