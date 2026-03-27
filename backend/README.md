# BITVORA EXCHANGE — Backend

Production-grade FastAPI backend for the BITVORA Exchange crypto-to-INR off-ramp platform. Three-layer architecture: Frontend → FastAPI → Supabase — with Cloudflare Tunnel as the public gateway.

---

## Architecture

```
┌──────────────────────────┐
│      FRONTEND (HTML)     │  ← Browser / pages/
│  Communicates ONLY with  │
│  Cloudflare domain       │
└───────────┬──────────────┘
            │ HTTPS (Cloudflare Tunnel)
            ▼
┌──────────────────────────┐
│   CLOUDFLARE TUNNEL      │  ← Public gateway
│   Rate limiting at edge  │
│   IP hidden, stack hidden│
└───────────┬──────────────┘
            │ localhost:8000
            ▼
┌──────────────────────────┐
│   FASTAPI (Layer 2)      │  ← This backend
│   JWT validation         │
│   Business rules         │
│   Service role key ONLY  │
│   Background workers     │
└───────────┬──────────────┘
            │ Service Role Key
            ▼
┌──────────────────────────┐
│   SUPABASE (Layer 3)     │  ← Database + Auth
│   RLS on every table     │
│   Realtime subscriptions │
└──────────────────────────┘
```

---

## Quick Start

### 1. Clone & Configure

```bash
cd backend/
cp .env.example .env
# Fill in all values in .env
```

### 2. Run Supabase Migration

Go to your Supabase project → SQL Editor → paste the contents of `supabase_migration.sql` → Run.

This creates all 7 tables with RLS policies, indexes, and Realtime publication.

### 3. Build & Run with Docker

```bash
docker-compose up -d --build
```

The backend starts on `127.0.0.1:8000` (localhost only — never publicly exposed).

### 4. Configure Cloudflare Tunnel

Point your Cloudflare Tunnel to `http://localhost:8000`. The tunnel handles TLS termination and routes all traffic from `api.bitvora.exchange` to the backend.

### 5. Set Frontend API URL

In your frontend JavaScript, set the API base URL to your Cloudflare domain:

```javascript
const API_BASE = "https://api.bitvora.exchange";
```

---

## Folder Structure

```
backend/
├── main.py                          # FastAPI entry point + lifespan workers
├── config.py                        # Pydantic Settings (typed .env loader)
├── database.py                      # Supabase client singleton
│
├── routes/
│   ├── auth.py                      # Register, login, logout, refresh
│   ├── transaction.py               # Submit, quote, deposit address
│   ├── status.py                    # Transaction status by reference
│   ├── assets.py                    # Chain info, exchange rates
│   └── admin.py                     # Payout queue, user mgmt, stats
│
├── services/
│   ├── price_manager.py             # CoinGecko rate fetcher + cache
│   ├── expiry.py                    # Transaction expiry worker
│   └── tx_verifier/
│       ├── verification_queue.py    # Polls pending → dispatches verifiers
│       ├── confirmation_tracker.py  # Re-checks 'verifying' confirmations
│       ├── lock_recovery.py         # Frees stuck locks
│       └── chains/
│           ├── evm.py               # ETH, BSC
│           ├── tron.py              # TRX, TRC20
│           ├── solana.py            # SOL, SPL
│           ├── bitcoin.py           # BTC
│           ├── litecoin.py          # LTC
│           └── ton.py               # TON, Jetton
│
├── models/
│   ├── transaction.py               # Request/response schemas
│   ├── user.py                      # Auth schemas
│   └── payout.py                    # Admin/payout schemas
│
├── utils/
│   ├── middleware.py                 # Cloudflare, RateLimit, Maintenance
│   ├── security.py                  # JWT verify, admin verify
│   └── txid_ledger.py               # Anti-double-processing
│
├── admin/
│   └── panel.py                     # (Reserved for admin panel UI)
│
├── supabase_migration.sql           # Full DB schema
├── requirements.txt                 # Python dependencies
├── Dockerfile                       # Production container
├── docker-compose.yml               # Service orchestration
├── .env.example                     # Environment variable template
└── README.md                        # This file
```

