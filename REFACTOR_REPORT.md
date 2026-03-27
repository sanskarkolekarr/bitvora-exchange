# BITVORA EXCHANGE — Refactor Report

> Audit performed: 2026-03-25 | Zero code changes in this step — report only.

---

## HTML Duplication

| ID | Category | File(s) | Lines | Description |
|----|----------|---------|-------|-------------|
| H1 | DUPLICATE | All 12 HTML pages | ~30 lines each | `tailwind.config = { ... }` block copied identically in every page `<head>` |
| H2 | DUPLICATE | All 12 HTML pages | ~1 line each | `<div class="noise-overlay"></div>` hardcoded in every page body |
| H3 | DUPLICATE | All 12 HTML pages | ~1 line each | `<div class="custom-cursor hidden md:block" id="cursor"></div>` in every page |
| H4 | DUPLICATE | 11 pages (not signin) | ~25 lines each | Navbar `<nav id="navbar" class="navbar-pill ...">` with links, duplicated with slight style variations per page |
| H5 | DUPLICATE | 11 pages | ~30 lines each | Footer HTML block with links and copyright, duplicated across pages |
| H6 | DUPLICATE | 3 pages (index, how-it-works, why-us) | ~15 lines each | Navbar scroll observer (`navbar.classList.add('loaded'/'scrolled')`) duplicated inline |
| H7 | DEAD CODE | `pages/howitworks.html` (27KB) | entire file | Older version of `how-it-works.html` (62KB) — same page, different design. One is dead. |
| H8 | DEAD CODE | `pages/whyus.html` (29KB) | entire file | Older version of `why-us.html` (110KB) — same page, different design. One is dead. |
| H9 | DUPLICATE | `pages/index.html` | tag set | Google Fonts `<link>` tags duplicated in every page head |
| H10 | DUPLICATE | `pages/index.html` | tag set | Material Symbols Outlined `<link>` tag duplicated in every page head |

---

## JavaScript Duplication

| ID | Category | File(s) | Lines | Description |
|----|----------|---------|-------|-------------|
| J1 | CONSOLIDATE | `api.js` | 8–21, 143–165 | `getCurrentUser()` and `requireAuth()` already exist in `api.js` — good. But session check in `whyus.html:344` duplicates this inline. |
| J2 | CONSOLIDATE | `whyus.html` inline `<script>` | ~10 lines | Inline `localStorage.getItem('bitvora_session')` + navbar user injection duplicates logic from `api.js:getCurrentUser()` |
| J3 | SIMPLIFY | `platform.js` | full file | 17KB utility file — needs audit for dead functions vs. actually-called code |
| J4 | CONSOLIDATE | Various HTML inline scripts | scattered | Cursor follow JS (mousemove listeners for `#cursor`) likely duplicated inline in pages that have the cursor div |

---

## Python Duplication

| ID | Category | File(s) | Lines | Description |
|----|----------|---------|-------|-------------|
| P1 | DUPLICATE | `chains/evm.py:19`, `tron.py:16`, `solana.py:16`, `bitcoin.py:16`, `ton.py:16` | 7 lines each | `class VerificationResult` dataclass defined identically in all 5 chain verifier files — should be in a shared `models/verification.py` |
| P2 | REDUNDANT | `routes/transaction.py:31,137,174`, `routes/admin.py:184` | 1 line each | `chain.lower()` called inline in 4 places — extract `normalize_chain()` |
| P3 | REDUNDANT | `routes/transaction.py:33,81`, `utils/txid_ledger.py:15,23,37` | 1 line each | `txid.strip().lower()` in 5 places — extract `normalize_txid()` |
| P4 | REDUNDANT | `routes/admin.py:296,359,407,428` | 1 line each | `from datetime import datetime` imported inline inside function bodies 4 times — already imported at file top (line 8) |
| P5 | CONSOLIDATE | `routes/admin.py:26-36` vs `admin.py:302-309` | ~10 lines each | Two different admin log mechanisms: `_log_action()` → `admin_log` table, and inline dict → `admin_logs` table (different tables!) |
| P6 | SIMPLIFY | `routes/transaction.py:106-115` vs `routes/transaction.py:155-158` | ~8 lines each | Fee calculation `fee_pct = 0.015; gross = amount * rate; fee = gross * fee_pct; net = gross - fee` duplicated in `submit` and `quote` |
| P7 | SIMPLIFY | `utils/security.py:25,35` | 2 lines | `db = get_supabase()` called twice in `get_current_user()` — second call is redundant, same client |

---

## CSS Duplication

| ID | Category | File(s) | Lines | Description |
|----|----------|---------|-------|-------------|
| C1 | CONSOLIDATE | `styles.css` + `profile-card.css` | various | Need to check for overlapping selectors between the two files |
| C2 | CONSOLIDATE | `styles.css` | scattered | Multiple `@media (max-width: 768px)` blocks spread throughout the file — should be merged into a single block at bottom |

---

## Config Duplication

| ID | Category | File(s) | Lines | Description |
|----|----------|---------|-------|-------------|
| K1 | CONSOLIDATE | Frontend inline JS (submit.html) | ~20 lines | Chain-to-token mapping may be hardcoded in frontend — should fetch from `GET /assets/chains` API |

---

## File/Folder Cleanup

| ID | Category | Path | Description |
|----|----------|------|-------------|
| F1 | DEAD CODE | `pages/howitworks.html` | Older version — superseded by `how-it-works.html` |
| F2 | DEAD CODE | `pages/whyus.html` | Older version — superseded by `why-us.html` |
| F3 | DEAD CODE | `backend/routes/__pycache__/` | Compiled Python cache committed to workspace |
| F4 | DEAD CODE | `backend/utils/__pycache__/` | Compiled Python cache committed to workspace |
| F5 | SIMPLIFY | Project root | Missing `.gitignore` at project root |
| F6 | DEAD CODE | `scripts/rename_brand.ps1` | One-time migration script — already deleted |

---

## Summary

| Category | Count |
|----------|-------|
| DUPLICATE | 16 |
| DEAD CODE | 6 |
| REDUNDANT | 4 |
| SIMPLIFY | 4 |
| CONSOLIDATE | 6 |
| **Total** | **36** |

---

## VERIFICATION RESULTS

> To be populated after Step 8.
