@echo off
chcp 65001 > NUL
echo ========================================================
echo   🌟 [우선순위 1위 메인 앱] GD3 Market Hub — Streamlit
echo   접속 주소: http://localhost:8501 (외부/태블릿: http://180.230.74.56:8501)
echo ========================================================
cd /d "%~dp0streamlit_app"
set PYTHONUTF8=1
"..\\.venv\\Scripts\\python.exe" -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0
pause
