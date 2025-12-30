-- Create category_genre mapping table to map ListenNotes genre IDs to our category IDs
CREATE TABLE IF NOT EXISTS public.category_genre (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    genre_id INTEGER NOT NULL UNIQUE,
    category_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES public.podcast_categories(id) ON DELETE CASCADE
);

-- Add index for fast lookups
CREATE INDEX IF NOT EXISTS idx_category_genre_genre_id ON public.category_genre(genre_id);
CREATE INDEX IF NOT EXISTS idx_category_genre_category_id ON public.category_genre(category_id);

-- Insert the mappings
INSERT INTO public.category_genre (genre_id, category_id) VALUES
    (144, '34af2f25-0a1e-44a6-b035-3a746047800b'),
    (151, 'cdfc87fd-e0a9-4c55-bbc2-9edac04fb48a'),
    (88, 'e99a2344-c713-4b99-8016-6af5d78011cb'),
    (68, '0ccdecb7-1e3c-4876-9d40-8fa0f939a108'),
    (127, '3040a0e0-92f9-446d-b31c-446fa3b9545f'),
    (135, '1ac159a3-63bf-460b-a57f-6ebe31d8bd45'),
    (93, '9a29ce5b-b8ba-4d65-a604-f215a55382c2'),
    (125, 'ea4f389d-6f0e-4c95-8686-dcad9be5ac66'),
    (132, 'fab051b0-daf5-4c5a-a933-f068e6015b94'),
    (168, 'dcf8f278-8b39-446d-b4bf-199f55c28e02'),
    (134, '312453b7-838a-4780-867a-0b95cd60f4ca'),
    (77, 'bc458dca-8475-43b5-b5c1-6b6ae7f75197'),
    (82, '1ab9eb9a-2d5d-4f7d-9fe4-37861763249c'),
    (133, '41173aaf-9529-48db-9769-74c3ad525052'),
    (99, 'ede7227a-3da7-40f8-b82d-154196b9e1ec'),
    (69, '3a494217-f37b-4bcf-8679-ca08082aef5b'),
    (100, '19ad0af2-fc23-4df2-8434-d05ce6731587'),
    (107, 'dec901b2-bb1c-4ebc-888b-ba34206b6434'),
    (122, 'fdddb8ba-6495-4aa7-a08c-5a68ca4b284c'),
    (111, '055b3b96-1e96-49a7-a048-ad686ca45f02'),
    (117, '4b54108d-a9ce-4499-bcfa-50125d266f94')
ON CONFLICT (genre_id) DO NOTHING;

-- Add RLS policies
ALTER TABLE public.category_genre ENABLE ROW LEVEL SECURITY;

-- Allow all authenticated users to read the mappings (public data)
CREATE POLICY "Anyone can read category genre mappings" ON public.category_genre
    FOR SELECT USING (true);

-- Only service role can insert/update/delete
CREATE POLICY "Service role can manage category genre mappings" ON public.category_genre
    FOR ALL USING (auth.role() = 'service_role');

-- Add comment to table
COMMENT ON TABLE public.category_genre IS 'Maps ListenNotes genre IDs to our internal podcast category IDs';
COMMENT ON COLUMN public.category_genre.genre_id IS 'Genre ID from ListenNotes API';
COMMENT ON COLUMN public.category_genre.category_id IS 'Reference to our podcast_categories table';