@echo off
TITLE BITVORA — KILL ALL
COLOR 0C

echo.
echo ==========================================
echo   BITVORA EXCHANGE — Killing All Services
echo ==========================================
echo.

echo [1/3] Terminating all Python processes...
taskkill /F /IM python.exe /T 2>nul
taskkill /F /IM python3.exe /T 2>nul
taskkill /F /IM uvicorn.exe /T 2>nul
taskkill /F /IM cloudflared.exe /T 2>nul

echo [2/3] Closing any open BITVORA windows...
taskkill /F /FI "WINDOWTITLE eq BITVORA*" 2>nul

echo [3/3] Stopping Infrastructure Containers...
docker stop bitvora-redis 2>nul

echo.
echo ==========================================
echo   ALL PROCESSES KILLED
echo ==========================================
echo   Ports 8000 and 3000 are now free.
echo   Redis container stopped safely.
echo   Run START.bat to restart.
echo ==========================================
echo Press any key to close this window.
pause > nul
