-- =============================================
-- BITVORA EXCHANGE — Complete Supabase Migration
-- Run this in the Supabase SQL Editor
-- =============================================

-- ─────────────────────────────────────────────
-- 1. USERS TABLE
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.users (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    username TEXT UNIQUE NOT NULL CHECK (username ~ '^[a-zA-Z0-9_]{3,20}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_banned BOOLEAN NOT NULL DEFAULT FALSE,
    total_transactions INTEGER NOT NULL DEFAULT 0,
    total_inr_received NUMERIC NOT NULL DEFAULT 0,
    default_upi TEXT
);

ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

-- Users can read their own row
CREATE POLICY "users_select_own" ON public.users
    FOR SELECT USING (auth.uid() = id);

-- Users can update their own row (username change etc)
CREATE POLICY "users_update_own" ON public.users
    FOR UPDATE USING (auth.uid() = id);

-- Service role has unrestricted access
CREATE POLICY "users_service_all" ON public.users
    FOR ALL USING (auth.role() = 'service_role');


-- ─────────────────────────────────────────────
-- 2. TRANSACTIONS TABLE
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reference TEXT UNIQUE NOT NULL,
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    chain TEXT NOT NULL,
    asset TEXT NOT NULL,
    txid TEXT UNIQUE NOT NULL,
    amount_crypto NUMERIC NOT NULL,
    amount_inr NUMERIC,
    exchange_rate NUMERIC,
    platform_fee_pct NUMERIC NOT NULL DEFAULT 0.015,
    platform_fee_inr NUMERIC,
    deposit_address TEXT NOT NULL,
    payout_destination TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'verifying', 'verified', 'payout_queued', 'payout_sent', 'failed', 'expired')
    ),
    confirmations INTEGER NOT NULL DEFAULT 0,
    required_confirmations INTEGER NOT NULL,
    verified_at TIMESTAMPTZ,
    payout_queued_at TIMESTAMPTZ,
    payout_sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '30 minutes'),
    error_message TEXT,
    is_locked BOOLEAN NOT NULL DEFAULT FALSE,
    lock_acquired_at TIMESTAMPTZ,
    explorer_url TEXT
);

ALTER TABLE public.transactions ENABLE ROW LEVEL SECURITY;

-- Users can see their own transactions
CREATE POLICY "transactions_select_own" ON public.transactions
    FOR SELECT USING (auth.uid() = user_id);

-- Users can insert new transactions
CREATE POLICY "transactions_insert_own" ON public.transactions
    FOR INSERT WITH CHECK (auth.uid() = user_id);

-- No user updates — only service role can update
CREATE POLICY "transactions_service_all" ON public.transactions
    FOR ALL USING (auth.role() = 'service_role');



-- ─────────────────────────────────────────────
-- 8. SETTINGS TABLE
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "settings_service_all" ON public.settings
    FOR ALL USING (auth.role() = 'service_role');


-- Enable Realtime publication
ALTER PUBLICATION supabase_realtime ADD TABLE public.transactions;

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON public.transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_transactions_status ON public.transactions(status);
CREATE INDEX IF NOT EXISTS idx_transactions_reference ON public.transactions(reference);
CREATE INDEX IF NOT EXISTS idx_transactions_txid ON public.transactions(txid);
CREATE INDEX IF NOT EXISTS idx_transactions_locked ON public.transactions(is_locked) WHERE is_locked = TRUE;
CREATE INDEX IF NOT EXISTS idx_transactions_expires ON public.transactions(expires_at) WHERE status IN ('pending', 'verifying');


-- ─────────────────────────────────────────────
-- 3. TXID LEDGER (Anti-Double-Processing)
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.txid_ledger (
    txid TEXT PRIMARY KEY,
    chain TEXT NOT NULL,
    transaction_id UUID NOT NULL REFERENCES public.transactions(id) ON DELETE CASCADE,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.txid_ledger ENABLE ROW LEVEL SECURITY;

-- Service role only — no user access
CREATE POLICY "txid_ledger_service_only" ON public.txid_ledger
    FOR ALL USING (auth.role() = 'service_role');


-- ─────────────────────────────────────────────
-- 4. PAYOUT QUEUE
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.payout_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID NOT NULL REFERENCES public.transactions(id) ON DELETE CASCADE,
    payout_destination TEXT NOT NULL,
    amount_inr NUMERIC NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'processing', 'completed', 'failed')
    ),
    admin_note TEXT,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

ALTER TABLE public.payout_queue ENABLE ROW LEVEL SECURITY;

-- Service role only
CREATE POLICY "payout_queue_service_only" ON public.payout_queue
    FOR ALL USING (auth.role() = 'service_role');

CREATE INDEX IF NOT EXISTS idx_payout_queue_status ON public.payout_queue(status);
CREATE INDEX IF NOT EXISTS idx_payout_queue_tx ON public.payout_queue(transaction_id);


-- ─────────────────────────────────────────────
-- 5. DEPOSIT ADDRESSES
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.deposit_addresses (
    chain TEXT PRIMARY KEY,
    address TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.deposit_addresses ENABLE ROW LEVEL SECURITY;

-- Anyone can read active addresses
CREATE POLICY "deposit_addresses_public_read" ON public.deposit_addresses
    FOR SELECT USING (is_active = TRUE);

-- Service role has full access
CREATE POLICY "deposit_addresses_service_all" ON public.deposit_addresses
    FOR ALL USING (auth.role() = 'service_role');


-- ─────────────────────────────────────────────
-- 6. EXCHANGE RATES
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.exchange_rates (
    asset TEXT PRIMARY KEY,
    rate_inr NUMERIC NOT NULL,
    source TEXT NOT NULL DEFAULT 'coingecko',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.exchange_rates ENABLE ROW LEVEL SECURITY;

-- Anyone can read rates
CREATE POLICY "exchange_rates_public_read" ON public.exchange_rates
    FOR SELECT USING (TRUE);

-- Service role has full write access
CREATE POLICY "exchange_rates_service_all" ON public.exchange_rates
    FOR ALL USING (auth.role() = 'service_role');

-- Enable realtime for exchange_rates
ALTER PUBLICATION supabase_realtime ADD TABLE public.exchange_rates;


-- ─────────────────────────────────────────────
-- 7. ADMIN LOG (Append-Only Audit Trail)
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.admin_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_username TEXT NOT NULL,
    action TEXT NOT NULL,
    target_id UUID,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.admin_log ENABLE ROW LEVEL SECURITY;

-- Service role only — no user access
CREATE POLICY "admin_log_service_only" ON public.admin_log
    FOR ALL USING (auth.role() = 'service_role');

CREATE INDEX IF NOT EXISTS idx_admin_log_created ON public.admin_log(created_at DESC);
