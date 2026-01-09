-- Migration: Create user_onboarding_categories junction table
-- Description: Stores the podcast categories selected by users during onboarding

CREATE TABLE IF NOT EXISTS public.user_onboarding_categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    category_id UUID NOT NULL REFERENCES public.podcast_categories(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Ensure each user can only select a category once
    UNIQUE(user_id, category_id)
);

-- Create indexes for performance (IF NOT EXISTS)
CREATE INDEX IF NOT EXISTS idx_user_onboarding_categories_user_id ON public.user_onboarding_categories(user_id);
CREATE INDEX IF NOT EXISTS idx_user_onboarding_categories_category_id ON public.user_onboarding_categories(category_id);

-- Enable RLS (only if table was just created)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_tables 
        WHERE schemaname = 'public' 
        AND tablename = 'user_onboarding_categories' 
        AND rowsecurity = true
    ) THEN
        ALTER TABLE public.user_onboarding_categories ENABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- Drop existing policies if they exist and recreate them
DROP POLICY IF EXISTS "Category selections viewable by authenticated users" ON public.user_onboarding_categories;
DROP POLICY IF EXISTS "Users can insert their own category selections" ON public.user_onboarding_categories;
DROP POLICY IF EXISTS "Users can update their own category selections" ON public.user_onboarding_categories;
DROP POLICY IF EXISTS "Users can delete their own category selections" ON public.user_onboarding_categories;

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
COMMENT ON TABLE public.user_onboarding_categories IS 'Junction table storing podcast categories selected by users during onboarding step 2';