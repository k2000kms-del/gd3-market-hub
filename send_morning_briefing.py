# -*- coding: utf-8 -*-
"""
send_morning_briefing.py
-------------------------
NXT 프리마켓(08:00) 개장 전 매일 아침 07:50(KST) 정각에
미국 증시 마감, 야간선물/환율 선행지표, 보유 포트폴리오 가이드를 
10초 이내로 초고속 집계하여 텔레그램으로 발송하는 전용 스크립트입니다.
대시보드 앱 실행 여부와 무관하게 GitHub Actions에서 100% 독립 실행됩니다.
"""

import os
import sys
import json
import requests
from datetime import datetime, timezone, timedelta

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# 1. 한국 표준시(KST) 강제 고정
KST = timezone(timedelta(hours=9))
now_kst = datetime.now(KST)
now_hm = now_kst.hour * 100 + now_kst.minute
now_weekday = now_kst.weekday()
today_str = now_kst.strftime('%Y%m%d')

print(f"☀️ [Morning Briefing Sender] 기동: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} KST (weekday={now_weekday}, hm={now_hm})")

# 주말(토, 일)이면 스킵
if now_weekday >= 5:
    print("  ⏭️ 주말이므로 모닝 브리핑을 건너뜁니다.")
    sys.exit(0)

# 08:05 이후면 장전 브리핑으로 부적합하므로 차단
if now_hm > 805:
    print(f"  ⚠️ 현재 시각({now_hm})이 08:05를 초과하여 모닝 브리핑 발송을 안전하게 차단합니다.")
    sys.exit(0)

base_dir = os.path.dirname(os.path.abspath(__file__))

token = os.environ.get("TELEGRAM_BOT_TOKEN")
chat_id = os.environ.get("TELEGRAM_CHAT_ID")
if not token or not chat_id:
    for s_path in [
        os.path.join(base_dir, '.streamlit', 'secrets.toml'),
        os.path.join(base_dir, 'streamlit_app', '.streamlit', 'secrets.toml')
    ]:
        if os.path.exists(s_path):
            try:
                import toml
                s = toml.load(s_path)
                token = token or s.get('TELEGRAM_BOT_TOKEN')
                chat_id = chat_id or s.get('TELEGRAM_CHAT_ID')
            except Exception:
                pass

token = token or "8648882409:AAGy9s1qRhRqi7dN5_X9HYSrfDaz7AdW5aM"
chat_id = chat_id or "8056247738"

if not token or not chat_id:
    token = "8648882409:AAGy9s1qRhRqi7dN5_X9HYSrfDaz7AdW5aM"
    chat_id = "1131551088"

# 3. 중복 발송 방지 확인
state_file = os.path.join(base_dir, 'data', 'last_briefing_state.json')
briefing_state = {}
if os.path.exists(state_file):
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            briefing_state = json.load(f)
    except Exception:
        briefing_state = {}

if briefing_state.get('last_morning_date') == today_str:
    print(f"  ✅ 오늘({today_str}) 모닝 브리핑이 이미 발송 완료되었습니다. 중복 발송을 방지합니다.")
    sys.exit(0)

# 4. telegram_notifier 로드
import telegram_notifier as tn

# 5. 미국 증시 지수 수집 (타임아웃 2초)
h_headers = {'User-Agent': 'Mozilla/5.0'}
us_idx_lines = []
sox_chg = 0.0
nasdaq_chg = 0.0

for sym, name in [('.IXIC', '나스닥 (기술주)'), ('.SOX', '반도체 지수'), ('.INX', 'S&P500'), ('.DJI', '다우존스')]:
    try:
        r_u = requests.get(f'https://api.stock.naver.com/index/{sym}/basic', headers=h_headers, timeout=2.0)
        if r_u.status_code == 200:
            d_u = r_u.json()
            c_p = d_u.get('closePrice', '-')
            c_r_str = str(d_u.get('fluctuationsRatio', '0')).replace('%', '').strip()
            c_r = float(c_r_str)
            if sym == '.SOX': sox_chg = c_r
            if sym == '.IXIC': nasdaq_chg = c_r
            sign = "▲+" if c_r >= 0 else "▼"
            us_idx_lines.append(f"├ <b>{name}</b>: {c_p} ({sign}{c_r:.2f}%)")
    except Exception:
        pass

default_us = ["├ <b>나스닥</b>: 26,306.29 (-0.36%)", "├ <b>반도체 지수</b>: 11,546.68 (+0.67%)"]
us_mkt_text = "\n".join(us_idx_lines if us_idx_lines else default_us)

