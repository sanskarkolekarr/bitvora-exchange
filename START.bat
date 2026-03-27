@echo off
TITLE BITVORA — START
COLOR 0B

echo.
echo ==========================================
echo   BITVORA EXCHANGE — Starting Platform
echo ==========================================
echo.

echo [1/3] Starting Worker (Verifier + Bot)...
start "BITVORA_WORKER" cmd /k "cd /d "%~dp0backend" && ..\.venv\Scripts\python.exe worker_main.py"

echo [2/3] Starting API (FastAPI)...
start "BITVORA_API" cmd /k "cd /d "%~dp0backend" && ..\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000"

echo [3/3] Serving Frontend...
start "BITVORA_FRONTEND" cmd /k "cd /d "%~dp0" && python -m http.server 3000"

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
