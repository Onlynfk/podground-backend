-- Migration: Add Founding Member subscription plan
-- This adds the third tier mentioned in requirements: Free, Pro, Founding Member

-- Insert the Founding Member plan
INSERT INTO public.subscription_plans (
    name, 
    display_name, 
    description, 
    price_monthly, 
    price_yearly, 
    features, 
    can_access_premium_resources, 
    can_access_analytics, 
    can_create_events
) VALUES (
    'founding_member',
    'Founding Member', 
    'Exclusive founding member benefits with lifetime access',
    19.99,  -- Higher price than Pro
    199.99, -- Higher price than Pro
    '[
        "everything_in_pro", 
        "lifetime_access", 
        "founding_member_badge", 
        "exclusive_features", 
        "early_access", 
        "direct_feedback_channel",
        "founding_member_community"
    ]'::jsonb,
    TRUE,  -- Can access premium resources
    TRUE,  -- Can access analytics  
    TRUE   -- Can create events
);

-- Add comment to document the plan
COMMENT ON TABLE public.subscription_plans IS 'Subscription plans: free (default), pro (paid), founding_member (premium paid)';

-- Verify the plan was created
SELECT name, display_name, price_monthly, price_yearly 
FROM public.subscription_plans 
ORDER BY price_monthly;