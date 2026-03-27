-- ==========================================================
-- BITVORA EXCHANGE — 7-Chains Cleanup Migration
-- Run this in your Supabase SQL Editor to clean up DB state
-- ==========================================================

-- 1. Remove deprecated chains from deposit_addresses
DELETE FROM public.deposit_addresses
WHERE chain IN ('polygon', 'arbitrum', 'avalanche', 'xrp', 'dogecoin');

-- 2. Remove deprecated assets from exchange_rates
DELETE FROM public.exchange_rates
WHERE asset IN ('MATIC', 'AVAX', 'ARB', 'XRP', 'DOGE');

-- Verification query (Optional)
-- SELECT * FROM public.deposit_addresses;
-- SELECT * FROM public.exchange_rates;
