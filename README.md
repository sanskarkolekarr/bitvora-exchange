# 💎 BITVORA EXCHANGE
**High-Performance Crypto-to-Fiat Exchange Engine**

Bitvora is a production-grade cryptocurrency exchange platform featuring real-time transaction verification, premium OLED aesthetics, and automated payout logic.

## 🚀 Key Features
- **High-Concurrency Verification**: Parallel multi-RPC racing for sub-second blockchain confirmation detection.
- **Deep Log Decoding**: Advanced ERC20/TRC20 transfer scanning, supporting Account Abstraction (AA) and DEX-routed payments.
- **Modern UI/UX**: Mobile-first, OLED-optimized premium design with custom animations (ScrollStack, Aurora effects).
- **Security-First Backend**: Built with FastAPI, featuring rate-limiting, Cloudflare tunnel integration, and strict anti-fraud timing validation.

## 🏗️ Technical Stack
- **Backend**: Python 3.11+, FastAPI, PostgreSQL (Supabase), Redis, HTTPX.
- **Frontend**: Vanilla HTML5/CSS3, JavaScript (ES6+), TailwindCSS.
- **Workers**: Asynchronous background workers for chain watching, price management, and Telegram alerts.

## 📂 Project Structure
- `/backend`: API server and Blockchain verification engine.
- `/assets`: Static assets, animations, and client-side logic.
- `/pages`: Responsive HTML templates.
- `/scripts`: Deployment and maintenance utilities.
- `/admin`: Admin dashboard for platform management.

## ⚙️ Setup
1. **Backend**: 
   - `cd backend`
   - `pip install -r requirements.txt`
   - Configure `.env` based on `.env.example`.
   - Start via `python main.py` or `START.bat`.
2. **Workers**:
   - Start verification workers via `python worker_main.py`.
3. **Frontend**:
   - Served via the `pages/` directory (static).
   - Configure `assets/js/config.js` for API endpoints.

---
*Created by [Antigravity](https://google.com) — Engineering the future of exchange.*
