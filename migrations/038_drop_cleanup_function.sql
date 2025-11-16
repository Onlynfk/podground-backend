-- Migration: Drop unused cleanup function
-- Removes get_expired_temp_media() function that was never implemented

-- Drop the function if it exists
DROP FUNCTION IF EXISTS get_expired_temp_media();
