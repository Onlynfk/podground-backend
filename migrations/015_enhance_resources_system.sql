-- Migration: Enhance resources system with experts and partners
-- This adds expert profiles, partner deals, and enhances the resources table

-- Enhance resources table with additional columns needed
ALTER TABLE public.resources 
ADD COLUMN IF NOT EXISTS category VARCHAR(100) DEFAULT 'general',
ADD COLUMN IF NOT EXISTS subcategory VARCHAR(100),
ADD COLUMN IF NOT EXISTS video_url TEXT,
ADD COLUMN IF NOT EXISTS download_url TEXT,
ADD COLUMN IF NOT EXISTS duration INTEGER, -- video duration in minutes
ADD COLUMN IF NOT EXISTS difficulty_level VARCHAR(20) DEFAULT 'beginner',
ADD COLUMN IF NOT EXISTS tags TEXT[],
ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS thumbnail_url TEXT,
ADD COLUMN IF NOT EXISTS view_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- Update the constraint to include more resource types
ALTER TABLE public.resources DROP CONSTRAINT IF EXISTS valid_resource_type;
ALTER TABLE public.resources ADD CONSTRAINT valid_resource_type 
CHECK (type IN ('article', 'video', 'guide', 'tool', 'template', 'course'));

-- Add constraint for difficulty levels
ALTER TABLE public.resources ADD CONSTRAINT valid_difficulty_level 
CHECK (difficulty_level IN ('beginner', 'intermediate', 'advanced'));

-- Create experts table
CREATE TABLE IF NOT EXISTS public.experts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    title VARCHAR(255) NOT NULL,
    specialization VARCHAR(255) NOT NULL,
    bio TEXT,
    avatar_url TEXT,
    contact_email TEXT,
    linkedin_url TEXT,
    website_url TEXT,
    is_available BOOLEAN DEFAULT TRUE,
    hourly_rate DECIMAL(10,2),
    rating DECIMAL(2,1) DEFAULT 5.0,
    total_sessions INTEGER DEFAULT 0,
    years_experience INTEGER,
    tags TEXT[],
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create partner deals table
CREATE TABLE IF NOT EXISTS public.partner_deals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    partner_name VARCHAR(255) NOT NULL,
    deal_title VARCHAR(500) NOT NULL,
    description TEXT,
    image_url TEXT,
    deal_url TEXT NOT NULL,
    platform VARCHAR(100), -- YouTube, Spotify, etc.
    discount_percent INTEGER,
    original_price DECIMAL(10,2),
    discounted_price DECIMAL(10,2),
    expires_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE,
    category VARCHAR(100),
    tags TEXT[],
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create resource categories lookup table
CREATE TABLE IF NOT EXISTS public.resource_categories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    icon_name VARCHAR(50),
    sort_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default resource categories
INSERT INTO public.resource_categories (name, display_name, description, sort_order) VALUES
('planning', 'Planning & Strategy', 'Content planning, show structure, and strategic guidance', 1),
('production', 'Production & Editing', 'Recording techniques, editing tools, and production workflows', 2),
('promotion', 'Promotion & Audience Growth', 'Marketing strategies, social media, and audience building', 3),
('monetization', 'Monetization & Offers', 'Revenue streams, sponsorships, and business models', 4),
('guest-management', 'Guest Management', 'Finding guests, interview techniques, and relationship building', 5),
('mindset', 'Mindset & Confidence', 'Overcoming fears, building confidence, and mental frameworks', 6),
('community', 'Community & Network', 'Building communities, networking, and collaboration', 7),
('equipment', 'Equipment & Tools', 'Microphones, software, and technical setups', 8),
('analytics', 'Analytics & Growth', 'Measuring success, analytics tools, and growth metrics', 9)
ON CONFLICT (name) DO NOTHING;

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_resources_category ON public.resources(category);
CREATE INDEX IF NOT EXISTS idx_resources_type ON public.resources(type);
CREATE INDEX IF NOT EXISTS idx_resources_is_premium ON public.resources(is_premium);
CREATE INDEX IF NOT EXISTS idx_resources_created_at ON public.resources(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_resources_tags ON public.resources USING GIN (tags);

CREATE INDEX IF NOT EXISTS idx_experts_specialization ON public.experts(specialization);
CREATE INDEX IF NOT EXISTS idx_experts_is_available ON public.experts(is_available);
CREATE INDEX IF NOT EXISTS idx_experts_rating ON public.experts(rating DESC);

CREATE INDEX IF NOT EXISTS idx_partner_deals_is_active ON public.partner_deals(is_active);
CREATE INDEX IF NOT EXISTS idx_partner_deals_expires_at ON public.partner_deals(expires_at);
CREATE INDEX IF NOT EXISTS idx_partner_deals_category ON public.partner_deals(category);

-- Enable RLS on new tables
ALTER TABLE public.experts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.partner_deals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.resource_categories ENABLE ROW LEVEL SECURITY;

-- RLS Policies for experts (public read, admin write)
CREATE POLICY "Anyone can view experts" ON public.experts
    FOR SELECT USING (true);

CREATE POLICY "Only admins can manage experts" ON public.experts
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM public.user_roles 
            WHERE user_id = auth.uid() AND role = 'admin' AND is_active = true
        )
    );

-- RLS Policies for partner deals (public read, admin write)  
CREATE POLICY "Anyone can view active partner deals" ON public.partner_deals
    FOR SELECT USING (is_active = true);

CREATE POLICY "Only admins can manage partner deals" ON public.partner_deals
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM public.user_roles 
            WHERE user_id = auth.uid() AND role = 'admin' AND is_active = true
        )
    );

-- RLS Policies for resource categories (public read, admin write)
CREATE POLICY "Anyone can view resource categories" ON public.resource_categories
    FOR SELECT USING (is_active = true);

CREATE POLICY "Only admins can manage resource categories" ON public.resource_categories
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM public.user_roles 
            WHERE user_id = auth.uid() AND role = 'admin' AND is_active = true
        )
    );

-- Grant permissions
GRANT SELECT ON TABLE public.experts TO authenticated;
GRANT SELECT ON TABLE public.partner_deals TO authenticated;
GRANT SELECT ON TABLE public.resource_categories TO authenticated;
GRANT ALL ON TABLE public.experts TO service_role;
GRANT ALL ON TABLE public.partner_deals TO service_role;
GRANT ALL ON TABLE public.resource_categories TO service_role;

-- Add comments
COMMENT ON TABLE public.experts IS 'Expert profiles for "Connect with an Expert" feature';
COMMENT ON TABLE public.partner_deals IS 'Partner deals and offers for podcasters';
COMMENT ON TABLE public.resource_categories IS 'Categories for organizing resources';

COMMENT ON COLUMN public.resources.is_premium IS 'True for premium video content, false for free content';
COMMENT ON COLUMN public.resources.category IS 'Main category (planning, production, etc.)';
COMMENT ON COLUMN public.resources.tags IS 'Searchable tags for content discovery';