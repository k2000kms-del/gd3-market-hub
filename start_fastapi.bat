@echo off
chcp 65001 > nul
echo =======================================================
echo  GD3 Market Hub — FastAPI 웹 서버 실행 (포트: 8000)
echo =======================================================
echo.
set PYTHONUTF8=1

if exist .\.venv\Scripts\python.exe (
    .\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
) else (
    python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
)

pause
