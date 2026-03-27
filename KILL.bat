@echo off
TITLE BITVORA — KILL ALL
COLOR 0C

echo.
echo ==========================================
echo   BITVORA EXCHANGE — Killing All Services
echo ==========================================
echo.

echo Terminating all Python processes...
taskkill /F /IM python.exe /T 2>nul
taskkill /F /IM python3.exe /T 2>nul

echo Closing any open BITVORA windows...
taskkill /F /FI "WINDOWTITLE eq BITVORA*" 2>nul

echo.
echo ==========================================
echo   ALL PROCESSES KILLED
echo ==========================================
echo   Ports 8000 and 3000 are now free.
echo   Run START.bat to restart.
echo ==========================================
echo Press any key to close this window.
pause > nul
