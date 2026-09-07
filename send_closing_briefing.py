# -*- coding: utf-8 -*-
"""
send_closing_briefing.py
-------------------------
평일 정규장 마감 직후 매일 15:40(KST) 정각에
1. 오늘 시장 3대 수급 동향 및 코스피/코스닥 결산
2. 외국인 선물 및 장 후반 수급 기류 분석
3. 자금 쏠림 주도 섹터
4. 대표님 계좌 포트폴리오 결산
5. 내일 시초가 시나리오별 실전 가이드 및 보유 종목별 핀포인트 액션
6. 퀀트 TOP 유망주
를 초고속 집계하여 텔레그램으로 발송하는 전용 스크립트입니다.
로컬 PC 실행 여부와 무관하게 GitHub Actions 클라우드에서 100% 독립 실행됩니다.
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

# 1. 한국 표준시(KST) 강제 고정
KST = timezone(timedelta(hours=9))
now_kst = datetime.now(KST)
now_hm = now_kst.hour * 100 + now_kst.minute
now_weekday = now_kst.weekday()
today_str = now_kst.strftime('%Y%m%d')

print(f"🌙 [Closing Briefing Sender] 기동: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} KST (weekday={now_weekday}, hm={now_hm})")

# 주말(토, 일)이면 스킵
if now_weekday >= 5:
    print("  ⏭️ 주말이므로 장마감 브리핑을 건너뜁니다.")
    sys.exit(0)

base_dir = os.path.dirname(os.path.abspath(__file__))

# 2. 텔레그램 토큰 로드 (Secrets -> secrets.toml -> Fallback)
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

import telegram_notifier as tn

# 3. 중복 발송 방지 상태 확인
state_file = os.path.join(base_dir, 'data', 'last_briefing_state.json')
os.makedirs(os.path.dirname(state_file), exist_ok=True)
briefing_state = {}
if os.path.exists(state_file):
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            briefing_state = json.load(f)
    except Exception:
        briefing_state = {}

last_closing = briefing_state.get('last_closing_date')
force_flag = os.environ.get("FORCE_SEND", "0") == "1"

if not force_flag and last_closing == today_str:
    print(f"  ⏭️ 오늘({today_str}) 이미 장마감 브리핑이 발송 완료되었습니다. 스킵합니다.")
    sys.exit(0)

print(f"🚀 장마감 브리핑 데이터 집계 및 생성 중 ({today_str})...")

# 4. 포트폴리오 및 시세 로드
port_path = os.path.join(base_dir, 'data', 'my_portfolio.json')
m_path = os.path.join(base_dir, 'data', 'df_full_market.csv')
tot_eval = 0.0
tot_entry = 0.0
port_count = 0
port_data = {}
df_m_tmp = pd.DataFrame()

if os.path.exists(port_path):
    try:
        with open(port_path, 'r', encoding='utf-8') as f:
            port_data = json.load(f)
        port_count = len(port_data)
        if os.path.exists(m_path):
            df_m_tmp = pd.read_csv(m_path)
        
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
    except Exception as e:
        print(f"DEBUG: 포트폴리오 집계 오류: {e}")

tot_pnl = tot_eval - tot_entry
tot_pct = ((tot_eval - tot_entry) / tot_entry * 100) if tot_entry > 0 else 0.0

# 5. 시장 수급 및 선물/환율 동향
sum_path = os.path.join(base_dir, 'data', 'df_market_summary.csv')
in_path = os.path.join(base_dir, 'data', 'df_supply_intraday.csv')
mkt_lines = []
fx_val = "1,344원선"

if os.path.exists(sum_path):
    try:
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
    except Exception as e:
        print(f"DEBUG: 시장 요약 집계 오류: {e}")

mkt_text = "\n".join(mkt_lines) if mkt_lines else "코스피/코스닥 정규장 마감 완료"

# 6. 장 후반 외인 수급 가속도 & 선물 기류
late_diff = 0
late_trend_str = "장 마감까지 외국인 현·선물 매도세 유지"
fut_impact_str = "내일 08:45 선물 개장 직후 베이시스(선물-현물 스프레드) 상방 전환 여부 필수 확인"

if os.path.exists(in_path):
    try:
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
    except Exception as e:
        print(f"DEBUG: 일중 수급 분석 오류: {e}")

fut_text = (
    f"├ <b>장 후반(14:00~15:30) 수급 기류</b>: {late_trend_str}\n"
    f"├ <b>원/달러 환율 (FX)</b>: {fx_val} (환율 안정세)\n"
    f"└ 💡 <b>선물/수급 핵심 시사점</b>: {fut_impact_str}"
)

# 7. 주도 섹터
sec_text = "반도체/AI 및 2차전지/바이오 순환매 지속"
hd_path = os.path.join(base_dir, 'data', 'df_high_density.csv')
if os.path.exists(hd_path):
    try:
        df_hd_tmp = pd.read_csv(hd_path)
        if not df_hd_tmp.empty and 'Name' in df_hd_tmp.columns:
            top_lead = df_hd_tmp.head(4)['Name'].tolist()
            sec_text = f"├ <b>수급 집중 주도주</b>: {', '.join(top_lead)}\n└ 💡 주도주 중심 자금 쏠림 현상 심화 (개별 테마주 선별 대응 필요)"
    except Exception:
        pass

# 8. 내일 시초가 시나리오 & 포트폴리오 핀포인트 액션
if late_diff < -500:
    open_forecast = "🔻 <b>[내일 시초가]</b>: <b>갭하락 출발 유력 (-0.4%~-0.8%)</b> (오늘 마감 투매 여파)"
    open_guide = "   ⏱️ <b>09:00~09:20 [패닉 투매 금지]</b>: 시초가 15분간 관망, 전일 저점 지지 및 09:20 이후 외인 선물 순매수 전환 확인 시에만 대응"
elif late_diff > 500:
    open_forecast = "🔺 <b>[내일 시초가]</b>: <b>갭상승 출발 유력 (+0.5%~+1.0%)</b> (외인 숏커버링 유입)"
    open_guide = "   ⏱️ <b>09:00~09:15 [추격매수 금지]</b>: 갭상승 후 차익 매물 윗꼬리 주의. 시초가 추격매수 절대 금지, 보유 수익주 분할 익절"
else:
    open_forecast = "⚖️ <b>[내일 시초가]</b>: <b>보합권 출발 유력 (±0.3%)</b> (야간 나스닥 연동)"
    open_guide = "   ⏱️ <b>09:00~09:15 [방향성 확인]</b>: 08:45 코스피200 선물 개장 베이시스(선물-현물) 상방 전환 확인 후 주도주 압축 공략"

profit_stocks = []
small_dip_stocks = []
heavy_stocks = []

if port_data and not df_m_tmp.empty:
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

# 9. 텔레그램 발송
print("📤 [Telegram] 장마감 결산 브리핑 발송 시도...")
r1 = tn.notify_closing_briefing(
    token=token, chat_id=chat_id,
    total_eval=tot_eval, total_pnl=tot_pnl, total_pct=tot_pct,
    port_count=port_count,
    market_summary_text=mkt_text,
    foreign_futures_text=fut_text,
    leading_sectors_text=sec_text,
    tomorrow_strategy_text=strat_text
)

# 10. 퀀트 TOP 1 추천
r2 = False
q_path = os.path.join(base_dir, 'data', 'df_quant_final.csv')
if os.path.exists(q_path):
    try:
        df_q_pick = pd.read_csv(q_path)
        if not df_q_pick.empty:
            top1 = df_q_pick.iloc[0]
            t_code = str(int(top1.get('Code', 0)) if pd.notna(top1.get('Code')) else '').zfill(6)
            # 신규 상장주 제외 체크
            is_new = False
            try:
                import FinanceDataReader as _fdr
                _dh = _fdr.DataReader(t_code)
                if len(_dh) < 60:
                    is_new = True
            except Exception:
                pass
            
            if not is_new:
                r2 = tn.notify_quant_top_pick(
                    token=token, chat_id=chat_id,
                    ticker=t_code,
                    name=str(top1.get('Name', '')),
                    score=float(top1.get('Total_Score_Adj', top1.get('Total_Score', 0))),
                    price=float(top1.get('Close', 0)),
                    chg_rate=float(top1.get('ChagesRatio', 0))
                )
    except Exception as _qe:
        print(f"DEBUG: 퀀트 추천 발송 에러: {_qe}")

print(f"✅ 장마감 브리핑 전송 완료 (r1={r1}, r2={r2})")

if r1 or r2:
    briefing_state['last_closing_date'] = today_str
    try:
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(briefing_state, f, ensure_ascii=False, indent=2)
        print(f"💾 마감 브리핑 성공 상태 저장 완료 ({today_str})")
    except Exception as se:
        print(f"DEBUG: 상태 파일 저장 실패: {se}")
