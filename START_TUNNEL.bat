@echo off
TITLE BITVORA — CLOUDFLARE TUNNEL
COLOR 0D

echo ==========================================
echo Starting Cloudflare Tunnel...
echo ==========================================
echo.   
cloudflared tunnel run --token eyJhIjoiNzBhOWExZjA4M2ZiNjk3MTI4MmE0ZTQ1OTY0NjI3MWQiLCJ0IjoiNWYyNGQ5MzQtYTczYS00YjEyLWI1YjktMTlhZjQ3NzIxMmQwIiwicyI6Ik1XTTVZVFl3TmpRdFptUXlaUzAwTldFMUxXSXhPVFF0TkRZeU5XRTRaV1k0WWpobSJ9
pause > nul
