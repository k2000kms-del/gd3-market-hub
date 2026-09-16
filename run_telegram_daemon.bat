@echo off
chcp 65001 > NUL
echo ========================================================
echo   🤖 GD3 Market Hub — 텔레그램 스마트 비서 상시 구동 데몬
echo   (대표님의 /포트, /추천, /시장 명령어 및 버튼 0.5초 즉각 응답)
echo   (외부 채널 엘리트강사/트레이딩스핀 60초 긴급 속보 실시간 감시)
echo ========================================================
cd /d "%~dp0"
set PYTHONUTF8=1
uv run python telegram_bot_daemon.py
pause
