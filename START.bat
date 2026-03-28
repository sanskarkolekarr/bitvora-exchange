@echo off
TITLE BITVORA — START
COLOR 0B

echo.
echo ==========================================
echo   BITVORA EXCHANGE — Starting Platform
echo ==========================================
echo.

echo [1/2] Starting API + Worker (FastAPI)...
start "BITVORA_API" cmd /k "cd /d "%~dp0backend" && ..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"

echo [2/2] Serving Frontend...
start "BITVORA_FRONTEND" cmd /k "cd /d "%~dp0" && .\.venv\Scripts\python.exe -m http.server 3000 --bind 127.0.0.1"

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
