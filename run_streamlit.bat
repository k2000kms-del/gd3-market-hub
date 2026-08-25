@echo off
chcp 65001 > NUL
echo ========================================================
echo   🐢 GD3 Market Hub — Streamlit 앱 (http://localhost:8501)
echo ========================================================
cd /d "%~dp0streamlit_app"
set PYTHONUTF8=1
"..\\.venv\\Scripts\\python.exe" -m streamlit run app.py --server.port 8501
pause
