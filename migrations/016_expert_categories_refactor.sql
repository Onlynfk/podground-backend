-- Migration: Refactor expert tags to categories with proper relationships
-- This creates a many-to-many relationship between experts and categories

-- First, create expert categories table
CREATE TABLE IF NOT EXISTS public.expert_categories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    icon_name VARCHAR(50),
    color VARCHAR(7), -- hex color code
    sort_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create expert-category mapping table
CREATE TABLE IF NOT EXISTS public.expert_category_mappings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    expert_id UUID NOT NULL REFERENCES public.experts(id) ON DELETE CASCADE,
    category_id UUID NOT NULL REFERENCES public.expert_categories(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Ensure unique combinations
    UNIQUE(expert_id, category_id)
);

-- Insert default expert categories
INSERT INTO public.expert_categories (name, display_name, description, sort_order, color) VALUES
('audio-production', 'Audio Production', 'Recording, editing, mixing, and mastering expertise', 1, '#FF6B6B'),
('content-strategy', 'Content Strategy', 'Content planning, storytelling, and format development', 2, '#4ECDC4'),
('marketing-growth', 'Marketing & Growth', 'Audience building, social media, and promotion strategies', 3, '#45B7D1'),
('technical-setup', 'Technical Setup', 'Equipment, hosting, distribution, and technical infrastructure', 4, '#96CEB4'),
('business-monetization', 'Business & Monetization', 'Revenue streams, sponsorships, and business development', 5, '#FFEAA7'),
('interview-skills', 'Interview Skills', 'Interview techniques, guest management, and conversation flow', 6, '#DDA0DD'),
('show-production', 'Show Production', 'End-to-end podcast production and project management', 7, '#98D8C8'),
('voice-performance', 'Voice & Performance', 'Voice coaching, presentation skills, and on-air presence', 8, '#F7DC6F'),
('analytics-optimization', 'Analytics & Optimization', 'Data analysis, performance tracking, and optimization strategies', 9, '#BB8FCE')
ON CONFLICT (name) DO NOTHING;

-- Remove the tags column from experts table (if it exists)
ALTER TABLE public.experts DROP COLUMN IF EXISTS tags;

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_expert_categories_name ON public.expert_categories(name);
CREATE INDEX IF NOT EXISTS idx_expert_categories_is_active ON public.expert_categories(is_active);
CREATE INDEX IF NOT EXISTS idx_expert_categories_sort_order ON public.expert_categories(sort_order);

CREATE INDEX IF NOT EXISTS idx_expert_category_mappings_expert_id ON public.expert_category_mappings(expert_id);
CREATE INDEX IF NOT EXISTS idx_expert_category_mappings_category_id ON public.expert_category_mappings(category_id);

-- Enable RLS on new tables
ALTER TABLE public.expert_categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.expert_category_mappings ENABLE ROW LEVEL SECURITY;

-- RLS Policies for expert categories (public read, admin write)
CREATE POLICY "Anyone can view expert categories" ON public.expert_categories
    FOR SELECT USING (is_active = true);

CREATE POLICY "Only admins can manage expert categories" ON public.expert_categories
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM public.user_roles 
            WHERE user_id = auth.uid() AND role = 'admin' AND is_active = true
        )
    );

-- RLS Policies for expert category mappings (public read, admin write)
CREATE POLICY "Anyone can view expert category mappings" ON public.expert_category_mappings
    FOR SELECT USING (true);

CREATE POLICY "Only admins can manage expert category mappings" ON public.expert_category_mappings
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM public.user_roles 
            WHERE user_id = auth.uid() AND role = 'admin' AND is_active = true
        )
    );

-- Grant permissions
GRANT SELECT ON TABLE public.expert_categories TO authenticated;
GRANT SELECT ON TABLE public.expert_category_mappings TO authenticated;
GRANT ALL ON TABLE public.expert_categories TO service_role;
GRANT ALL ON TABLE public.expert_category_mappings TO service_role;

-- Add comments
COMMENT ON TABLE public.expert_categories IS 'Categories for expert specializations and filtering';
COMMENT ON TABLE public.expert_category_mappings IS 'Many-to-many mapping between experts and their categories';

COMMENT ON COLUMN public.expert_categories.color IS 'Hex color code for UI display (e.g., #FF6B6B)';
COMMENT ON COLUMN public.expert_categories.icon_name IS 'Icon identifier for UI display';