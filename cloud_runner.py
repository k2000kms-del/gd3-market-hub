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

# KST 타임존
KST = timezone(timedelta(hours=9))
now_kst = datetime.now(KST)
now_hm = now_kst.hour * 100 + now_kst.minute
now_weekday = now_kst.weekday()  # 0=월, 4=금, 5=토, 6=일

print(f"🚀 [Cloud Runner] 실행 시작: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} KST")

# 1. 텔레그램 환경변수 확인
token = os.environ.get("TELEGRAM_BOT_TOKEN")
chat_id = os.environ.get("TELEGRAM_CHAT_ID")

import telegram_notifier as tn

# 2. 장전 브리핑 (08:40 ~ 08:59 KST)
if now_weekday < 5 and 840 <= now_hm <= 859:
    print("☀️ 장전 브리핑 발송 시도...")
    try:
        tn.notify_morning_briefing(token=token, chat_id=chat_id)
        print("  ✅ 장전 브리핑 발송 완료")
    except Exception as e:
        print(f"  ❌ 장전 브리핑 오류: {e}")

# 3. 장마감 브리핑 (15:35 ~ 16:10 KST)
if now_weekday < 5 and 1535 <= now_hm <= 1610:
    print("🌙 장마감 브리핑 발송 시도...")
    try:
        tn.notify_closing_briefing(token=token, chat_id=chat_id)
        tn.notify_quant_top_pick(token=token, chat_id=chat_id)
        print("  ✅ 장마감 브리핑 및 퀀트 추천 발송 완료")
    except Exception as e:
        print(f"  ❌ 장마감 브리핑 오류: {e}")

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
