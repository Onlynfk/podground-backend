-- Migration: Update subscriptions table for lifetime memberships
-- Description: Add support for one-time payment lifetime memberships alongside recurring Pro subscriptions

-- Add new columns to subscriptions table
ALTER TABLE public.subscriptions
ADD COLUMN IF NOT EXISTS subscription_type TEXT NOT NULL DEFAULT 'recurring' CHECK (subscription_type IN ('recurring', 'lifetime')),
ADD COLUMN IF NOT EXISTS lifetime_access BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS payment_intent_id TEXT; -- For one-time payments

-- Update status check constraint to include lifetime-specific status
ALTER TABLE public.subscriptions DROP CONSTRAINT IF EXISTS subscriptions_status_check;
ALTER TABLE public.subscriptions ADD CONSTRAINT subscriptions_status_check
CHECK (status IN (
    'active',
    'canceled',
    'incomplete',
    'incomplete_expired',
    'past_due',
    'trialing',
    'unpaid',
    'paused',
    'lifetime_active' -- New status for lifetime members
));

-- Create index for lifetime memberships
CREATE INDEX IF NOT EXISTS idx_subscriptions_subscription_type ON public.subscriptions(subscription_type);
CREATE INDEX IF NOT EXISTS idx_subscriptions_lifetime_access ON public.subscriptions(lifetime_access) WHERE lifetime_access = TRUE;

-- Add comments
COMMENT ON COLUMN public.subscriptions.subscription_type IS 'Type of subscription: recurring (Pro monthly) or lifetime (one-time payment)';
COMMENT ON COLUMN public.subscriptions.lifetime_access IS 'Whether user has lifetime access (one-time payment)';
COMMENT ON COLUMN public.subscriptions.payment_intent_id IS 'Stripe Payment Intent ID for one-time payments';
