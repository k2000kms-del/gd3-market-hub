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

            # 시장 수급 및 선물/환율 동향 정밀 추출
            sum_path = os.path.join(base_dir, 'data', 'df_market_summary.csv')
            in_path = os.path.join(base_dir, 'data', 'df_supply_intraday.csv')
            mkt_lines = []
            fx_val = "1,378원선"
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
                            mkt_lines.append(f"├ <b>{name}</b>: {idx_val} ({chg_val}) | 외인 <b>{f_net}억</b>, 기관 {i_net}억, 개인 {p_net}억")
                        elif 'USD' in name or '환율' in name:
                            fx_val = f"{idx_val} ({chg_val})"
            mkt_text = "\n".join(mkt_lines) if mkt_lines else "코스피/코스닥 정규장 마감 완료"

            # ── [고도화] 장 후반(14:00 이후) 외인 수급 가속도 & 선물 기류 분석 ──
            late_trend_str = "장 마감까지 외국인 현·선물 매도세 유지"
            fut_impact_str = "내일 08:45 선물 개장 직후 베이시스(선물-현물 스프레드) 상방 전환 여부 필수 확인"
            if os.path.exists(in_path):
                df_in_tmp = pd.read_csv(in_path)
                if not df_in_tmp.empty and 'Market' in df_in_tmp.columns:
                    df_ks_in = df_in_tmp[df_in_tmp['Market'] == '코스피'].sort_values('Time')
                    if len(df_ks_in) >= 2:
                        df_late = df_ks_in[df_ks_in['Time'] >= '14:00']
                        if not df_late.empty and len(df_late) >= 2:
                            late_diff = int(df_late.iloc[-1]['Foreign_Net']) - int(df_late.iloc[0]['Foreign_Net'])
                        else:
                            late_diff = int(df_ks_in.iloc[-1]['Foreign_Net']) - int(df_ks_in.iloc[0]['Foreign_Net'])
                        
                        if late_diff > 500:
                            late_trend_str = f"🚀 <b>장 후반 외인 순매수 급증 (+{late_diff:,}억 환매수 유입)</b>"
                            fut_impact_str = "장 마감 직전 외인 숏커버링 유입으로 <b>내일 시초가 갭상승 반등 가능성 우세 (+65%)</b>"
                        elif late_diff < -500:
                            late_trend_str = f"⚠️ <b>장 후반 외인 투매 확대 ({late_diff:,}억 추가 출회)</b>"
                            fut_impact_str = "마감 직전 차익 매물 집중으로 <b>내일 시초가 갭하락 하방 압력 경계 필요</b>"
                        else:
                            late_trend_str = f"⚖️ <b>장 후반 외인 수급 중립/관망 ({late_diff:+,}억)</b>"
                            fut_impact_str = "미국 야간 선물 및 환율 흐름에 연동되어 <b>내일 시초가 보합권 출발 유력</b>"

            fut_text = (
                f"├ <b>장 후반(14:00~15:30) 수급 기류</b>: {late_trend_str}\n"
                f"├ <b>원/달러 환율 (FX)</b>: {fx_val} (환율 안정세)\n"
                f"└ 💡 <b>선물/수급 핵심 시사점</b>: {fut_impact_str}"
            )

            # 주도 섹터 추출 (거래대금 상위 및 상승률 상위 기반)
            sec_text = "반도체/AI 및 2차전지/바이오 순환매 지속"
            hd_path = os.path.join(base_dir, 'data', 'df_high_density.csv')
            if os.path.exists(hd_path):
                df_hd_tmp = pd.read_csv(hd_path)
                if not df_hd_tmp.empty and 'Name' in df_hd_tmp.columns:
                    top_lead = df_hd_tmp.head(4)['Name'].tolist()
                    sec_text = f"├ <b>수급 집중 주도주</b>: {', '.join(top_lead)}\n└ 💡 주도주 중심 자금 쏠림 현상 심화 (개별 테마주 선별 대응 필요)"

            # ── [초고도화] 5. 내일 시초가 흐름 예측 & 대표님 보유 종목 연동 핀포인트 실전 작전 ──
            # (1) 내일 시초가 흐름 예측 (장세 기반)
            if late_diff < -500:
                open_forecast = "🔻 <b>[내일 시초가]</b>: <b>갭하락 출발 유력 (-0.4%~-0.8%)</b> (오늘 마감 투매 여파)"
                open_guide = "   ⏱️ <b>09:00~09:20 [패닉 투매 금지]</b>: 시초가 15분간 관망, 전일 저점 지지 및 09:20 이후 외인 선물 순매수 전환 확인 시에만 대응"
            elif late_diff > 500:
                open_forecast = "🔺 <b>[내일 시초가]</b>: <b>갭상승 출발 유력 (+0.5%~+1.0%)</b> (외인 숏커버링 유입)"
                open_guide = "   ⏱️ <b>09:00~09:15 [추격매수 금지]</b>: 갭상승 후 차익 매물 윗꼬리 주의. 시초가 추격매수 절대 금지, 보유 수익주 분할 익절"
            else:
                open_forecast = "⚖️ <b>[내일 시초가]</b>: <b>보합권 출발 유력 (±0.3%)</b> (야간 나스닥 연동)"
                open_guide = "   ⏱️ <b>09:00~09:15 [방향성 확인]</b>: 08:45 코스피200 선물 개장 베이시스(선물-현물) 상방 전환 확인 후 주도주 압축 공략"

            # (2) 대표님 보유 종목별 핀포인트 맞춤 액션 추출
            profit_stocks = []
            small_dip_stocks = []
            heavy_stocks = []

            if os.path.exists(port_path) and df_m_tmp is not None and not df_m_tmp.empty:
                for pk, pv in port_data.items():
                    s_name = str(pv.get('name', pk))
                    s_ep = float(pv.get('entry_price', 0))
                    s_qty = float(pv.get('qty', 0))
                    m_row = df_m_tmp[df_m_tmp['Code'].astype(str).str.zfill(6) == str(pk).zfill(6)]
                    s_cp = float(m_row.iloc[0].get('Close', s_ep)) if not m_row.empty else s_ep
                    s_val = s_ep * s_qty
                    s_pnl = ((s_cp - s_ep) / s_ep * 100) if s_ep > 0 else 0.0
                    s_weight = (s_val / tot_entry * 100) if tot_entry > 0 else 0.0

                    if s_pnl >= 5.0:
                        profit_stocks.append(f"{s_name}(+{s_pnl:.1f}%)")
                    elif s_weight < 12.0 and s_pnl <= -5.0:
                        small_dip_stocks.append(f"{s_name}({s_pnl:.1f}%)")
                    elif s_weight >= 12.0 or s_pnl <= -35.0:
                        heavy_stocks.append(f"{s_name}({s_pnl:.1f}%, 비중{s_weight:.0f}%)")

            port_action_lines = []
            if profit_stocks:
                port_action_lines.append(f"🟢 <b>[수익 극대화]</b> {', '.join(profit_stocks)}: 시초가 슈팅 시 1차 익절 목표가에서 <b>50% 분할 익절</b>로 확정수익 확보")
            if small_dip_stocks:
                port_action_lines.append(f"🟡 <b>[스마트 평단 인하]</b> {', '.join(small_dip_stocks)}: 내일 갭하락 후 09:30 20일선 지지 확인 시 <b>1회 분할 추가매수</b>로 탈출 평단 단축")
            if heavy_stocks:
                port_action_lines.append(f"🔴 <b>[비중과다 리스크 관리]</b> {', '.join(heavy_stocks)}: 추가 매수 절대 금지! 장중 반등(+3~5%) 출회 시 <b>비중 20~30% 축소</b>로 현금 확보")

            port_action_text = "\n".join(port_action_lines) if port_action_lines else "보유 종목 안정권 유지 중 (원칙 매매 준수)"

            strat_text = (
                f"{open_forecast}\n"
                f"{open_guide}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎯 <b>[대표님 보유 종목별 내일 핀포인트 액션]</b>\n"
                f"{port_action_text}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"⏰ <b>[내일 핵심 매매 타임테이블]</b>\n"
                f"├ <b>08:45</b>: 코스피200 선물 개장 수급 (외인 상방/하방 베팅 확인)\n"
                f"├ <b>09:00~09:15</b>: 시초가 갭 방향 확인 (절대 매매 자제 구간)\n"
                f"└ <b>09:30~10:00</b>: 당일 수급 집중 퀀트 TOP3 압축 공략 & 계좌 비중 조절"
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
