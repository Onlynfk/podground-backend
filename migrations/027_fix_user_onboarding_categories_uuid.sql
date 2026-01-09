-- Migration: Fix user_onboarding_categories table to use UUID for category_id
-- Description: Alters the category_id column from INTEGER to UUID to match podcast_categories schema

-- Drop the table and recreate it with correct UUID types
-- This is the safest approach since the table likely has wrong column types
DROP TABLE IF EXISTS public.user_onboarding_categories CASCADE;

-- Recreate the table with correct UUID structure
CREATE TABLE public.user_onboarding_categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    category_id UUID NOT NULL REFERENCES public.podcast_categories(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Ensure each user can only select a category once
    UNIQUE(user_id, category_id)
);

-- Create indexes for performance
CREATE INDEX idx_user_onboarding_categories_user_id ON public.user_onboarding_categories(user_id);
CREATE INDEX idx_user_onboarding_categories_category_id ON public.user_onboarding_categories(category_id);

-- Enable RLS
ALTER TABLE public.user_onboarding_categories ENABLE ROW LEVEL SECURITY;

-- RLS Policies
-- Users can view all category selections (for analytics/recommendations)
CREATE POLICY "Category selections viewable by authenticated users" ON public.user_onboarding_categories
    FOR SELECT
    USING (auth.uid() IS NOT NULL);

-- Users can only insert their own category selections
CREATE POLICY "Users can insert their own category selections" ON public.user_onboarding_categories
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Users can only update their own category selections
CREATE POLICY "Users can update their own category selections" ON public.user_onboarding_categories
    FOR UPDATE
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Users can only delete their own category selections
CREATE POLICY "Users can delete their own category selections" ON public.user_onboarding_categories
    FOR DELETE
    USING (auth.uid() = user_id);

-- Add comment
COMMENT ON TABLE public.user_onboarding_categories IS 'Junction table storing podcast categories selected by users during onboarding step 2 - Fixed to use UUID types';