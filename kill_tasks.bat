@echo off
TITLE BITVORA CLEANUP — SYSTEM RESET
COLOR 0C

echo  ==============================================================
echo      BITVORA CLEANUP — System Reset
echo  ==============================================================
echo.

:: 1. Force kill python/uvicorn
echo  [1/2] Terminating all Python processes...
taskkill /F /IM python.exe /T 2>nul
taskkill /F /IM uvicorn.exe /T 2>nul
echo       ^> Python & Uvicorn terminated.

:: 2. Cleanup Docker 
echo  [2/2] Cleaning Infrastructure Containers...
docker stop bitvora-redis 2>nul
echo       ^> Infrastructure reset.

echo.
echo  ==============================================================
echo      BITVORA INFRASTRUCTURE RESET COMPLETE
echo  ==============================================================
echo.
echo    All ports (3000, 8000) should now be free.
echo    Redis container has been stopped safely.
echo.
echo  ==============================================================
echo  Press any key to close this script.
pause > nul
