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
            # 퀀트 데이터 로드
            q_path = os.path.join(base_dir, 'data', 'df_quant_final.csv')
            top_names = []
            if os.path.exists(q_path):
                df_q_tmp = pd.read_csv(q_path)
                if not df_q_tmp.empty and 'Name' in df_q_tmp.columns:
                    top_names = df_q_tmp.head(4)['Name'].tolist()

            # 시장 요약 로드
            sum_path = os.path.join(base_dir, 'data', 'df_market_summary.csv')
            regime = "상승/횡보 국면"
            c_rat, s_rat = 20.0, 80.0
            b_ma5, b_st = 3.5, "안정"
            if os.path.exists(sum_path):
                df_s_tmp = pd.read_csv(sum_path)
                if not df_s_tmp.empty:
                    # 코스피 등락률 기반 국면 판단
                    ks_row = df_s_tmp[df_s_tmp.iloc[:, 0].astype(str).str.contains('코스피')]
                    if not ks_row.empty:
                        chg_str = str(ks_row.iloc[0].get('등락률', '0')).replace('%', '').replace('+', '').strip()
                        try:
                            chg_val = float(chg_str)
                            if chg_val < -0.5:
                                regime = "약세/보수 국면"
                                c_rat, s_rat = 70.0, 30.0
                        except Exception:
                            pass

            res = tn.notify_morning_briefing(
                token=token, chat_id=chat_id,
                market_regime=regime, cash_ratio=c_rat, stock_ratio=s_rat,
                bollinger_ma5=b_ma5, bollinger_status=b_st,
                top_quant_names=top_names
            )
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
            # 포트폴리오 및 시세 로드하여 총 평가금액/손익 계산
            port_path = os.path.join(base_dir, 'data', 'my_portfolio.json')
            m_path = os.path.join(base_dir, 'data', 'df_full_market.csv')
            tot_eval = 0.0
            tot_entry = 0.0
            port_count = 0
            if os.path.exists(port_path):
                with open(port_path, 'r', encoding='utf-8') as f:
                    port_data = json.load(f)
                port_count = len(port_data)
                df_m_tmp = pd.read_csv(m_path) if os.path.exists(m_path) else pd.DataFrame()
                
                for pk, pv in port_data.items():
                    ep = float(pv.get('entry_price', 0))
                    qty = float(pv.get('qty', 0))
                    tot_entry += ep * qty
                    cur_p = ep
                    if not df_m_tmp.empty and 'Code' in df_m_tmp.columns:
                        m_row = df_m_tmp[df_m_tmp['Code'].astype(str).str.zfill(6) == str(pk).zfill(6)]
                        if not m_row.empty:
                            cur_p = float(m_row.iloc[0].get('Close', ep))
                    tot_eval += cur_p * qty

            # 시장 수급 및 선물 동향 추출
            sum_path = os.path.join(base_dir, 'data', 'df_market_summary.csv')
            mkt_lines = []
            fut_text = "외국인 장 후반 선물 관망세 유지"
            if os.path.exists(sum_path):
                df_s_tmp = pd.read_csv(sum_path)
                if not df_s_tmp.empty:
                    for _, row in df_s_tmp.iterrows():
                        name = str(row.iloc[0])
                        idx_val = str(row.get('지수', ''))
                        chg_val = str(row.get('등락률', ''))
                        f_net = str(row.get('외국인(억)', '-'))
                        p_net = str(row.get('개인(억)', '-'))
                        i_net = str(row.get('기관(억)', '-'))
                        if '코스피' in name or '코스닥' in name:
                            mkt_lines.append(f"├ <b>{name}</b>: {idx_val} ({chg_val}) | 외인 {f_net}억, 기관 {i_net}억, 개인 {p_net}억")
                        elif '선물' in name or '나스닥' in name or 'USD' in name:
                            fut_text = f"├ <b>{name}</b>: {idx_val} ({chg_val})\n└ 💡 외국인 선물 수급과 환율 변동성이 내일 시초가에 직결됩니다."
            mkt_text = "\n".join(mkt_lines) if mkt_lines else "코스피/코스닥 정규장 마감 완료"

            # 주도 섹터 추출 (거래대금 상위 및 상승률 상위 기반)
            sec_text = "반도체/AI 및 2차전지/바이오 순환매 지속"
            hd_path = os.path.join(base_dir, 'data', 'df_high_density.csv')
            if os.path.exists(hd_path):
                df_hd_tmp = pd.read_csv(hd_path)
                if not df_hd_tmp.empty and 'Name' in df_hd_tmp.columns:
                    top_lead = df_hd_tmp.head(4)['Name'].tolist()
                    sec_text = f"├ <b>수급 집중 주도주</b>: {', '.join(top_lead)}\n└ 💡 주도주 중심 자금 쏠림 현상 심화 (개별 테마주 선별 대응 필요)"

            # 내일 대응 전략
            strat_text = (
                "📈 <b>[갭상승 출발 시]</b>: 09:00~09:15 갭 함정 주의! 시초가 추격매수 금지, 보유 수익 종목 50% 분할 익절 후 눌림목 지지 확인\n"
                "📉 <b>[갭하락 출발 시]</b>: 시초가 패닉 투매 절대 금지! 20일선 지지력 확인 후 09:30 이후 외인 수급 전환 시 분할 매수\n"
                "⚖️ <b>[보합/혼조 출발 시]</b>: 지수 방향성보다 외국인/기관 순매수 유입 퀀트 TOP3 주도주 위주로 압축 매매"
            )

            r1 = tn.notify_closing_briefing(
                token=token, chat_id=chat_id,
                total_eval=tot_eval, total_pnl=tot_pnl, total_pct=tot_pct,
                port_count=port_count,
                market_summary_text=mkt_text,
                foreign_futures_text=fut_text,
                leading_sectors_text=sec_text,
                tomorrow_strategy_text=strat_text
            )
            r2 = tn.notify_quant_top_pick(token=token, chat_id=chat_id)
            print(f"  ✅ 프리미엄 장마감 브리핑 및 퀀트 추천 발송 완료 (r1={r1}, r2={r2})")
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
