create table public.blog_categories (
  id uuid not null default gen_random_uuid (),
  name character varying(255) not null,
  slug character varying(255) not null,
  description text null,
  created_at timestamp without time zone null default CURRENT_TIMESTAMP,
  constraint blog_categories_pkey primary key (id),
  constraint blog_categories_slug_key unique (slug)
) TABLESPACE pg_default;
