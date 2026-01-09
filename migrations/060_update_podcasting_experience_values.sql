-- Migration: Update podcasting experience values from 5_years_plus to 3_years_plus
-- This updates the check constraint on user_onboarding table

-- Drop the old constraint
ALTER TABLE public.user_onboarding
DROP CONSTRAINT IF EXISTS user_onboarding_podcasting_experience_check;

-- Add the new constraint with updated value
ALTER TABLE public.user_onboarding
ADD CONSTRAINT user_onboarding_podcasting_experience_check
CHECK (podcasting_experience IN ('0-1_year', '1-3_years', '3_years_plus'));

-- Update any existing data that has the old value
UPDATE public.user_onboarding
SET podcasting_experience = '3_years_plus'
WHERE podcasting_experience = '5_years_plus';