---

## Public RPC Endpoints & Rate Limits

| Chain     | RPC Endpoint                              | Rate Limit       |
|-----------|-------------------------------------------|------------------|
| Ethereum  | `https://eth.llamarpc.com`                | ~50 req/s        |
| BSC       | `https://bsc-dataseed.binance.org`        | ~10 req/s        |
| Tron      | `https://api.trongrid.io`                 | 15 req/s free    |
| Solana    | `https://api.mainnet-beta.solana.com`     | ~10 req/s        |
| TON       | `https://toncenter.com/api/v2`            | 1 req/s free     |
| Bitcoin   | `https://blockstream.info/api`            | ~10 req/s        |
| Litecoin  | `https://api.blockcypher.com/v1/ltc/main` | ~10 req/s        |

---

## Verification Flow

```
User submits TXID
       │
       ▼
[Pending] ──── Verification Queue (every 10s) ────►
       │                                            │
       │  If TX found + some confirmations          │
       ▼                                            │
[Verifying] ── Confirmation Tracker (every 25s) ──► │
       │                                            │
       │  If confirmations >= threshold             │
       ▼                                            │
[Verified] ──► Immediately advances to ──►          │
       │                                            │
       ▼                                            │
[Payout Queued] ──── Admin reviews in panel ────►   │
       │                                            │
       │  Admin clicks "Mark Paid"                  │
       ▼                                            │
[Payout Sent] ──── INR in user's bank ──── ✓ Done   │
                                                    │
[Expired] ◄──── Expiry Worker (every 60s) ──────────┘
                (if 30min window passes)
```

### Required Confirmations

| Chain     | Confirmations | Approx. Time |
|-----------|---------------|--------------|
| Ethereum  | 12            | ~2.5 min     |
| BSC       | 15            | ~45 sec      |
| Tron      | 19            | ~1 min       |
| Solana    | 1 (finalized) | ~instant     |
| TON       | 1 (finalized) | ~5 sec       |
| Bitcoin   | 2             | ~20 min      |
| Litecoin  | 3             | ~7.5 min     |

---

## Admin Workflow

1. **Login** with `ADMIN_SECRET_KEY` via Bearer token: `Authorization: Bearer <key>`
2. **View queue**: `GET /admin/payout-queue` — lists all verified transactions awaiting manual INR payout
3. **Process payout**: Manually send INR via IMPS/UPI to the destination shown
4. **Mark paid**: `POST /admin/mark-paid/{transaction_id}` — updates status, user stats, audit log
5. **Reject**: `POST /admin/reject/{transaction_id}` with reason — sets status to failed

Other admin routes:
- `GET /admin/transactions` — full transaction list with filters
- `GET /admin/users` — user management
- `POST /admin/ban/{user_id}` — suspend users
- `GET /admin/stats` — platform volume, fees, averages
- `POST /admin/maintenance/on|off` — toggle maintenance mode

---

## Security Highlights

- **Cloudflare-only access**: `CloudflareMiddleware` rejects all non-tunnel requests
- **JWT verification**: Every protected route validates Supabase JWTs
- **Ban checking**: Banned users are blocked at the dependency level
- **TXID normalization**: All TXIDs lowercased to prevent case-variation bypass
- **Amount tolerance**: 0.1% tolerance on amount comparisons (RPC floating point)
- **No enumeration**: Login returns identical errors for wrong username vs wrong password
- **Admin 404s**: Admin routes return 404 (not 403) to hide their existence
- **No stack traces**: Production errors return generic messages only
- **RLS everywhere**: All Supabase tables have Row Level Security as defense-in-depth
- **Docs disabled**: Swagger/ReDoc/OpenAPI endpoints are disabled in production