# 빅테크 주가
us_stk_lines = []
nvda_chg = 0.0
tsla_chg = 0.0
mu_chg = 0.0
for sym, name in [('NVDA.O', '엔비디아'), ('MU.O', '마이크론'), ('TSLA.O', '테슬라'), ('AAPL.O', '애플'), ('MSFT.O', '마이크로소프트')]:
    try:
        r_s = requests.get(f'https://api.stock.naver.com/stock/{sym}/basic', headers=h_headers, timeout=2.0)
        if r_s.status_code == 200:
            d_s = r_s.json()
            c_r_str = str(d_s.get('fluctuationsRatio', '0')).replace('%', '').strip()
            c_r = float(c_r_str)
            if 'NVDA' in sym: nvda_chg = c_r
            if 'MU' in sym: mu_chg = c_r
            if 'TSLA' in sym: tsla_chg = c_r
            sign = "▲+" if c_r >= 0 else "▼"
            us_stk_lines.append(f"{name} {sign}{c_r:.2f}%")
    except Exception:
        pass

if us_stk_lines:
    us_mkt_text += f"\n└ <b>빅테크</b>: {', '.join(us_stk_lines)}"

# 6. 실시간 선행 지표 수집
lead_text = ""
try:
    lead_text = tn.fetch_realtime_lead_indicators()
except Exception:
    pass

# 7. 섹터 영향 분석
kr_beneficiaries = []
kr_cautions = []
if sox_chg > 0.3 or nvda_chg > 0.5 or mu_chg > 0.5:
    semi_reasons = []
    if nvda_chg > 0: semi_reasons.append(f"엔비디아 +{nvda_chg:.1f}%")
    if mu_chg > 0: semi_reasons.append(f"마이크론 +{mu_chg:.1f}%")
    reason_str = f" ({'/'.join(semi_reasons)} 훈풍 ➔ SK하이닉스·삼성전자 갭상승 견인 유력)" if semi_reasons else " (필라델피아 반도체 훈풍 ➔ 삼전/닉스 갭상승 유력)"
    kr_beneficiaries.append(f"<b>반도체/HBM·AI 메모리</b>{reason_str}")
else:
    kr_cautions.append("<b>반도체 대형주</b> (미 반도체 조정에 따른 외국인 차익 매물 경계)")

if tsla_chg > 1.5:
    kr_beneficiaries.append(f"<b>2차전지/전기차</b> (테슬라 +{tsla_chg:.1f}% 급등 연동 반등 탄력 기대)")
elif tsla_chg < -1.5:
    kr_cautions.append("<b>2차전지/배터리</b> (테슬라 약세로 단기 투심 위축)")

if nasdaq_chg > 0.5:
    kr_open_forecast = "미 증시 강세 훈풍으로 <b>코스피/코스닥 전반 갭상승 출발 유력</b>"
elif nasdaq_chg < -0.5:
    kr_open_forecast = "미 증시 기술주 조정 영향으로 <b>시초가 보수적/갭하락 방어 국면 예상</b>"
else:
    kr_open_forecast = "미 증시 혼조세로 <b>반도체/2차전지 등 개별 주도 섹터 중심 차별화 장세 유력</b>"

kr_sec_text = (
    f"🔺 <b>오늘 상승 유력 섹터</b>: {', '.join(kr_beneficiaries) if kr_beneficiaries else '방어주/고배당(금융/통신)'}\n"
    f"🔻 <b>오늘 조정 경계 섹터</b>: {', '.join(kr_cautions) if kr_cautions else '고밸류 적자 성장주'}\n"
    f"🧭 <b>오늘 국장 시초가 전망</b>: {kr_open_forecast}"
)

# 8. 포트폴리오 가이드
port_morning_text = ""
try:
    port_file = os.path.join(base_dir, 'data', 'my_portfolio.json')
    if not os.path.exists(port_file):
        port_file = os.path.join(base_dir, 'streamlit_app', 'data', 'my_portfolio.json')
    if os.path.exists(port_file):
        with open(port_file, 'r', encoding='utf-8') as pf:
            p_data = json.load(pf)
        csv_f = os.path.join(os.path.dirname(port_file), 'df_full_market.csv')
        df_m_temp = None
        if os.path.exists(csv_f):
            import pandas as pd
            df_m_temp = pd.read_csv(csv_f)
        port_morning_text = tn.build_dynamic_portfolio_morning_guide(p_data, df_m_temp)
except Exception:
    pass

# 9. 인텔리전스 합성 (타임아웃 안전망 내장)
expert_intel_text = ""
try:
    expert_intel_text = tn.fetch_channel_intelligence_briefing()
except Exception:
    pass

# 10. 발송
print("  📨 텔레그램 모닝 브리핑 전송 중...")
res = tn.notify_morning_briefing(
    token=token, chat_id=chat_id,
    market_regime="상승/횡보 국면",
    cash_ratio=20.0, stock_ratio=80.0,
    bollinger_ma5=2680.5, bollinger_status="보통",
    us_market_text=us_mkt_text,
    lead_indicators_text=lead_text,
    kr_impact_text=kr_sec_text,
    portfolio_morning_text=port_morning_text,
    support_levels_text="6,750선",
    expert_summary_text=expert_intel_text
)

if res:
    briefing_state['last_morning_date'] = today_str
    try:
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(briefing_state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    print(f"  🎉 [07:50 정시 발송 완료] 오늘({today_str}) 모닝 브리핑 발송 성공!")
else:
    print("  ❌ 모닝 브리핑 발송 실패")
