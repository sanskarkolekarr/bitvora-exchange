@echo off
TITLE BITVORA — START
COLOR 0B

echo.
echo ==========================================
echo   BITVORA EXCHANGE — Starting Platform
echo ==========================================
echo.

echo [1/3] Starting Infrastructure (Redis)...
docker start bitvora-redis >nul 2>&1
if errorlevel 1 (
    echo   [-] Redis container not found, creating new one...
    docker run -d --name bitvora-redis -p 6379:6379 redis:7-alpine >nul
) else (
    echo   [+] Redis started.
)

echo [2/3] Starting API + Worker (FastAPI)...
start "BITVORA_API" cmd /k "cd /d "%~dp0backend" && ..\.venv\Scripts\python.exe -m uvicorn app.main:app --host :: --reload --port 8000"

echo [3/4] Serving Frontend...
start "BITVORA_FRONTEND" cmd /k "cd /d "%~dp0" && .\.venv\Scripts\python.exe serve_frontend.py 3000 --bind 127.0.0.1"

echo [4/4] Activating Cloudflare Secure Tunnel...
start "BITVORA_TUNNEL" cmd /k "cloudflared tunnel run --token eyJhIjoiNzBhOWExZjA4M2ZiNjk3MTI4MmE0ZTQ1OTY0NjI3MWQiLCJ0IjoiNWYyNGQ5MzQtYTczYS00YjEyLWI1YjktMTlhZjQ3NzIxMmQwIiwicyI6Ik1XTTVZVFl3TmpRdFptUXlaUzAwTldFMUxXSXhPVFF0TkRZeU5XRTRaV1k0WWpobSJ9"

echo.
echo ==========================================
echo   ALL SERVICES STARTED
echo ==========================================
echo.
echo   API Docs  : http://localhost:8000/docs
echo   Frontend  : http://localhost:3000/pages/index.html
echo.
echo ==========================================
echo Press any key to close this window.
pause > nul
