# GD3 Market Hub 프로젝트 규칙 및 가이드라인

## 1. 사용자 필수 규칙 (절대 준수)
- **모든 대답과 주석은 반드시 '한국어'로 작성할 것.**
- **새로운 라이브러리나 패키지를 설치할 때는 반드시 미리 허락을 구할 것.**
- **코드를 수정할 때는 기존의 코드 스타일을 무조건 유지할 것.**

---

## 2. 프로젝트 아키텍처 개요
본 프로젝트는 국내 주식 시장 실시간 감시, 퀀트 분석, AI 브리핑 및 텔레그램 알림 시스템을 제공하는 올인원 트레이딩 허브입니다.

- **메인 Streamlit 대시보드**: pp.py (및 배포 미러 streamlit_app/app.py)
- **텔레그램 알림 데몬**: 	elegram_bot_daemon.py
- **텔레그램 알림/통신 엔진**: 	elegram_notifier.py
- **차트 생성기**: chart_image_generator.py
- **포트폴리오 데이터**: data/my_portfolio.json
- **시장/퀀트 데이터**: data/df_full_market.csv, data/df_quant_final.csv, data/df_high_density.csv

---

## 3. 핵심 개발 및 데이터 원칙
1. **네이버 실시간 시세 1순위 적용**:
   - 대시보드(포트폴리오, 퀀트 TOP10, 수급 TOP10, 개별종목 분석)와 텔레그램 봇의 모든 종목 가격 표시는 	elegram_notifier.py의 etch_realtime_stock_info(code)를 1순위로 조회하여 네이버 실시간 체결가/종가를 반영합니다.
   - 장중/장외/주말 불문하고 항상 네이버 실시간 API가 우선이며, CSV는 최후의 폴백으로만 사용합니다.
2. **배포 동기화 규칙**:
   - pp.py를 수정할 때는 반드시 streamlit_app/app.py에도 동일하게 복사하여 동기화합니다.
   - 	elegram_notifier.py 수정 시에도 streamlit_app/telegram_notifier.py에 동기화합니다.
3. **텔레그램 봇 상시 응답 (24/7)**:
   - 사용자의 원터치 버튼 명령(내포트폴리오, 퀀트top3추천, 시장에너지진단 등)은 야간 및 주말에도 차단되지 않고 orce_send=True로 즉시 응답해야 합니다.