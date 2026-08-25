@echo off
chcp 65001 > nul
title GD 3.0 Market Hub - 대시보드 및 텔레그램 봇 실행기

echo ================================================================
echo  [GD 3.0 Market Hub] 대시보드 및 텔레그램 봇을 시작합니다...
echo ================================================================
echo.

cd /d "C:\Users\김실근\.gemini\antigravity\scratch\gd3_market_hub"

set "PYTHONUTF8=1"
set "PY_EXE=C:\Users\김실근\.gemini\antigravity\scratch\gd3_market_hub\.venv\Scripts\python.exe"
set "ST_EXE=C:\Users\김실근\.gemini\antigravity\scratch\gd3_market_hub\.venv\Scripts\streamlit.exe"

echo [1/3] 기존 프로세스 점검 중...
powershell -Command "Get-Process -Name streamlit, python -ErrorAction SilentlyContinue | Where-Object { .CommandLine -like '*gd3_market_hub*' -or .CommandLine -like '*streamlit_app*' } | Stop-Process -Force -ErrorAction SilentlyContinue" > nul 2>&1
timeout /t 1 /nobreak > nul

echo [2/3] 24시간 독립형 텔레그램 봇 데몬 가동 중...
start /b "" "%PY_EXE%" "C:\Users\김실근\.gemini\antigravity\scratch\gd3_market_hub\telegram_bot_daemon.py" > nul 2>&1

echo [3/3] Streamlit 대시보드 웹 서버 실행 및 브라우저 열기...
echo.
echo  * 대시보드 주소: http://localhost:8501
echo  * 이 창을 띄워두시면 실시간 시세와 텔레그램 알림이 작동합니다.
echo ================================================================
echo.

start http://localhost:8501
"%ST_EXE%" run "C:\Users\김실근\.gemini\antigravity\scratch\gd3_market_hub\streamlit_app\app.py" --server.port 8501 --server.headless false

pause
