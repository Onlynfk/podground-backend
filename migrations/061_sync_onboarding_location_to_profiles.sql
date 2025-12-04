-- Migration: Sync onboarding location data to user_profiles
-- Description: Copy location_id from user_onboarding to user_profiles.location for completed onboarding
-- Format: "City, Country" by concatenating name and country_name

-- Update existing user_profiles with location from user_onboarding
UPDATE user_profiles up
SET location = sc.name || ', ' || sc.country_name
FROM user_onboarding uo
JOIN states_countries sc ON uo.location_id = sc.id
WHERE up.user_id = uo.id
  AND uo.is_completed = TRUE
  AND uo.location_id IS NOT NULL
  AND sc.name IS NOT NULL
  AND sc.country_name IS NOT NULL;

-- Log the number of profiles updated
DO $$
DECLARE
  updated_count INTEGER;
BEGIN
  GET DIAGNOSTICS updated_count = ROW_COUNT;
  RAISE NOTICE 'Updated % user profiles with location data from onboarding', updated_count;
END $$;
