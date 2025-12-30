-- Migration: Enable RLS on subscription_plans table
-- Issue: Table is public but RLS has not been enabled
-- Fix: Enable RLS with appropriate read policies

-- Enable Row Level Security on subscription_plans table
ALTER TABLE public.subscription_plans ENABLE ROW LEVEL SECURITY;

-- Create policy: All authenticated users can view subscription plans
-- This is intentional as users need to see available plans to make purchasing decisions
CREATE POLICY "Anyone can view subscription plans" 
ON public.subscription_plans 
FOR SELECT 
USING (true);  -- All users can see all plans

-- Create policy: Only service role can manage subscription plans
-- This prevents users from modifying plan details
CREATE POLICY "Service role can manage subscription plans" 
ON public.subscription_plans 
FOR ALL 
USING (auth.role() = 'service_role');

-- Add comment to document the security model
COMMENT ON TABLE public.subscription_plans IS 
'Subscription plans available in the system. RLS enabled with public read access (intentional) as users need to see available plans. Only service role can modify plans.';

-- Verify other tables that might need RLS
DO $$
DECLARE
    rec RECORD;
    missing_rls_tables TEXT := '';
BEGIN
    -- Check for tables without RLS in public schema
    FOR rec IN 
        SELECT tablename 
        FROM pg_tables 
        WHERE schemaname = 'public' 
        AND rowsecurity = false
        AND tablename NOT IN (
            -- System tables that don't need RLS
            'schema_migrations',
            'spatial_ref_sys',
            -- Tables that are intentionally public
            'podcast_categories'  -- Categories are public info
        )
    LOOP
        missing_rls_tables := missing_rls_tables || rec.tablename || ', ';
    END LOOP;
    
    IF missing_rls_tables != '' THEN
        RAISE NOTICE 'Tables still missing RLS: %', rtrim(missing_rls_tables, ', ');
    END IF;
END $$;

-- Additional security notes:
-- 1. subscription_plans table contains pricing and features - public info by design
-- 2. user_subscriptions table (which links users to plans) has proper RLS
-- 3. Only admins/service role should be able to create or modify plans
-- 4. All users need read access to see available plans and pricing