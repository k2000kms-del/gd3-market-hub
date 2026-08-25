@echo off
chcp 65001 > NUL
echo ========================================================
echo   ⚡ GD3 Market Hub — Fast Web 대시보드 (http://localhost:8000)
echo ========================================================
cd /d "%~dp0fast_web_dashboard"
set PYTHONUTF8=1
"..\\.venv\\Scripts\\python.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
pause
