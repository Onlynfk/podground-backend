-- Migration 026: Drop Expert Categories System
-- Remove expert categories and category mappings tables since categories are no longer used for experts

-- Drop the junction table first (due to foreign key constraints)
DROP TABLE IF EXISTS public.expert_category_mappings;

-- Drop the categories table
DROP TABLE IF EXISTS public.expert_categories;

-- Note: The experts table itself remains unchanged
-- Experts now use their 'specialization' field instead of categories