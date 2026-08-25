# 📂 GD3 Market Hub — 프로젝트 분리 안내

본 디렉토리는 사용자 요구사항에 따라 **기존 Streamlit 앱**과 **신규 Fast Web 대시보드** 2개의 독립 프로젝트로 완전히 구조화 분리되었습니다.

---

## 1. ⚡ 프로젝트 A: Fast Web 대시보드 (권장 - 0.01초 속도)
* **폴더 위치**: `fast_web_dashboard/`
* **기술 스택**: FastAPI + Plotly.js + Vanilla Web UI
* **접속 주소**: `http://localhost:8000` (외부/태블릿: `http://180.230.74.56:8000`)
* **특징**: 
  - 0.01초 반응 속도, 화면 깜빡임 0%, 5개 핵심 탭
  - 뉴스 아래 볼린저 밴드(20,2) 시장 에너지 카드 & 콤보 차트 통합
  - 포트폴리오 자산 총괄 요약바 및 1600px 꽉 찬 밀도
* **실행 방법**:
  - `run_fast_web.bat` 더블 클릭
  - 또는 파워셸에서:
    ```powershell
    cd fast_web_dashboard
    $env:PYTHONUTF8="1"; ..\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
    ```

---

## 2. 🐢 프로젝트 B: 레거시 Streamlit 앱 (기존 백업 버전)
* **폴더 위치**: `streamlit_app/`
* **기술 스택**: Python Streamlit Monolithic
* **접속 주소**: `http://localhost:8501`
* **특징**:
  - 기존 5,400줄 모놀리식 단일 파일 구조
  - 뉴스 하단에 동일한 볼린저 밴드 지표 카드 백업 통합 완료
* **실행 방법**:
  - `run_streamlit.bat` 더블 클릭
  - 또는 파워셸에서:
    ```powershell
    cd streamlit_app
    $env:PYTHONUTF8="1"; ..\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8501
    ```
