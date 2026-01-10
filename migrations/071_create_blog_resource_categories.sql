create table public.blog_resource_categories (
  category_id uuid not null,
  resource_id uuid not null,
  constraint blog_resource_categories_pkey primary key (category_id, resource_id),
  constraint fk_category foreign KEY (category_id) references blog_categories (id) on delete CASCADE,
  constraint fk_resource foreign KEY (resource_id) references resources (id) on delete CASCADE
) TABLESPACE pg_default;