-- Fix post category keywords to match the podcasting-focused categories
-- The keywords were still from the old generic categories, causing AI miscategorization

-- Update keywords for each podcasting-focused category
UPDATE public.post_categories
SET keywords = ARRAY[
    'audience', 'growth', 'promotion', 'marketing', 'listeners', 'reach',
    'seo', 'discovery', 'social media', 'advertising', 'promotion strategy',
    'listener engagement', 'audience building', 'podcast marketing', 'outreach',
    'branding', 'visibility', 'discoverability', 'grow', 'increase listeners'
]
WHERE name = 'technology'  -- This was reused for "Grow Your Audience"
   OR display_name = 'Grow Your Audience';

UPDATE public.post_categories
SET keywords = ARRAY[
    'equipment', 'gear', 'microphone', 'audio', 'mic', 'recording',
    'software', 'hardware', 'tools', 'daw', 'editing', 'production',
    'studio', 'setup', 'tech', 'headphones', 'mixer', 'interface',
    'recommend', 'recommendation', 'best gear', 'podcast equipment'
]
WHERE name = 'news-politics'  -- This was reused for "Gears & Tools"
   OR display_name = 'Gears & Tools';

UPDATE public.post_categories
SET keywords = ARRAY[
    'guest', 'interview', 'collaboration', 'looking for', 'be a guest',
    'guest appearance', 'expert', 'speaker', 'collaborate', 'feature',
    'invite', 'booking', 'guest search', 'guest wanted', 'guest opportunity',
    'pitch', 'guest spot', 'co-host', 'interview opportunity'
]
WHERE name = 'general'  -- This was reused for "Find or Be a Guest"
   OR display_name = 'Find or Be a Guest';

UPDATE public.post_categories
SET keywords = ARRAY[
    'win', 'milestone', 'celebration', 'achievement', 'success', 'reached',
    'accomplished', 'proud', 'excited', 'hit', 'goal', 'downloads',
    'subscribers', 'reviews', 'rating', 'breakthrough', 'first episode',
    'anniversary', 'launched', 'celebrate', 'congratulations', 'milestone reached'
]
WHERE name = 'entertainment'  -- This was reused for "Celebrate Wins"
   OR display_name = 'Celebrate Wins';

UPDATE public.post_categories
SET keywords = ARRAY[
    'question', 'help', 'advice', 'how to', 'tips', 'beginner',
    'starting out', 'podcast advice', 'best practices', 'wondering',
    'should i', 'what do you think', 'recommendations', 'guidance',
    'learning', 'new to podcasting', 'confused', 'struggling', 'need help',
    'any tips', 'how do i', 'what is', 'can someone explain'
]
WHERE name = 'tech'  -- This was reused for "Ask a Podcast Question"
   OR display_name = 'Ask a Podcast Question';

-- If there are any other categories, update them as well
-- Check for Business category (might be "Monetization" or similar)
UPDATE public.post_categories
SET keywords = ARRAY[
    'monetization', 'money', 'revenue', 'sponsors', 'sponsorship',
    'ads', 'advertising', 'income', 'profit', 'business model',
    'pricing', 'patreon', 'membership', 'sell', 'earn', 'make money',
    'financial', 'paid', 'subscription', 'donations'
]
WHERE name = 'business'
  AND display_name NOT IN (
    'Grow Your Audience',
    'Gears & Tools',
    'Find or Be a Guest',
    'Celebrate Wins',
    'Ask a Podcast Question'
  );

-- Check for Content/Production category
UPDATE public.post_categories
SET keywords = ARRAY[
    'content', 'episode', 'format', 'structure', 'scripting',
    'editing', 'production', 'workflow', 'publishing', 'schedule',
    'consistency', 'episode ideas', 'topics', 'planning', 'outline',
    'recording', 'post-production', 'content strategy', 'show notes'
]
WHERE (name = 'education' OR name = 'lifestyle')
  AND display_name NOT IN (
    'Grow Your Audience',
    'Gears & Tools',
    'Find or Be a Guest',
    'Celebrate Wins',
    'Ask a Podcast Question'
  );

-- Show updated categories
SELECT
    display_name,
    description,
    array_to_string(keywords, ', ') as keywords_list
FROM public.post_categories
WHERE is_active = true
ORDER BY sort_order;
