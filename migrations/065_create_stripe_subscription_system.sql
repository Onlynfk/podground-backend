-- Migration: Create Stripe subscription system
-- Description: Add subscriptions table and stripe_customer_id to users for Stripe integration

-- Add stripe_customer_id to users table (via auth.users metadata)
-- Note: Supabase auth.users stores custom data in raw_user_meta_data
-- We'll track this in a separate user_stripe_customers table for better querying

-- Create subscriptions table
CREATE TABLE IF NOT EXISTS public.subscriptions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    stripe_subscription_id TEXT UNIQUE NOT NULL,
    stripe_customer_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'active',
        'canceled',
        'incomplete',
        'incomplete_expired',
        'past_due',
        'trialing',
        'unpaid',
        'paused'
    )),
    plan_id TEXT NOT NULL, -- Stripe Price ID
    current_period_start TIMESTAMPTZ NOT NULL,
    current_period_end TIMESTAMPTZ NOT NULL,
    cancel_at_period_end BOOLEAN DEFAULT FALSE,
    canceled_at TIMESTAMPTZ,
    trial_start TIMESTAMPTZ,
    trial_end TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, stripe_subscription_id)
);

-- Create user_stripe_customers mapping table
CREATE TABLE IF NOT EXISTS public.user_stripe_customers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID UNIQUE NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    stripe_customer_id TEXT UNIQUE NOT NULL,
    email TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON public.subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe_subscription_id ON public.subscriptions(stripe_subscription_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe_customer_id ON public.subscriptions(stripe_customer_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON public.subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_subscriptions_current_period_end ON public.subscriptions(current_period_end);
CREATE INDEX IF NOT EXISTS idx_user_stripe_customers_user_id ON public.user_stripe_customers(user_id);
CREATE INDEX IF NOT EXISTS idx_user_stripe_customers_stripe_customer_id ON public.user_stripe_customers(stripe_customer_id);

-- Add updated_at trigger for subscriptions
CREATE OR REPLACE FUNCTION update_subscriptions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_subscriptions_updated_at
    BEFORE UPDATE ON public.subscriptions
    FOR EACH ROW
    EXECUTE FUNCTION update_subscriptions_updated_at();

-- Add updated_at trigger for user_stripe_customers
CREATE OR REPLACE FUNCTION update_user_stripe_customers_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_user_stripe_customers_updated_at
    BEFORE UPDATE ON public.user_stripe_customers
    FOR EACH ROW
    EXECUTE FUNCTION update_user_stripe_customers_updated_at();

-- Add RLS policies
ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_stripe_customers ENABLE ROW LEVEL SECURITY;

-- Users can view their own subscriptions
CREATE POLICY "Users can view their own subscriptions"
    ON public.subscriptions
    FOR SELECT
    USING (auth.uid() = user_id);

-- Service role can manage all subscriptions (for webhook handlers)
CREATE POLICY "Service role can manage all subscriptions"
    ON public.subscriptions
    FOR ALL
    USING (auth.role() = 'service_role');

-- Users can view their own stripe customer data
CREATE POLICY "Users can view their own stripe customer data"
    ON public.user_stripe_customers
    FOR SELECT
    USING (auth.uid() = user_id);

-- Service role can manage all stripe customer data
CREATE POLICY "Service role can manage all stripe customer data"
    ON public.user_stripe_customers
    FOR ALL
    USING (auth.role() = 'service_role');

-- Add comments
COMMENT ON TABLE public.subscriptions IS 'Stores Stripe subscription data for users';
COMMENT ON TABLE public.user_stripe_customers IS 'Maps users to their Stripe customer IDs';
COMMENT ON COLUMN public.subscriptions.stripe_subscription_id IS 'Stripe subscription ID (sub_xxx)';
COMMENT ON COLUMN public.subscriptions.stripe_customer_id IS 'Stripe customer ID (cus_xxx)';
COMMENT ON COLUMN public.subscriptions.status IS 'Subscription status from Stripe';
COMMENT ON COLUMN public.subscriptions.plan_id IS 'Stripe Price ID (price_xxx)';
COMMENT ON COLUMN public.subscriptions.cancel_at_period_end IS 'Whether subscription will cancel at period end';
