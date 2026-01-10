-- Force fix user_connections foreign keys
-- This script forcefully drops and recreates the constraints

-- First, check if there's a public.users table that shouldn't exist
DROP TABLE IF EXISTS public.users CASCADE;

-- Fix follower_id constraint
ALTER TABLE public.user_connections DROP CONSTRAINT IF EXISTS user_connections_follower_id_fkey CASCADE;

-- Clean up orphaned records before adding constraint
DELETE FROM public.user_connections
WHERE follower_id NOT IN (SELECT id FROM auth.users);

-- Add correct constraint
ALTER TABLE public.user_connections
ADD CONSTRAINT user_connections_follower_id_fkey
FOREIGN KEY (follower_id) REFERENCES auth.users(id) ON DELETE CASCADE;

-- Fix following_id constraint
ALTER TABLE public.user_connections DROP CONSTRAINT IF EXISTS user_connections_following_id_fkey CASCADE;

-- Clean up orphaned records
DELETE FROM public.user_connections
WHERE following_id NOT IN (SELECT id FROM auth.users);

-- Add correct constraint
ALTER TABLE public.user_connections
ADD CONSTRAINT user_connections_following_id_fkey
FOREIGN KEY (following_id) REFERENCES auth.users(id) ON DELETE CASCADE;

-- Verify the constraints
SELECT
    conname AS constraint_name,
    conrelid::regclass AS table_name,
    confrelid::regclass AS referenced_table,
    pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'public.user_connections'::regclass
AND contype = 'f'
ORDER BY conname;
