-- Migration: Update onboarding from 6 steps to 5 steps
-- Description: Remove step_6_completed column and update is_completed logic
-- The new step 5 (favorite podcasts) becomes the final step

-- Note: step_6_completed column will remain in the database for backwards compatibility
-- but will no longer be used by the application. The is_completed flag will now be
-- set when step_5 is completed.

-- Update any records that have completed step 5 to mark as fully completed
UPDATE public.user_onboarding
SET is_completed = TRUE,
    completed_at = COALESCE(completed_at, NOW())
WHERE step_5_completed = TRUE
  AND is_completed = FALSE;

-- Update current_step for users who were at step 6
UPDATE public.user_onboarding
SET current_step = 5
WHERE current_step = 6;

-- Add comment to document the change
COMMENT ON COLUMN public.user_onboarding.step_6_completed IS 'DEPRECATED: Step 6 was removed in the 5-step onboarding refactor. This column is kept for backwards compatibility but is no longer used.';

-- Add comment about the new completion logic
COMMENT ON COLUMN public.user_onboarding.is_completed IS 'Set to TRUE when all 5 onboarding steps are completed (previously required 6 steps)';