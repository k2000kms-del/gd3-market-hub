# GD3 Market Hub (AI 트레이딩 & 실시간 시장 대시보드)

이 문서는 Antigravity 에이전트가 본 프로젝트를 완벽히 이해하고 유지보수할 수 있도록 작성된 프로젝트 지침서입니다.

## 1. 프로젝트 주요 기능
1. **Streamlit 인터랙티브 대시보드 (pp.py)**:
   - 실시간 시장 지수 및 볼린저 밴드 에너지 진단
   - Panel 1: 외국인/기관 실시간 수급 포착 (Diverging Bar Chart)
   - Panel 2: 보정 Quant Buy TOP 10 랭킹 (불트랩 페널티 적용)
   - Panel 3: 개별 종목 심층 캔들 차트, 세력 수급 가속도, 스마트 매매 판정
   - Panel 4: 포트폴리오 관리 테이블 (24시간 네이버 실시간 체결가/수익률 계산)
   - Panel 5: Gemini AI 비동기 맞춤 종목 브리핑
2. **텔레그램 알림 시스템 (	elegram_notifier.py, 	elegram_bot_daemon.py)**:
   - 24시간 원터치 인라인 버튼: [내포트폴리오], [퀀트top3추천], [시장에너지진단]
   - 긴급 사이드카 / 서킷브레이커 / VI 발동 즉시 경보
   - 다중 텔레그램 채널 수신 정보 AI 교차 취합 및 중복 제거 브리핑
   - 모닝 브리핑 (08:30) 및 장마감 브리핑 (15:40)

## 2. 핵심 파일 구조
- pp.py: 메인 대시보드 (Streamlit 애플리케이션)
- streamlit_app/app.py: Streamlit Cloud 배포용 미러링 파일 (pp.py 수정 시 반드시 동기화)
- 	elegram_bot_daemon.py: 텔레그램 봇 폴링 및 채널 메시지 수집 데몬
- 	elegram_notifier.py: 메시지/차트 발송 엔진 및 네이버 실시간 시세 API (etch_realtime_stock_info)
- chart_image_generator.py: 텔레그램 발송용 캔들 차트 이미지 생성
- data/my_portfolio.json: 등록된 보유 종목 포트폴리오 (코드, 매수가, 수량 등)
- data/df_full_market.csv: 시장 전체 종목 스냅샷 데이터
- data/df_quant_final.csv: 퀀트 스코어 스냅샷 데이터

## 3. 실행 명령어
- **대시보드 실행**: uv run streamlit run app.py (또는 
un_dashboard.bat)
- **텔레그램 봇 데몬 실행**: uv run python telegram_bot_daemon.py (또는 
un_telegram_daemon.bat)

## 4. 사용자 규칙
- 모든 대화와 주석은 한국어로 작성.
- 패키지 설치 시 반드시 사전 동의 획득.
- 기존 코드 스타일 무조건 유지.
- 대시보드 및 봇의 가격 표시는 네이버 실시간 시세 API(etch_realtime_stock_info) 1순위 유지.