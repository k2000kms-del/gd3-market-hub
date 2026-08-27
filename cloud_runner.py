# -*- coding: utf-8 -*-
"""
cloud_runner.py
---------------
PC가 꺼져 있어도 GitHub Actions 클라우드 환경에서 매 10분마다 자동 실행되어
1. 시장 데이터 및 10분 단위 일중 수급 수집 (4번 패널 실시간 적재)
2. 텔레그램 장전/장마감 브리핑 및 실시간 매수/매도/손절 신호 감시 푸시
를 100% 무인으로 수행하는 종합 클라우드 오케스트레이터입니다.
"""

import os
import sys
import json
import pandas as pd
from datetime import datetime, timezone, timedelta

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# KST 타임존
KST = timezone(timedelta(hours=9))
now_kst = datetime.now(KST)
now_hm = now_kst.hour * 100 + now_kst.minute
now_weekday = now_kst.weekday()  # 0=월, 4=금, 5=토, 6=일

today_str = now_kst.strftime('%Y%m%d')

print(f"🚀 [Cloud Runner] 실행 시작: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} KST (today={today_str}, hm={now_hm})")

# 1. 텔레그램 환경변수 및 secrets 확인
token = os.environ.get("TELEGRAM_BOT_TOKEN")
chat_id = os.environ.get("TELEGRAM_CHAT_ID")

base_dir = os.path.dirname(os.path.abspath(__file__))
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

import telegram_notifier as tn

# ── 브리핑 발송 상태 관리 (중복 방지 및 큐 지연 완벽 대응) ──
state_file = os.path.join(base_dir, 'data', 'last_briefing_state.json')
os.makedirs(os.path.dirname(state_file), exist_ok=True)
briefing_state = {}
if os.path.exists(state_file):
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            briefing_state = json.load(f)
    except Exception:
        briefing_state = {}

def _save_state():
    try:
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(briefing_state, f, ensure_ascii=False, indent=2)
    except Exception as err:
        print(f"DEBUG: 상태 파일 저장 실패: {err}")

# 2. 장전 브리핑 (08:00 ~ 09:30 KST 사이 최초 1회 무조건 발송)
last_morning = briefing_state.get('last_morning_date')
if now_weekday < 5 and 800 <= now_hm <= 930:
    if last_morning != today_str:
        print(f"☀️ 장전 브리핑 발송 시도 ({today_str})...")
        try:
            res = tn.notify_morning_briefing(token=token, chat_id=chat_id)
            print(f"  ✅ 장전 브리핑 발송 결과: {res}")
            briefing_state['last_morning_date'] = today_str
            _save_state()
        except Exception as e:
            print(f"  ❌ 장전 브리핑 오류: {e}")
    else:
        print(f"☀️ 오늘({today_str}) 장전 브리핑은 이미 발송 완료되었습니다.")

# 3. 장마감 브리핑 (15:30 ~ 18:30 KST 사이 최초 1회 무조건 발송)
last_closing = briefing_state.get('last_closing_date')
if now_weekday < 5 and 1530 <= now_hm <= 1830:
    if last_closing != today_str:
        print(f"🌙 장마감 브리핑 및 퀀트 TOP3 추천 발송 시도 ({today_str})...")
        try:
            r1 = tn.notify_closing_briefing(token=token, chat_id=chat_id)
            r2 = tn.notify_quant_top_pick(token=token, chat_id=chat_id)
            print(f"  ✅ 장마감 브리핑 및 퀀트 추천 발송 완료 (r1={r1}, r2={r2})")
            briefing_state['last_closing_date'] = today_str
            _save_state()
        except Exception as e:
            print(f"  ❌ 장마감 브리핑 오류: {e}")
    else:
        print(f"🌙 오늘({today_str}) 장마감 브리핑은 이미 발송 완료되었습니다.")

# 4. 장중 포트폴리오 실시간 감시 (09:00 ~ 15:30 KST)
if now_weekday < 5 and 900 <= now_hm <= 1530:
    print("📡 장중 실시간 포트폴리오 감시 스캔...")
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        port_path = os.path.join(base_dir, 'data', 'my_portfolio.json')
        if os.path.exists(port_path):
            with open(port_path, 'r', encoding='utf-8') as f:
                port = json.load(f)
            
            # quant 데이터 로드
            q_path = os.path.join(base_dir, 'data', 'df_quant_final.csv')
            df_q = pd.read_csv(q_path) if os.path.exists(q_path) else pd.DataFrame()
            
            # 각 보유 종목 점검
            if not df_q.empty and 'Code' in df_q.columns:
                df_q['Code'] = df_q['Code'].astype(str).str.zfill(6)
                for code, item in port.items():
                    c_str = str(code).zfill(6)
                    match = df_q[df_q['Code'] == c_str]
                    if not match.empty:
                        row = match.iloc[0]
                        c_price = float(row.get('Close', 0))
                        e_price = float(item.get('entry_price', 0))
                        stop_loss = float(item.get('stop_loss', 0)) if item.get('stop_loss') else e_price * 0.95
                        
                        # 손절선 이탈 감지
                        if c_price > 0 and c_price <= stop_loss:
                            tn.notify_daily_sell_signal(
                                code=c_str, name=item.get('name', c_str),
                                current_price=c_price, entry_price=e_price,
                                reason="🛑 손절선 이탈", signal_type="손절경고",
                                token=token, chat_id=chat_id
                            )
            print("  ✅ 장중 포트폴리오 스캔 완료")
    except Exception as e:
        print(f"  ❌ 장중 포트폴리오 스캔 오류: {e}")

print("🏁 [Cloud Runner] 완료")
