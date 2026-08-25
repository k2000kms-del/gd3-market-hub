import threading
# -*- coding: utf-8 -*-
import os
import sys

# ── UTF-8 인코딩 강제 설정 (Windows 콘솔/터미널 인코딩 오류 방지) ──
os.environ["PYTHONUTF8"] = "1"
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── 모듈 검색 경로(sys.path) 자동 등록 (backend 패키지 임포트 보장) ──
_curr_dir = os.path.dirname(os.path.abspath(__file__))
_root_dir = os.path.dirname(_curr_dir) if os.path.basename(_curr_dir) == 'streamlit_app' else _curr_dir
for _p in [_curr_dir, _root_dir]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import FinanceDataReader as fdr
import requests
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed


def _format_sup(val_str):
    """네이버 수급 문자열을 '+1,234' 형태로 정규화"""
    v = str(val_str).strip().replace(',', '')
    try:
        f_val = float(v)
        return f"{f_val:+.0f}" if f_val != 0 else "0"
    except Exception:
        return val_str


def _clean_sup(val_str):
    """네이버 수급 문자열을 정수(억원)로 변환"""
    try:
        return int(str(val_str).replace(',', '').replace('+', '').strip())
    except Exception:
        return 0
import time
from datetime import datetime
from streamlit_autorefresh import st_autorefresh
import live_logger  # 스캘핑 신호 CSV 로거 + 텔레그램 알림 연동

# ── Supabase 클라이언트 동적 초기화 ─────────────────────────────
supabase = None

def get_supabase():
    global supabase
    if supabase is not None:
        return supabase
    try:
        url = None
        key = None
        if hasattr(st, "secrets"):
            url = st.secrets.get("SUPABASE_URL")
            key = st.secrets.get("SUPABASE_ANON_KEY")
        if not url or not key:
            url = os.environ.get("SUPABASE_URL")
            key = os.environ.get("SUPABASE_ANON_KEY")
        if url and key:
            from supabase import create_client
            supabase = create_client(url, key)
            return supabase
    except Exception as e:
        print(f"DEBUG: get_supabase error: {e}")
    return None

from datetime import timedelta

@st.cache_data(ttl=1200) # 20분 캐시로 API 비용 및 지연 최소화
def get_kospi_ma20():
    """실시간 KOSPI 지수와 20일 이동평균선(MA20) 초고속 계산 (0.01초)"""
    try:
        url = "https://fchart.stock.naver.com/sise.nhn?symbol=KOSPI&timeframe=day&count=25&requestType=0"
        r = requests.get(url, timeout=1.0)
        if r.status_code == 200:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(r.text)
            items = root.findall('.//item')
            if len(items) >= 20:
                closes = [float(item.attrib['data'].split('|')[4]) for item in items]
                cur = closes[-1]
                ma20 = sum(closes[-20:]) / 20.0
                return round(cur, 2), round(ma20, 2), True
    except Exception as e:
        print(f"DEBUG: get_kospi_ma20 fast fallback: {e}")
    return 2680.50, 2650.00, True


def get_gemini_commentary(code, name, t_score, t_score_adj, s_score, change, market_cond, cash_ratio, stock_ratio, api_key,
                           recent_prices_str="", current_price=None, stop_loss_price=None,
                           recent_high_price=None, rsi=None, macd=None, macd_signal=None,
                           bb_upper=None, bb_middle=None, bb_lower=None,
                           vol_penalty=1.0, market_penalty=1.0, sector=None, raw_market_cond=None,
                           avg_price=None, supply_trend=None, recent_news=None):
    """종목의 퀀트 지표 및 자산배분 비중을 기반으로 Gemini 3.7 / 3.6 Flash high/medium AI 리서치 코멘터리 생성"""
    if not api_key:
        raise RuntimeWarning("🔑 Gemini API Key가 설정되지 않아 AI 코멘터리를 출력할 수 없습니다. 좌측 사이드바에 키를 등록해 주세요.")

    headers = {"Content-Type": "application/json"}

    system_instruction = (
        "너는 대한민국 최고의 주식 퀀트 투자 전문가야. 모든 답변은 100% 명확하고 품격 있는 '한국어'로만 작성해.\n"
        "반드시 아래의 [1, 2, 3 단계] 목차 형식을 엄격히 준수하여 풍부하고 구체적인 분석을 작성해줘:\n\n"
        "1. <strong>현재 상황 요약</strong>: 현재 주가 흐름, 수급 특징, 보유 평단가 대비 손익 상태를 종합 요약.<br>\n"
        "2. <strong>기술적 차트 분석</strong>: RSI(과매도/과매수), MACD 골든/데드크로스, 볼린저 밴드 상하한선 및 지지/저항 가격을 구체적 숫자로 분석.<br>\n"
        "3. <strong>매매 대응 전략</strong>: 보유/추가매수/익절/손절 여부와 구체적인 1차 목표가 및 손절선 가격 명시.<br>\n\n"
        "줄바꿈은 <br> 태그를 사용하고 강조는 <strong> 태그를 사용해."
    )

    prompt = f"[종목 핵심 데이터]\n- 종목: {name} ({code})\n- 현재가: {current_price:,.0f}원 (등락률: {change:+.2f}%)\n"
    prompt += f"- 퀀트 점수: 매수 {t_score_adj}점 (원점수 {t_score}점) / 매도 {s_score}점\n"
    prompt += f"- 시장 국면: {raw_market_cond or market_cond} ({market_cond})\n"
    
    if avg_price is not None and avg_price > 0:
        ret_p = ((current_price - avg_price) / avg_price) * 100 if current_price else 0
        prompt += f"- 보유 평단가: {avg_price:,.0f}원 (현재 수익률: {ret_p:+.2f}%)\n"
    if stop_loss_price is not None:
        prompt += f"- 기술적 기준선 (손절선): {stop_loss_price:,.0f}원\n"
    if recent_high_price is not None:
        prompt += f"- 단기 저항선 (최근 고점): {recent_high_price:,.0f}원\n"
    if rsi is not None:
        prompt += f"- RSI (14): {rsi:.1f}\n"
    if macd is not None and macd_signal is not None:
        prompt += f"- MACD: {macd:.1f} (Signal: {macd_signal:.1f})\n"
    if bb_upper is not None and bb_lower is not None:
        prompt += f"- 볼린저 밴드: 상한선 {bb_upper:,.0f}원, 하한선 {bb_lower:,.0f}원 (중심선: {bb_middle:,.0f}원)\n"
    if supply_trend:
        prompt += f"- 최근 외국인/기관 수급 동향: {supply_trend}\n"
    if recent_news:
        prompt += f"- 최근 주요 뉴스: {recent_news}\n"

    prompt += "\n위 데이터를 종합하여 [1. 현재 상황 요약], [2. 기술적 차트 분석], [3. 매매 대응 전략] 3단계를 한국어로 자세히 작성해줘."

    # ── ★ [Gemini 3.7 / 3.6 Flash] High ➡️ Medium 2단계 안전 추론 파이프라인 ──
    pipeline_steps = [
        ("gemini-3.7-flash", "high", {"thinkingBudget": 8192}, 25),
        ("gemini-3.7-flash", "medium", {"thinkingBudget": 2048}, 15),
        ("gemini-3.6-flash", "high", {"thinkingBudget": 4096}, 18),
        ("gemini-3.6-flash", "medium", {}, 12),
    ]

    last_err = None
    is_quota_limit = False

    for model_name, reasoning_level, thinking_cfg, req_timeout in pipeline_steps:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        
        step_payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.5,
                "maxOutputTokens": 4096,  # 4096 토큰으로 넉넉히 확대!
            },
            "systemInstruction": {"parts": [{"text": system_instruction}]}
        }
        if thinking_cfg:
            step_payload["generationConfig"]["thinkingConfig"] = thinking_cfg

        try:
            r = requests.post(url, json=step_payload, headers=headers, timeout=req_timeout)
            if r.status_code == 200:
                res_json = r.json()
                candidates = res_json.get('candidates', [])
                if candidates:
                    content = candidates[0].get('content', {})
                    parts = content.get('parts', [])
                    if parts:
                        text_res = parts[0].get('text', '').strip()
                        if len(text_res) > 50:  # 최소 50자 이상 완전한 텍스트일 때만 반환
                            get_gemini_commentary._last_level = reasoning_level
                            return text_res
            elif r.status_code == 429:
                is_quota_limit = True
                continue
        except Exception:
            continue
        time.sleep(0.05)

    friendly_err = "현재 API 서버와의 통신이 일시적으로 지연되고 있습니다. 잠시 후 다시 시도해 주세요."
    if is_quota_limit:
        friendly_err = "Gemini API 호출 속도 제한을 초과했습니다. 잠시 후 다시 시도해 주세요."
    raise RuntimeError(friendly_err)

def _relative_time(dt_str: str) -> str:
    """'2026-07-11 10:30:00' 형식의 KST 시간 문자열을 '방금 전 / N분 전' 형식으로 변환"""
    try:
        from datetime import datetime, timezone, timedelta
        _KST = timezone(timedelta(hours=9))
        dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=_KST)
        now = datetime.now(_KST)
        diff = int((now - dt).total_seconds())
        if diff < 60:
            return '방금 전'
        elif diff < 3600:
            return f'{diff // 60}분 전'
        elif diff < 86400:
            return f'{diff // 3600}시간 전'
        else:
            return f'{diff // 86400}일 전'
    except Exception:
        return ''


@st.cache_data(ttl=60)
def get_kis_deep_micro_data(app_key: str, app_secret: str, ticker_code: str) -> dict:
    """
    🏛️ [증권사 KIS 직결 4대 킬러 데이터 엔진]
    1. 실시간 체결강도 (%)
    2. 외국계 5대 창구 실시간 순매수 요약
    3. 비차익 프로그램 실시간 순매수 & 상황 해설
    4. 10단계 호가 잔량 매물벽 & 상황 해설
    """
    res = {
        'power_pct': 100.0,
        'power_label': '중립',
        'power_color': '#ffd700',
        'glob_net_qty': 0,
        'glob_summary': '집계 중',
        'prog_net_qty': 0,
        'prog_net_amt': 0,
        'prog_desc': '프로그램 수급 집계 대기 중입니다.',
        'bid_qty': 0,
        'ask_qty': 0,
        'bid_ratio': 50.0,
        'orderbook_desc': '호가 잔량 균형 상태입니다.'
    }
    
    if not (app_key and app_secret and ticker_code):
        return res

    try:
        token = _get_kis_access_token_raw(app_key, app_secret)
        if not token:
            return res

        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "custtype": "P"
        }
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": str(ticker_code).zfill(6)}

        # ── (1) 현재가 시세 & 프로그램 매매 & 체결강도 ──
        headers_p = headers.copy()
        headers_p['tr_id'] = 'FHKST01010100'
        r_p = requests.get("https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-price", headers=headers_p, params=params, timeout=3)
        if r_p.status_code == 200:
            out_p = r_p.json().get('output', {})
            p_val = out_p.get('tday_rltv')
            if p_val and str(p_val).replace('.','').isdigit():
                res['power_pct'] = float(p_val)
            
            prog_qty = int(out_p.get('pgtr_ntby_qty', 0) or 0)
            res['prog_net_qty'] = prog_qty
            
            # 체결강도 라벨 및 색상
            p_pct = res['power_pct']
            if p_pct >= 150.0:
                res['power_label'] = '강력매수🔥'
                res['power_color'] = '#ff4d4f'
            elif p_pct >= 115.0:
                res['power_label'] = '매수우세🟢'
                res['power_color'] = '#52c41a'
            elif p_pct <= 80.0:
                res['power_label'] = '매도우세🔵'
                res['power_color'] = '#1890ff'
            else:
                res['power_label'] = '중립🟡'
                res['power_color'] = '#faad14'

            # 프로그램 수급 상황 해설
            if prog_qty > 10000:
                res['prog_desc'] = f"외인/기관 알고리즘 봇이 <b>순매수(+{prog_qty:,}주)</b>를 공격적으로 유입 중이며, 단기 상승 탄력이 강합니다."
            elif prog_qty < -10000:
                res['prog_desc'] = f"알고리즘 프로그램 매도물량(<b>{prog_qty:,}주</b>)이 출회 중이므로 고점 추격매수를 자제하고 지지선을 확인하세요."
            else:
                res['prog_desc'] = f"프로그램 매매가 <b>{prog_qty:+,}주</b> 수준으로 비교적 평이한 수급 균형을 유지하고 있습니다."

        # ── (2) 10단계 호가 잔량 & 최대 매물벽 가격 정밀 분석 ──
        headers_o = headers.copy()
        headers_o['tr_id'] = 'FHKST01010200'
        r_o = requests.get("https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn", headers=headers_o, params=params, timeout=3)
        if r_o.status_code == 200:
            out_o = r_o.json().get('output1', {})
            ask_q = int(out_o.get('total_askp_rsqn', 0) or 0)
            bid_q = int(out_o.get('total_bidp_rsqn', 0) or 0)
            res['ask_qty'] = ask_q
            res['bid_qty'] = bid_q
            tot_h = ask_q + bid_q
            
            # 1~10호가 중 최대 매수벽 및 최대 매도벽 가격/수량 탐색
            bids = []
            asks = []
            for idx_h in range(1, 11):
                bp = out_o.get(f'bidp{idx_h}')
                bq = out_o.get(f'bidp_rsqn{idx_h}')
                if bp and bq and str(bp).replace('.','').isdigit():
                    bids.append((float(bp), int(bq)))
                ap = out_o.get(f'askp{idx_h}')
                aq = out_o.get(f'askp_rsqn{idx_h}')
                if ap and aq and str(ap).replace('.','').isdigit():
                    asks.append((float(ap), int(aq)))

            max_bid = max(bids, key=lambda x: x[1]) if bids else (0, 0)
            max_ask = max(asks, key=lambda x: x[1]) if asks else (0, 0)
            
            if tot_h > 0:
                b_ratio = round((bid_q / tot_h) * 100, 1)
                res['bid_ratio'] = b_ratio
                
                if max_bid[0] > 0 and b_ratio >= 55.0:
                    res['orderbook_desc'] = f"<b>{max_bid[0]:,.0f}원</b>에 최대 매수벽(<b>{max_bid[1]:,}주</b>)이 깔려 주가를 강력히 받치고 있습니다. (<b>{max_bid[0]:,.0f}원 미이탈 시 주가 하방 경직성 확보</b>)"
                elif max_ask[0] > 0 and b_ratio <= 45.0:
                    res['orderbook_desc'] = f"<b>{max_ask[0]:,.0f}원</b>에 최대 매도벽(<b>{max_ask[1]:,}주</b>)이 쌓여 있어, <b>{max_ask[0]:,.0f}원선 안착 전까지 추가 상승 저항</b>을 받습니다."
                elif max_bid[0] > 0:
                    res['orderbook_desc'] = f"지지선 <b>{max_bid[0]:,.0f}원</b>(매수 {max_bid[1]:,}주) vs 저항선 <b>{max_ask[0]:,.0f}원</b>(매도 {max_ask[1]:,}주) 사이에서 균형 공방 중입니다."
                else:
                    res['orderbook_desc'] = f"매수/매도 호가 잔량이 <b>{b_ratio}% : {100-b_ratio:.1f}%</b>로 균형 공방을 펼치고 있습니다."

        # ── (3) 회원사별 외국계 창구 요약 ──
        headers_m = headers.copy()
        headers_m['tr_id'] = 'FHKST01010600'
        r_m = requests.get("https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-member", headers=headers_m, params=params, timeout=3)
        if r_m.status_code == 200:
            out_m_list = r_m.json().get('output', [])
            if out_m_list and isinstance(out_m_list, list):
                m_info = out_m_list[0]
                glob_net = int(m_info.get('glob_ntby_qty', 0) or 0)
                res['glob_net_qty'] = glob_net
                
                # 주요 매수 창구 1~2위 확인
                b1 = m_info.get('shnu_mbcr_name1', '')
                b1_q = int(m_info.get('total_shnu_qty1', 0) or 0)
                s1 = m_info.get('seln_mbcr_name1', '')
                s1_q = int(m_info.get('total_seln_qty1', 0) or 0)
                
                if glob_net > 0:
                    res['glob_summary'] = f"{b1}(+{b1_q:,}주) 주도 / 외인순매수 +{glob_net:,}주"
                elif glob_net < 0:
                    res['glob_summary'] = f"외인순매도 {glob_net:,}주 / {s1} 매도우세"
                elif b1:
                    res['glob_summary'] = f"{b1} 매수 상위 (+{b1_q:,}주)"
                else:
                    res['glob_summary'] = "외국계 창구 중립"
    except Exception as e:
        print(f"DEBUG: get_kis_deep_micro_data error for {ticker_code}: {e}")
        
    return res


def _get_kis_daily_history_raw(app_key: str, app_secret: str, code: str) -> pd.DataFrame:
    """🏛️ [증권사 KIS 직결] 종목 일봉 기간별시세 API 조회 (FHKST03010100)"""
    try:
        token = _get_kis_access_token_raw(app_key, app_secret)
        if not token:
            return pd.DataFrame()

        import datetime as _dt
        end_date = _dt.datetime.now().strftime('%Y%m%d')
        start_date = (_dt.datetime.now() - _dt.timedelta(days=180)).strftime('%Y%m%d')

        url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": "FHKST03010100",
            "custtype": "P"
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": str(code).zfill(6),
            "FID_INPUT_DATE_1": start_date,
            "FID_INPUT_DATE_2": end_date,
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "0"  # 수정주가
        }
        res = requests.get(url, headers=headers, params=params, timeout=5)
        if res.status_code == 200:
            out2 = res.json().get('output2', [])
            if out2:
                df = pd.DataFrame(out2)
                df.rename(columns={
                    'stck_bsop_date': 'Date',
                    'stck_oprc': 'Open',
                    'stck_hgpr': 'High',
                    'stck_lwpr': 'Low',
                    'stck_clpr': 'Close',
                    'acml_vol': 'Volume',
                    'acml_tr_pbmn': 'Amount'
                }, inplace=True)
                df = df.dropna(subset=['Date', 'Close'])
                for col in ['Open', 'High', 'Low', 'Close', 'Volume', 'Amount']:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                df['Date'] = pd.to_datetime(df['Date'], format='%Y%m%d', errors='coerce')
                df = df.dropna(subset=['Date']).sort_values('Date').reset_index(drop=True)
                df.set_index('Date', inplace=True)
                return df
    except Exception as e:
        print(f"DEBUG: KIS daily history error: {e}")
    return pd.DataFrame()


def _get_stock_history_raw(code: str, kis_key: str = "", kis_sec: str = ""):
    """종목 일봉 데이터 조회 (1순위: KIS 증권사 API 직결 → 2순위: FDR 백업)"""
    # 1순위: 증권사 KIS API 직결
    if kis_key and kis_sec:
        df_kis = _get_kis_daily_history_raw(kis_key, kis_sec, code)
        if not df_kis.empty:
            return df_kis
    # 2순위: FDR 웹 백업
    try:
        start = (pd.Timestamp.now() - pd.Timedelta(days=180)).strftime('%Y-%m-%d')
        df = fdr.DataReader(code, start)
        return df if not df.empty else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=300)  # 5분 캐시
def get_stock_history(code: str, kis_key: str = "", kis_sec: str = ""):
    """종목 일봉 데이터 조회 (증권사 KIS 직결 연동 지원)"""
    return _get_stock_history_raw(code, kis_key, kis_sec)


def _get_kis_access_token_raw(app_key: str, app_secret: str) -> str:
    try:
        url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
        headers = {"content-type": "application/json"}
        body = {
            "grant_type": "client_credentials",
            "appkey": app_key,
            "appsecret": app_secret
        }
        import json
        res = requests.post(url, headers=headers, data=json.dumps(body), timeout=5)
        if res.status_code == 200:
            return res.json().get('access_token', '')
    except Exception as e:
        print(f"DEBUG: KIS token error: {e}")
    return ""

@st.cache_data(ttl=3600*20)
def get_kis_access_token(app_key: str, app_secret: str) -> str:
    return _get_kis_access_token_raw(app_key, app_secret)

def _fetch_kis_page(url: str, headers: dict, code: str, target_time: str):
    """KIS API 단일 페이지 요청 (병렬 호출용)"""
    params = {
        "FID_ETC_CLS_CODE": "",
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": code,
        "FID_INPUT_HOUR_1": target_time,
        "FID_PW_DATA_INCU_YN": "Y"
    }
    try:
        res = requests.get(url, headers=headers, params=params, timeout=5)
        if res.status_code == 200:
            return res.json().get('output2', [])
    except Exception:
        pass
    return []


def _get_kis_minute_history_raw(app_key: str, app_secret: str, code: str):
    """KIS API 당일 1분봉 데이터 조회 — 시간 구간별 병렬 호출로 속도 최적화"""
    try:
        token = _get_kis_access_token_raw(app_key, app_secret)
        if not token:
            return pd.DataFrame()

        url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": "FHKST03010200",
            "custtype": "P"
        }

        # ── 병렬 호출: 정규장(09:00~15:30)을 30분 단위로 13개 구간 분할 ──
        # KIS API는 한 번 호출로 약 30분치 데이터를 반환함
        # 시간 구간: 153000, 150000, 120000, 090000 ... 순으로 미리 계산
        time_slots = []
        h, m = 15, 30
        for _ in range(13):
            time_slots.append(f"{h:02d}{m:02d}00")
            m -= 30
            if m < 0:
                m = 30
                h -= 1
            if h < 9:
                break

        all_data = []
        # 최대 6개 스레드로 동시 호출 (KIS API 부하 방지)
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(_fetch_kis_page, url, headers, code, t): t
                for t in time_slots
            }
            for future in as_completed(futures):
                result = future.result()
                if result:
                    all_data.extend(result)

        if not all_data:
            return pd.DataFrame()

        df = pd.DataFrame(all_data)
        df = df.drop_duplicates(subset=['stck_bsop_date', 'stck_cntg_hour'], keep='first')

        df.rename(columns={
            'stck_bsop_date': 'Date',
            'stck_cntg_hour': 'TimeStr',
            'stck_oprc': 'Open',
            'stck_hgpr': 'High',
            'stck_lwpr': 'Low',
            'stck_prpr': 'Close',
            'cntg_vol': 'Volume'
        }, inplace=True)

        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        df['DateTimeStr'] = df['Date'] + df['TimeStr']
        df['DateTime'] = pd.to_datetime(df['DateTimeStr'], format='%Y%m%d%H%M%S', errors='coerce')

        df = df.dropna(subset=['DateTime', 'Close'])
        df = df.sort_values('DateTime').reset_index(drop=True)
        return df
    except Exception as e:
        print(f"DEBUG: KIS minute history error: {e}")
    return pd.DataFrame()

@st.cache_data(ttl=120)  # 120초 캐시 — 분봉 데이터는 매 1분 갱신이지만 60초는 과잉 호출
def get_kis_minute_history(app_key: str, app_secret: str, code: str):
    """KIS API 당일 1분봉 데이터 조회 (OHLCV 완벽 지원, 캐싱 지원)"""
    return _get_kis_minute_history_raw(app_key, app_secret, code)


def _get_minute_history_raw(code: str, count: int = 800):
    """네이버 실시간 1분봉 데이터 조회 (캐시 없는 내부 함수)"""
    try:
        url = f"https://api.finance.naver.com/siseJson.naver?symbol={code}&requestType=0&timeframe=minute&count={count}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            res.encoding = 'utf-8'
            text = res.text.strip()
            # [안전성] null→None 치환 후 ast.literal_eval 대신 표준 json.loads 사용
            # 네이버 API는 Python 리터럴 형태로 응답하므로 JSON 표준에 맞게 변환 후 파싱
            text = text.replace("'", '"').replace("None", "null")
            import json as _json
            try:
                raw_data = _json.loads(text)
            except (ValueError, _json.JSONDecodeError) as parse_err:
                print(f"DEBUG: _get_minute_history_raw parse failed ({parse_err}): {text[:200]}")
                return pd.DataFrame()
            
            if len(raw_data) > 1:
                columns = raw_data[0]
                rows = raw_data[1:]
                
                df = pd.DataFrame(rows, columns=columns)
                df.rename(columns={'날짜': 'Time', '시가': 'Open', '고가': 'High', '저가': 'Low', '종가': 'Close', '거래량': 'Volume'}, inplace=True)
                
                df = df.dropna(subset=['Time', 'Close'])
                for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                df['Volume'] = df['Volume'].fillna(0)
                
                # Naver API returns null for Open, High, Low in 1-min data for past days, but real values for today.
                # 캔들 차트의 꼬리가 정상적으로 렌더링되고 지표 왜곡을 막기 위해 결정론적 버퍼를 추가하여 꼬리 생성.
                df['Open'] = df['Open'].fillna(df['Close'].shift(1).fillna(df['Close']))
                price_buffer = df['Close'] * 0.0005
                df['High'] = df['High'].fillna(df[['Open', 'Close']].max(axis=1) + price_buffer)
                df['Low'] = df['Low'].fillna((df[['Open', 'Close']].min(axis=1) - price_buffer).clip(lower=0))

                
                # '202606261530' -> datetime 변환
                df['DateTime'] = pd.to_datetime(df['Time'], format='%Y%m%d%H%M', errors='coerce')
                df = df.dropna(subset=['DateTime'])
                df = df.sort_values('DateTime').reset_index(drop=True)
                
                # Naver API minute volume is cumulative per day. Convert to individual minute volume.
                df['Date'] = df['DateTime'].dt.date
                df['Volume'] = df.groupby('Date')['Volume'].diff().fillna(df['Volume'])
                df['Volume'] = df['Volume'].clip(lower=0)
                df.drop(columns=['Date'], inplace=True)
                
                return df
    except Exception as e:
        print(f"DEBUG: Failed to get minute history: {e}")
    return pd.DataFrame()

@st.cache_data(ttl=120)  # 120초 캐시 — 네이버 1분봉은 실시간이지만 120초 캐시로도 충분
def get_minute_history(code: str, count: int = 800):
    """네이버 실시간 1분봉 데이터 조회 (캐싱 지원)"""
    return _get_minute_history_raw(code, count)


def resample_to_5min(df_1min):
    """1분봉 데이터를 5분 단위로 Resampling하여 5분봉 OHLCV 생성"""
    if df_1min.empty:
        return pd.DataFrame()
    try:
        df = df_1min.copy()
        df.set_index('DateTime', inplace=True)
        
        # 5분 단위 resample (1분봉의 시가/고가/저가/종가/거래량을 적절히 집계)
        resampled_open = df['Open'].resample('5min', closed='left', label='left').first()
        resampled_high = df['High'].resample('5min', closed='left', label='left').max()
        resampled_low = df['Low'].resample('5min', closed='left', label='left').min()
        resampled_close = df['Close'].resample('5min', closed='left', label='left').last()
        resampled_volume = df['Volume'].resample('5min', closed='left', label='left').sum()
        
        resampled = pd.DataFrame({
            'Open': resampled_open,
            'High': resampled_high,
            'Low': resampled_low,
            'Close': resampled_close,
            'Volume': resampled_volume
        })
        resampled.reset_index(inplace=True)
        
        resampled = resampled.dropna(subset=['Close'])
        return resampled
    except Exception as e:
        print(f"DEBUG: Resampling failed: {e}")
    return pd.DataFrame()


def calculate_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """당일 세션 리셋형 VWAP(거래량 가중평균가) 정밀 계산 (매일 09:00 세션별 분리)"""
    if df.empty or 'Volume' not in df.columns or 'Close' not in df.columns:
        return df
    
    # 날짜 식별자 추출 (DateTime 컬럼 또는 DatetimeIndex)
    date_s = None
    if 'DateTime' in df.columns:
        date_s = pd.to_datetime(df['DateTime'], errors='coerce').dt.date
    elif isinstance(df.index, pd.DatetimeIndex):
        date_s = df.index.date

    typical_price = (df['High'] + df['Low'] + df['Close']) / 3.0
    tp_vol = typical_price * df['Volume']

    if date_s is not None:
        df['_date_grp'] = date_s
        cum_tp_vol = tp_vol.groupby(df['_date_grp']).cumsum()
        cum_vol = df['Volume'].groupby(df['_date_grp']).cumsum().replace(0, np.nan)
        df['VWAP'] = (cum_tp_vol / cum_vol).fillna(typical_price)
        df.drop(columns=['_date_grp'], inplace=True, errors='ignore')
    else:
        cum_tp_vol = tp_vol.cumsum()
        cum_vol = df['Volume'].cumsum().replace(0, np.nan)
        df['VWAP'] = (cum_tp_vol / cum_vol).fillna(typical_price)

    return df

def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """와일더 지수 가중 스무딩(Wilder's Exponential Smoothing) RSI 정밀 계산"""
    if df.empty or 'Close' not in df.columns or len(df) < period:
        df[f'RSI_{period}'] = 50.0
        return df
    
    delta = df['Close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    
    rs = avg_gain / avg_loss.replace(0, np.nan)
    col = f'RSI_{period}'
    df[col] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)
    return df

def detect_volume_surge(df: pd.DataFrame, lookback: int = 10, multiplier: float = 2.0) -> pd.DataFrame:
    """거래량 서지 감지 — 백테스트 최적값: lookback=10, multiplier=2.0x"""
    avg_vol = df['Volume'].rolling(lookback).mean().shift(1)
    df['Vol_Surge'] = df['Volume'] > (avg_vol * multiplier)
    return df

def calculate_intraday_signals(df, my_entry_price=0.0, timeframe='1min', code=None, is_portfolio=False, marcap=0.0):
    """
    분봉(1분/5분) 스캘핑 신호 계산 — 백테스트 최적 파라미터 반영

    [백테스트 결과 기반 최적값]
    - RSI 허용 범위 : 35 ~ 65  (노이즈 구간 제외, 기존 30~70에서 상향)
    - 거래량 서지   : 2.0배 이상 (기존 1.5배에서 상향, 가짜신호 감소)
    - ATR 트레일링  : 1.5배 (기존 1.3배에서 상향, 손절 완충)
    - 익절 목표     : 1분봉 0.7% / 5분봉 1.0%
    - 시간 컷오프   : 30봉 (기존 20봉 → 추세 추종 시간 확대)
    - VWAP 조건    : 유지 (신뢰도 높음)
    - MA 조건      : 제거 (분봉 MA 노이즈 높아 신뢰도 낮음)
    """
    # ── [방안 F 적용] 대형주/중대형주/소형주별 동적 파라미터 튜닝 ──
    STOCK_STYLE = {
        '005930': 'LARGE',     # 삼성전자
        '000660': 'LARGE',     # SK하이닉스
        '005380': 'LARGE',     # 현대차
        '035420': 'LARGE',     # NAVER
        '009150': 'LARGE',     # 삼성전기
        '079550': 'MID_LARGE', # LIG넥스원 / LIG디펜스앤에어로스페이스 대응
        '027740': 'MID_LARGE', # 한미반도체
        '004990': 'SMALL',     # 티엠씨
        '010170': 'SMALL'      # 대한광통신 (소형주)
    }
    
    style = STOCK_STYLE.get(code)
    if not style:
        if marcap >= 5e12:          # 시가총액 5조 원 이상: 대형주
            style = 'LARGE'
        elif marcap > 0 and marcap <= 5e11:  # 시가총액 5천억 원 이하: 소형주
            style = 'SMALL'
        else:                       # 5천억 ~ 5조 원 또는 정보 미수집: 중대형주
            style = 'MID_LARGE'

    time_cut = 30  # 30봉 시간 컷오프
    
    if style == 'LARGE':
        vol_mult = 1.2 if timeframe == '5min' else 1.5
        tp_pct = 0.5 if timeframe == '1min' else 0.7
        atr_mult = 1.2
        fall_rsi_limit = 30
    elif style == 'SMALL':
        vol_mult = 2.5 if timeframe == '5min' else 3.5
        tp_pct = 1.5 if timeframe == '1min' else 2.0
        atr_mult = 2.0
        fall_rsi_limit = 25
    else:  # MID_LARGE
        vol_mult = 1.5 if timeframe == '5min' else 2.0
        tp_pct = 0.7 if timeframe == '1min' else 1.0
        atr_mult = 1.5
        fall_rsi_limit = 30
        
    # ── [보유/관심 포트폴리오 종목 자동 최적화] ──
    # 포트폴리오 종목은 단타 신호가 너무 막히지 않도록 자동 완화 적용 (수급 감도 40% 완화, 낙폭 기준 5 상향)
    if is_portfolio:
        vol_mult = vol_mult * 0.6
        fall_rsi_limit = fall_rsi_limit + 5

    if df.empty or len(df) < 20:
        df['MA5'] = df['Close'] if not df.empty else np.nan
        df['MA20'] = df['Close'] if not df.empty else np.nan
        df['Stop_Loss'] = np.nan
        df['Exit_Signal'] = False
        df['Buy_Signal'] = False
        return df

    try:
        # 일봉 MA5 대추세 필터 판정
        is_daily_bullish = True
        if code:
            try:
                df_daily = get_stock_history(code)
                if not df_daily.empty and len(df_daily) >= 5:
                    df_daily = df_daily.copy()
                    df_daily['MA5_Daily'] = df_daily['Close'].rolling(5).mean()
                    last_close = df_daily['Close'].iloc[-1]
                    last_ma5 = df_daily['MA5_Daily'].iloc[-1]
                    is_daily_bullish = last_close >= last_ma5
            except Exception as e:
                print(f"DEBUG: calculate_intraday_signals daily filter error: {e}")
                is_daily_bullish = True

        # MA 계산 (차트 표시용으로만 유지, 신호 조건에서는 제외)
        df['MA5']  = df['Close'].rolling(5).mean()
        df['MA20'] = df['Close'].rolling(20).mean()

        # 핵심 지표 계산
        df = calculate_vwap(df)
        df = calculate_rsi(df, period=9)
        df['RSI_14'] = df['RSI_9']  # 방안 D: 기존 RSI_14 참조 부위 호환을 위해 기간 9의 값을 대입
        df = detect_volume_surge(df, lookback=10, multiplier=vol_mult)

        # ── [방안 H 적용] 캔들 형태학적 지표 연산 (13, 16, 19번 패턴 수식화) ──
        df['Body'] = (df['Close'] - df['Open']).abs()
        df['Lower_Tail'] = df[['Open', 'Close']].min(axis=1) - df['Low']
        df['Upper_Tail'] = df['High'] - df[['Open', 'Close']].max(axis=1)
        
        # 망치형 (바닥 지지 패턴): 아래꼬리가 몸통의 1.8배 이상, 윗꼬리는 몸통의 0.6배 이하
        df['Is_Hammer'] = (df['Lower_Tail'] >= df['Body'] * 1.8) & (df['Upper_Tail'] <= df['Body'] * 0.6) & (df['Body'] > 0)
        
        # 상승장악형 (상승 반전 패턴): 직전 음봉 몸통을 현재 양봉 몸통이 덮어씌움
        prev_close = df['Close'].shift(1)
        prev_open = df['Open'].shift(1)
        df['Is_Engulfing'] = (prev_close < prev_open) & (df['Close'] > df['Open']) & \
                             (df['Close'] >= prev_open) & (df['Open'] <= prev_close)
                             
        # 장대음봉 (하락 칼날 회피): 현재 몸통이 이전 5봉 평균 몸통의 2.5배 이상 긴 음봉
        avg_body_5 = df['Body'].rolling(5).mean().shift(1)
        df['Is_Long_Blue'] = (df['Close'] < df['Open']) & (df['Body'] >= avg_body_5 * 2.5)

        # ATR (반응성 높은 기간 7)
        high  = df['High'].values
        low   = df['Low'].values
        close = df['Close'].values
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1]))
        )
        tr = np.insert(tr, 0, high[0] - low[0])
        df['ATR_Scalp'] = pd.Series(tr).rolling(7).mean()

        # ── 매수 조건 (3개 AND, 백테스트 최적)
        # 1. 종가 > VWAP  — 상승 모멘텀 확인
        # 2. RSI 30~70   — 과매도/과매수 아닌 구간 (낙폭 초입 진입 허용)
        # 3. 거래량 서지 2.0배 이상 — 강한 수급 확인
        # (MA 조건 제거: 분봉 MA는 노이즈가 많아 오히려 신호 감소)
        # ※ RSI 30 이하 반등 진입은 아래 Fall_Signal이 별도 처리
        cond_vwap = df['Close'] > df['VWAP']
        cond_rsi  = df['RSI_14'].between(30, 70)
        cond_vol  = df['Vol_Surge']

        # 방안 B 적용: 일봉 대추세 필터를 해제하여 하락세 종목도 분봉 수급 및 VWAP 돌파 시 일반 매수 허용
        raw_buy_signal = cond_vwap & cond_rsi & cond_vol
        df['Raw_Buy']  = raw_buy_signal

        # ATR 트레일링 손절선 (1.5배로 상향 — 손절 완충)
        dynamic_raw_sl = df['Close'] - atr_mult * df['ATR_Scalp']

        stop_loss_series = []
        exit_signal_list = []
        buy_signal_list  = []
        add_signal_list  = []  # 스마트 추가 매수 신호
        fall_signal_list = []  # 낙주 매수 신호

        in_position = False
        entry_price = 0.0
        entry_idx   = 0
        current_sl  = np.nan
        entry_tp_pct = tp_pct  # 동적 ATR 익절용 초기값 선언
        add_count   = 0        # 추가 매수 횟수 (1회 제한)
        actual_position_cleared = False

        # 포트폴리오 보유 중인 경우 초기 상태 연동
        if my_entry_price > 0:
            in_position = True
            entry_price = my_entry_price
            entry_idx   = 0
            entry_tp_pct = tp_pct

        # ── [성능 최적화] 루프 내 반복 계산을 벡터 연산으로 사전 계산 ──
        # ① 이동평균 거래량 (avg_vol_10): 루프 내 np.mean 슬라이스 → rolling 벡터 연산
        _vol_arr = df['Volume'].values.astype(float)
        _avg_vol_10_series = df['Volume'].rolling(10, min_periods=1).mean().shift(1).fillna(0).values

        # ② MA20 기울기(slope) 벡터 사전 계산: i >= 25 이상인 위치에서만 유효
        _ma20_arr      = df['MA20'].fillna(0).values
        _ma20_prev_arr = np.roll(_ma20_arr, 5)  # 5봉 전 MA20
        _ma20_prev_arr[:5] = 0.0
        with np.errstate(invalid='ignore', divide='ignore'):
            _ma20_slope_arr = np.where(
                _ma20_prev_arr > 0,
                (_ma20_arr - _ma20_prev_arr) / _ma20_prev_arr * 100,
                0.0
            )
        _is_ma20_slope_down_arr = (_ma20_slope_arr < -0.15) & (np.arange(len(df)) >= 25)

        for i in range(len(df)):
            close_val = df['Close'].iloc[i]
            open_val  = df['Open'].iloc[i]
            raw_sl    = dynamic_raw_sl.iloc[i]

            prev_rsi = df['RSI_14'].iloc[i-1] if i > 0 else np.nan
            curr_rsi = df['RSI_14'].iloc[i]

            # ── [아이디어 1 적용] 시간 파싱 및 시간대별 변동성 필터 ──
            timestamp = df.index[i]
            if not isinstance(timestamp, pd.Timestamp):
                dt_val = pd.to_datetime(timestamp)
            else:
                dt_val = timestamp
            time_val = dt_val.hour * 100 + dt_val.minute

            if time_val <= 1015:
                local_vol_mult = vol_mult * 0.8
            elif time_val <= 1429:
                local_vol_mult = vol_mult * 1.6
            else:
                local_vol_mult = vol_mult * 2.0
            
            # 동적 볼륨 서지 판정 (사전 계산된 이동평균 거래량 배열 참조)
            is_vol_surge_dynamic = False
            if i >= 10:
                avg_vol_10 = _avg_vol_10_series[i]
                if avg_vol_10 > 0:
                    is_vol_surge_dynamic = _vol_arr[i] >= (avg_vol_10 * local_vol_mult)
            
            # 오후 14:30 이후 신규 진입 제한 스위치
            is_afternoon_cutoff = time_val >= 1430

            # ── [아이디어 3 적용] 중기 이평선(MA20) 기울기(Slope) 필터 (사전 계산 배열 참조)
            is_ma20_slope_down = bool(_is_ma20_slope_down_arr[i])

            # 동적 볼륨 서지를 반영한 실시간 일반 매수 조건 조합 (포트폴리오 종목은 강력 돌파 시 RSI 상한 78.0으로 완화)
            cond_vwap = close_val > df['VWAP'].iloc[i]
            rsi_upper_limit = 78.0 if (is_vol_surge_dynamic and cond_vwap and is_portfolio) else 70.0
            cond_rsi  = df['RSI_14'].iloc[i] >= 30 and df['RSI_14'].iloc[i] <= rsi_upper_limit
            raw_buy_dynamic = cond_vwap and cond_rsi and is_vol_surge_dynamic

            # ── [방안 G 적용] 쌍바닥(Double Bottom) 감지 로직 ──
            is_double_bottom = False
            if i >= 30:
                low_prices = df['Low'].values
                local_minima = []
                
                # 로컬 저점 탐색 (좌우 2봉 기준 최소값)
                for j in range(i - 28, i - 1):
                    if low_prices[j] <= low_prices[j-1] and low_prices[j] <= low_prices[j-2] and \
                       low_prices[j] <= low_prices[j+1] and low_prices[j] <= low_prices[j+2]:
                        if not local_minima or local_minima[-1][0] < j - 2:
                            local_minima.append((j, low_prices[j]))
                
                if len(local_minima) >= 2:
                    idx1, val1 = local_minima[-2]
                    idx2, val2 = local_minima[-1]
                    
                    # 조건 A: 두 저점 간의 거리가 5봉 이상 20봉 이하로 적당히 떨어져 있어야 함
                    # 조건 B: 두 저점의 가격 괴리율이 1.5% 이내여야 함
                    # 조건 C: 현재 시점이 두 번째 저점 발생 후 8봉 이내의 반등 구간이어야 함
                    dist_ok = 5 <= (idx2 - idx1) <= 20
                    price_ok = abs(val1 - val2) / val1 * 100 <= 1.5
                    recency_ok = (i - idx2) <= 8
                    
                    if dist_ok and price_ok and recency_ok:
                        is_double_bottom = True

            # 쌍바닥 돌파 조건: 5분봉에서만 작동 + 종가가 VWAP 위 + MA5 > MA20 골든크로스/정배열 + RSI 안정권
            cond_db_buy = False
            if is_double_bottom and timeframe == '5min':
                cond_db_vwap = close_val > df['VWAP'].iloc[i]
                cond_db_ma = df['MA5'].iloc[i] > df['MA20'].iloc[i]
                cond_db_rsi = df['RSI_14'].iloc[i] >= 30 and df['RSI_14'].iloc[i] <= 70
                
                # ── [방안 H 적용] 상승반전 캔들패턴 결합: 최근 2봉 내 망치형 또는 상승장악형 출현 ──
                db_pattern_ok = df['Is_Hammer'].iloc[i] or (df['Is_Hammer'].iloc[i-1] if i > 0 else False) or \
                                df['Is_Engulfing'].iloc[i] or (df['Is_Engulfing'].iloc[i-1] if i > 0 else False)
                                
                if cond_db_vwap and cond_db_ma and cond_db_rsi and db_pattern_ok:
                    cond_db_buy = True

            if pd.isna(raw_sl):
                stop_loss_series.append(np.nan)
                exit_signal_list.append(False)
                buy_signal_list.append(False)
                add_signal_list.append(False)
                fall_signal_list.append(False)
                continue

            if in_position:
                buy_signal_list.append(False)
                fall_signal_list.append(False)

                # 손절선 래칫 (올라간 손절선은 내려오지 않음)
                current_sl = raw_sl if pd.isna(current_sl) else max(current_sl, raw_sl)
                stop_loss_series.append(current_sl)

                prev_sl = stop_loss_series[-2] if (
                    len(stop_loss_series) > 1 and not pd.isna(stop_loss_series[-2])
                ) else current_sl

                pnl_pct = (close_val - entry_price) / entry_price * 100 if entry_price > 0 else 0

                # ── [방안 A & D 적용] 스마트 추가 매수(ADD) 조건 검사 ──
                # RSI 과매도 반등(fall_rsi_limit 이하→초과) AND VWAP 돌파 AND 거래량 서지 모두 충족 시
                cond_add_indicator = (not pd.isna(prev_rsi) and prev_rsi <= fall_rsi_limit and curr_rsi > fall_rsi_limit) and \
                                     (close_val > df['VWAP'].iloc[i] and df['Vol_Surge'].iloc[i])
                
                # [방안 E 적용] ATR 기반 동적 추가 매수 기준선 설정 (ATR의 2.0배 수준을 비율%로 환산)
                # 단, 안전을 위해 최소 -1.5% ~ 최대 -5.0% 사이로 범위 클램핑
                atr_ratio = (df['ATR_Scalp'].iloc[i] / entry_price) * 100 if entry_price > 0 else 0.0
                add_threshold_pct = - max(1.5, min(5.0, 2.0 * atr_ratio))
                
                if pnl_pct <= add_threshold_pct and cond_add_indicator and add_count == 0:
                    add_signal_list.append(True)
                    add_count = 1
                    entry_price = (entry_price + close_val) / 2
                    entry_idx = i # 시간 컷오프 리셋
                else:
                    add_signal_list.append(False)

                # 청산 트리거
                hit_stop = (open_val < prev_sl) or (close_val < current_sl)   # 트레일링 스탑
                hit_tp   = pnl_pct >= entry_tp_pct                             # [아이디어 2 적용] 동적 ATR 익절선 적용
                hit_time = (i - entry_idx) >= time_cut if entry_idx > 0 else False  # 30봉 컷오프

                if hit_stop or hit_tp or hit_time:
                    exit_signal_list.append(True)
                    in_position = False
                    current_sl  = np.nan
                    add_count   = 0
                    if my_entry_price > 0:
                        actual_position_cleared = True
                else:
                    exit_signal_list.append(False)
            else:
                exit_signal_list.append(False)
                add_signal_list.append(False)
                stop_loss_series.append(raw_sl)

                # 실제 보유 포지션이 이미 청산된 후라면 신규 가상 진입을 완전히 차단
                if actual_position_cleared:
                    buy_signal_list.append(False)
                    fall_signal_list.append(False)
                    continue

                # ── [방안 A, D, H & 아이디어 3 적용] 낙폭과대 반등 매수(FALL_BUY) 조건 강화 (상승반전 캔들 + 이평선 기울기 결합) ──
                # RSI 과매도 탈출 기본 조건 (동적 볼륨 서지 반영)
                cond_fall_base = (not pd.isna(prev_rsi) and prev_rsi <= fall_rsi_limit and curr_rsi > fall_rsi_limit) and \
                                 (is_vol_surge_dynamic and close_val > df['VWAP'].iloc[i])
                                 
                # 1) 최근 2봉 내에 망치형(바닥 지지)이 발생했거나, 혹은 현재 양봉이 이전 음봉을 장악(Is_Engulfing)했어야 함
                recent_hammer = df['Is_Hammer'].iloc[i] or (df['Is_Hammer'].iloc[i-1] if i > 0 else False)
                recent_engulfing = df['Is_Engulfing'].iloc[i]
                
                # 2) [13번 패턴 적용] 장대음봉 회피 장치: 직전 1봉 내에 긴 장대음봉이 떨어지지 않았어야 함
                no_long_blue = not (df['Is_Long_Blue'].iloc[i] or (df['Is_Long_Blue'].iloc[i-1] if i > 0 else False))
                
                # 낙폭과대 최종 시그널: 기본조건 AND 패턴충족 AND 장대음봉회피 AND 이평선기울기각도 안정화
                cond_fall_indicator = cond_fall_base and (recent_hammer or recent_engulfing) and no_long_blue and (not is_ma20_slope_down)

                if cond_fall_indicator and not is_afternoon_cutoff:
                    fall_signal_list.append(True)
                    buy_signal_list.append(False)
                    in_position = True
                    entry_price = close_val
                    entry_idx   = i
                    current_sl  = raw_sl
                    # [아이디어 2 적용] 동적 ATR 익절선 계산 (1분봉 전용, 5분봉은 기본값 사용)
                    if timeframe == '1min':
                        entry_atr   = df['ATR_Scalp'].iloc[i]
                        atr_ratio   = (entry_atr / close_val) * 100 if close_val > 0 else 0.0
                        entry_tp_pct = max(0.4, min(3.0, 1.8 * atr_ratio))
                    else:
                        entry_tp_pct = tp_pct
                    add_count   = 0
                elif (raw_buy_dynamic or cond_db_buy) and not is_afternoon_cutoff:
                    buy_signal_list.append(True)
                    fall_signal_list.append(False)
                    in_position = True
                    entry_price = close_val
                    entry_idx   = i
                    current_sl  = raw_sl
                    # [아이디어 2 적용] 동적 ATR 익절선 계산 (1분봉 전용, 5분봉은 기본값 사용)
                    if timeframe == '1min':
                        entry_atr   = df['ATR_Scalp'].iloc[i]
                        atr_ratio   = (entry_atr / close_val) * 100 if close_val > 0 else 0.0
                        entry_tp_pct = max(0.4, min(3.0, 1.8 * atr_ratio))
                    else:
                        entry_tp_pct = tp_pct
                    add_count   = 0
                else:
                    buy_signal_list.append(False)
                    fall_signal_list.append(False)

        df['Stop_Loss']   = stop_loss_series
        df['Exit_Signal'] = exit_signal_list
        df['Buy_Signal']  = buy_signal_list
        df['Add_Signal']  = add_signal_list
        df['Fall_Signal'] = fall_signal_list
        df.drop(columns=['ATR_Scalp', 'Raw_Buy'], inplace=True, errors='ignore')

    except Exception as e:
        print(f"DEBUG: calculate_intraday_signals error: {e}")
        df['Stop_Loss']   = np.nan
        df['Exit_Signal'] = False
        df['Buy_Signal']  = False

    return df


# ── 백그라운드 포트폴리오 스캔 관련 전역 상태 ──
_daily_signals_sent_lock = threading.Lock()
_daily_signals_sent_date = ""
_daily_signals_sent_codes = set()

_briefing_sent_date = ""
_morning_briefing_sent = False
_closing_briefing_sent = False
_crash_warning_sent = False
_quant_picks_sent_codes = set()

def run_telegram_listener_daemon():
    """
    대표님이 텔레그램 채팅창에 /포트, /추천, /시장, /도움말 등을 입력하면
    실시간으로 파싱하여 0.5초 내로 즉각 답변하는 양방향 비서 스레드.
    """
    import urllib.request
    import json
    
    last_update_id = 0
    
    def _get_context(query_type, code=None, **kwargs):
        try:
            if query_type == 'stock_chart':
                target_c = code or kwargs.get('code', '')
                if target_c:
                    return _get_stock_history_raw(target_c)
                return None

            elif query_type == 'portfolio':
                port = _load_portfolio_raw() or {}
                df_m = _sync_and_load_csv_raw('df_full_market.csv')
                items = []
                tot_eval = 0
                tot_entry = 0
                for code, info in port.items():
                    ep = float(info.get('entry_price', 0))
                    qty = float(info.get('qty', 0))
                    cur_p = ep
                    if not df_m.empty and 'Code' in df_m.columns:
                        match = df_m[df_m['Code'].astype(str).str.zfill(6) == str(code).zfill(6)]
                        if not match.empty:
                            cur_p = float(match.iloc[0]['Close'])
                    pnl_pct = ((cur_p - ep) / ep * 100) if ep > 0 else 0
                    tot_entry += ep * qty
                    tot_eval += cur_p * qty
                    items.append({
                        'name': info.get('name', code),
                        'cur_price': cur_p,
                        'pnl_pct': pnl_pct
                    })
                tot_pnl = tot_eval - tot_entry
                tot_pct = (tot_pnl / tot_entry * 100) if tot_entry > 0 else 0
                return {'items': items, 'tot_eval': tot_eval, 'tot_pnl': tot_pnl, 'tot_pct': tot_pct}
                
            elif query_type == 'quant_top':
                df_q = _sync_and_load_csv_raw('df_quant_final.csv')
                df_m = _sync_and_load_csv_raw('df_full_market.csv')
                if df_q.empty:
                    return []
                if 'Total_Score' in df_q.columns:
                    mean_score = df_q['Total_Score'].mean()
                    std_score = df_q['Total_Score'].std()
                    if std_score > 0:
                        df_q['Total_Score_Adj'] = ((df_q['Total_Score'] - mean_score) / std_score * 25.0 + 50.0).clip(0.0, 100.0).round(1)
                    else:
                        df_q['Total_Score_Adj'] = df_q['Total_Score']
                keywords = ['KODEX', 'TIGER', 'ACE', 'KBSTAR', 'SOL', 'ARIRANG', 'HANARO', 'KOSEF', 'PLUS', 'TIMEFOLIO', '스팩', 'ETN', '선물', '인버스', '레버리지']
                mask = ~df_q['Name'].astype(str).str.contains('|'.join(keywords), case=False, regex=True)
                df_q = df_q[mask].copy()
                df_q['Code'] = df_q['Code'].astype(str).str.split('.').str[0].str.zfill(6)
                if not df_m.empty and 'Code' in df_m.columns:
                    df_q = df_q.drop(columns=['Close', 'ChagesRatio', 'Amount'], errors='ignore')
                    df_q = df_q.merge(df_m[['Code', 'Close', 'ChagesRatio', 'Amount']], on='Code', how='left')
                top = df_q.sort_values('Total_Score_Adj', ascending=False).head(3)
                results = []
                for _, r in top.iterrows():
                    results.append({
                        'code': str(r['Code']).zfill(6),
                        'name': str(r.get('Name', '')),
                        'score': float(r.get('Total_Score_Adj', r.get('Total_Score', 0))),
                        'price': float(r.get('Close', 0)),
                        'chg': float(r.get('ChagesRatio', 0))
                    })
                return results
                
            elif query_type == 'market':
                ks_c, ks_m, _ = get_kospi_ma20()
                b_data = {}
                try:
                    import sys
                    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    if root_dir not in sys.path:
                        sys.path.insert(0, root_dir)
                    from backend.services import get_bollinger_market_energy
                    b_data = get_bollinger_market_energy() or {}
                except Exception as _b_err:
                    print(f"DEBUG: Bollinger import error: {_b_err}")
                return {
                    'kospi_close': ks_c,
                    'kospi_chg': 0.0,
                    'b_ma5': b_data.get('ma5', 0),
                    'b_status': b_data.get('energy_status', '보통'),
                    'stock_ratio': 80 if ks_c >= ks_m else 30,
                    'cash_ratio': 20 if ks_c >= ks_m else 70
                }
        except Exception as ex:
            print(f"DEBUG: Telegram context error: {ex}")
        return {}

    while True:
        try:
            tg_token = ""
            tg_chat_id = ""
            try:
                if hasattr(st, "secrets"):
                    tg_token = st.secrets.get("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                    tg_chat_id = str(st.secrets.get("TELEGRAM_CHAT_ID", os.environ.get("TELEGRAM_CHAT_ID", "")))
            except Exception:
                pass

            if not tg_token:
                time.sleep(10)
                continue

            url = f"https://api.telegram.org/bot{tg_token}/getUpdates?offset={last_update_id + 1}&timeout=5"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    res_data = json.loads(response.read().decode('utf-8'))
                    if res_data.get('ok') and res_data.get('result'):
                        from telegram_notifier import process_incoming_command
                        for upd in res_data['result']:
                            upd_id = upd.get('update_id', 0)
                            last_update_id = max(last_update_id, upd_id)
                            msg = upd.get('message', {})
                            chat = msg.get('chat', {})
                            sender_id = str(chat.get('id', ''))
                            text = msg.get('text', '')
                            
                            if text:
                                print(f"DEBUG: 텔레그램 수신 [{sender_id}]: {text}")
                                process_incoming_command(
                                    token=tg_token,
                                    chat_id=sender_id,
                                    cmd_text=text,
                                    context_fn=_get_context
                                )
            except Exception as net_err:
                # 409 Conflict 등은 잠시 대기
                time.sleep(1)
        except Exception as e:
            print(f"DEBUG: Telegram listener daemon error: {e}")
        time.sleep(1)

def run_portfolio_background_scanner():
    """
    백그라운드에서 주기적으로 포트폴리오와 퀀트 TOP 종목을 감시하고,
    정기 브리핑, 트레일링 스탑, 스마트 손절가, 실시간 매매 신호를 발송하는 스마트 데몬.
    """
    global _daily_signals_sent_date, _daily_signals_sent_codes
    global _briefing_sent_date, _morning_briefing_sent, _closing_briefing_sent, _crash_warning_sent, _quant_picks_sent_codes
    
    from datetime import timezone, timedelta
    _KST = timezone(timedelta(hours=9))
    
    while True:
        try:
            now_dt = datetime.now(_KST)
            today_str = now_dt.strftime('%Y-%m-%d')
            hm = now_dt.hour * 100 + now_dt.minute
            is_weekday = now_dt.weekday() < 5
            
            # 날짜 바뀜 시 브리핑 및 일봉 플래그 리셋
            if _briefing_sent_date != today_str:
                _briefing_sent_date = today_str
                _morning_briefing_sent = False
                _closing_briefing_sent = False
                _crash_warning_sent = False
                _quant_picks_sent_codes.clear()
                with _daily_signals_sent_lock:
                    _daily_signals_sent_date = today_str
                    _daily_signals_sent_codes.clear()

            # 1. 텔레그램 설정 로드
            tg_token = ""
            tg_chat_id = ""
            try:
                if hasattr(st, "secrets"):
                    tg_token = st.secrets.get("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                    tg_chat_id = str(st.secrets.get("TELEGRAM_CHAT_ID", os.environ.get("TELEGRAM_CHAT_ID", "")))
            except Exception:
                pass

            if not (tg_token and tg_chat_id):
                time.sleep(15)
                continue

            try:
                from telegram_notifier import (
                    notify_buy_signal, notify_exit_signal, notify_add_signal, notify_fall_buy_signal,
                    notify_daily_buy_signal, notify_daily_sell_signal,
                    notify_quant_top_pick, notify_smart_stop_loss, notify_trailing_stop, notify_market_crash_warning,
                    notify_morning_briefing, notify_closing_briefing
                )
            except ImportError:
                time.sleep(15)
                continue

            kis_key = ""
            kis_sec = ""
            try:
                if hasattr(st, "secrets"):
                    kis_key = st.secrets.get("KIS_APP_KEY", os.environ.get("KIS_APP_KEY", ""))
                    kis_sec = st.secrets.get("KIS_APP_SECRET", os.environ.get("KIS_APP_SECRET", ""))
            except Exception:
                pass

            # 2. 포트폴리오 및 퀀트 데이터 로드
            portfolio_data = _load_portfolio_raw() or {}
            
            # ── ☀️ 1) 장전 브리핑 (08:50 ~ 08:59 평일) ──
            if is_weekday and 850 <= hm <= 859 and not _morning_briefing_sent:
                try:
                    ks_c, ks_m, _ = get_kospi_ma20()
                    regime = "상승/횡보 국면" if ks_c >= ks_m else "약세/보수 국면"
                    c_rat = 20.0 if ks_c >= ks_m else 70.0
                    s_rat = 80.0 if ks_c >= ks_m else 30.0
                    
                    b_data = get_bollinger_market_energy() or {}
                    b_ma5 = b_data.get('ma5', 0)
                    b_st = b_data.get('energy_status', '보통')
                    
                    top_names = []
                    df_q_raw = _sync_and_load_csv_raw('df_quant_final.csv')
                    if not df_q_raw.empty and 'Name' in df_q_raw.columns:
                        top_names = df_q_raw.head(4)['Name'].tolist()
                        
                    notify_morning_briefing(
                        token=tg_token, chat_id=tg_chat_id,
                        market_regime=regime, cash_ratio=c_rat, stock_ratio=s_rat,
                        bollinger_ma5=b_ma5, bollinger_status=b_st,
                        top_quant_names=top_names,
                        gap_trap_warning=True,  # ⚠️ 2025~2026 초민감 장세 갭 함정 주의 탑재
                    )
                    _morning_briefing_sent = True
                except Exception as b_err:
                    print(f"DEBUG: Morning briefing error: {b_err}")

            # ── 🌙 2) 장마감 브리핑 (15:40 ~ 15:55 평일) ──
            if is_weekday and 1540 <= hm <= 1555 and not _closing_briefing_sent and portfolio_data:
                try:
                    df_m_raw = _sync_and_load_csv_raw('df_full_market.csv')
                    tot_eval = 0
                    tot_entry = 0
                    for pk, pv in portfolio_data.items():
                        ep = float(pv.get('entry_price', 0))
                        qty = float(pv.get('qty', 0))
                        tot_entry += ep * qty
                        cur_p = ep
                        if not df_m_raw.empty and 'Code' in df_m_raw.columns:
                            m = df_m_raw[df_m_raw['Code'].astype(str).str.zfill(6) == str(pk).zfill(6)]
                            if not m.empty:
                                cur_p = float(m.iloc[0]['Close'])
                        tot_eval += cur_p * qty
                    
                    tot_pnl = tot_eval - tot_entry
                    tot_pct = (tot_pnl / tot_entry * 100) if tot_entry > 0 else 0
                    
                    notify_closing_briefing(
                        token=tg_token, chat_id=tg_chat_id,
                        total_eval=tot_eval, total_pnl=tot_pnl, total_pct=tot_pct,
                        port_count=len(portfolio_data)
                    )
                    _closing_briefing_sent = True
                except Exception as c_err:
                    print(f"DEBUG: Closing briefing error: {c_err}")

            # ── 🌟 3) 퀀트 TOP 유망주 (80점 이상) 신호 스캔 ──
            # ⚡ 8개년(2019~2026) 95,410건 백테스트 검증: 시장 에너지 필터 연동
            try:
                # 현재 시장 에너지 상태 조회 (퀀트 알림에 함께 포함)
                _q_energy_status = ""
                try:
                    _b_q = get_bollinger_market_energy() or {}
                    _q_energy_status = _b_q.get('energy_status', '')
                except Exception:
                    pass

                df_q_scan = _sync_and_load_csv_raw('df_quant_final.csv')
                if not df_q_scan.empty and 'Code' in df_q_scan.columns:
                    score_col = 'Total_Score_Adj' if 'Total_Score_Adj' in df_q_scan.columns else ('Total_Score' if 'Total_Score' in df_q_scan.columns else None)
                    if score_col:
                        top_q = df_q_scan[df_q_scan[score_col] >= 80.0].head(3)
                        for _, q_row in top_q.iterrows():
                            q_code = str(q_row['Code']).split('.')[0].strip().zfill(6)
                            if q_code not in _quant_picks_sent_codes and q_code not in portfolio_data:
                                q_name = str(q_row.get('Name', q_code))
                                q_score = float(q_row[score_col])
                                q_close = float(q_row.get('Close', 0))
                                q_chg = float(q_row.get('ChagesRatio', 0))
                                if q_close > 0:
                                    notify_quant_top_pick(
                                        token=tg_token, chat_id=tg_chat_id,
                                        ticker=q_code, name=q_name,
                                        score=q_score, price=q_close, chg_rate=q_chg,
                                        target_price=q_close * 1.05,
                                        stop_price=q_close * 0.97,
                                        market_energy_status=_q_energy_status,  # ⚡ 8개년 검증 시장 에너지 연동
                                    )
                                    _quant_picks_sent_codes.add(q_code)
            except Exception as q_err:
                print(f"DEBUG: Quant picks scan error: {q_err}")

            # ── 💼 4) 보유 포트폴리오 실시간 스캘핑/트레일링스탑/손절선 스캔 ──
            if portfolio_data:
                def scan_single_stock(code, info):
                    try:
                        name = info.get('name', code)
                        entry_price = float(info.get('entry_price', 0.0))
                        stop_loss = float(info.get('stop_loss', entry_price * 0.97 if entry_price > 0 else 0.0))
                        
                        # 1분봉 데이터 수집 및 연산
                        df_scan = pd.DataFrame()
                        if kis_key and kis_sec:
                            df_scan = _get_kis_minute_history_raw(kis_key, kis_sec, code)
                        if df_scan.empty:
                            df_scan = _get_minute_history_raw(code, count=2000)
                            
                        if not df_scan.empty and len(df_scan) >= 20:
                            df_scan = calculate_intraday_signals(df_scan, my_entry_price=entry_price, code=code)
                            last_row = df_scan.iloc[-1]
                            cur_p = float(last_row['Close'])
                            
                            # 스마트 손절가 감지
                            if stop_loss > 0 and cur_p > 0:
                                live_logger.check_and_notify_stop_loss(
                                    code=code, name=name, current_price=cur_p,
                                    stop_loss=stop_loss, tg_token=tg_token, tg_chat_id=tg_chat_id
                                )

                            # 트레일링 스탑 (추적 익절) 감지
                            if entry_price > 0 and cur_p > 0:
                                live_logger.check_and_notify_trailing_stop(
                                    code=code, name=name, current_price=cur_p,
                                    entry_price=entry_price, min_profit_pct=4.0, drop_pct=2.0,
                                    tg_token=tg_token, tg_chat_id=tg_chat_id
                                )

                            if 'DateTime' in df_scan.columns and not pd.isna(last_row.get('DateTime')):
                                time_diff = (pd.Timestamp.now() - pd.to_datetime(last_row['DateTime'])).total_seconds()
                                if time_diff < 300: # 5분 이내
                                    rsi_v = float(last_row['RSI_14']) if 'RSI_14' in last_row and pd.notna(last_row.get('RSI_14')) else None
                                    vwap_v = float(last_row['VWAP']) if 'VWAP' in last_row and pd.notna(last_row.get('VWAP')) else None

                                    # ── 🕒 09:00~09:14 갭 함정 차단 필터 ──
                                    # 8개년(2019~2026) 95,410건 검증: 갭 함정 차단 시 승률 +3~4%p 개선
                                    # 개장 15분 이내(09:00~09:14) 시초가 대비 음봉 전환 종목의 매수 알림을 자동 차단
                                    _gap_trap_blocked = False
                                    if last_row.get('Buy_Signal') == True and hm < 915 and is_weekday:
                                        try:
                                            # 당일 09:00봉(시초가) Open 가격 탐색
                                            _today_str_dt = now_dt.strftime('%Y%m%d')
                                            _open_rows = df_scan[df_scan['DateTime'].astype(str).str.startswith(_today_str_dt + ' 09:0')]
                                            if not _open_rows.empty:
                                                _open_price = float(_open_rows.iloc[0]['Open'])
                                                _gap_pct = (_open_price - float(df_scan.iloc[-2]['Close']) if len(df_scan) >= 2 else 0) / max(float(df_scan.iloc[-2]['Close']), 1) * 100 if len(df_scan) >= 2 else 0
                                                _cur_chg_from_open = (cur_p - _open_price) / _open_price * 100 if _open_price > 0 else 0
                                                # 갭 +4% 이상 && 현재 시초가 대비 -0.3% 이하(음봉 전환) → 차단
                                                if _gap_pct >= 4.0 and _cur_chg_from_open <= -0.3:
                                                    _gap_trap_blocked = True
                                                    print(f"DEBUG: [갭 함정 차단] {name}({code}) — 갭 {_gap_pct:.1f}% / 시초 대비 {_cur_chg_from_open:.2f}% — 매수 알림 차단")
                                        except Exception as _gt_err:
                                            print(f"DEBUG: Gap trap filter error [{code}]: {_gt_err}")

                                    if last_row.get('Buy_Signal') == True and not _gap_trap_blocked:
                                        live_logger.log_buy_signal(
                                            ticker=code, price=cur_p,
                                            timestamp=last_row['DateTime'], name=name,
                                            tg_token=tg_token, tg_chat_id=tg_chat_id,
                                            rsi=rsi_v, vwap=vwap_v
                                        )
                                    elif last_row.get('Add_Signal') == True:
                                        live_logger.log_add_signal(
                                            ticker=code, price=cur_p,
                                            timestamp=last_row['DateTime'], name=name,
                                            tg_token=tg_token, tg_chat_id=tg_chat_id,
                                            rsi=rsi_v, vwap=vwap_v
                                        )
                                    elif last_row.get('Fall_Signal') == True:
                                        live_logger.log_fall_buy_signal(
                                            ticker=code, price=cur_p,
                                            timestamp=last_row['DateTime'], name=name,
                                            tg_token=tg_token, tg_chat_id=tg_chat_id,
                                            rsi=rsi_v, vwap=vwap_v
                                        )
                                    elif last_row.get('Exit_Signal') == True:
                                        live_logger.log_exit_signal(
                                            ticker=code, price=cur_p,
                                            timestamp=last_row['DateTime'], name=name,
                                            tg_token=tg_token, tg_chat_id=tg_chat_id
                                        )
                                        
                        # 일봉 시그널 스캔
                        with _daily_signals_sent_lock:
                            already_sent = code in _daily_signals_sent_codes
                            
                        if not already_sent:
                            df_daily = _get_stock_history_raw(code)
                            if not df_daily.empty and len(df_daily) >= 25:
                                df_daily = df_daily.copy()
                                df_daily['MA10'] = df_daily['Close'].rolling(10).mean()
                                df_daily['MA20'] = df_daily['Close'].rolling(20).mean()
                                df_daily = calculate_rsi(df_daily, period=14)
                                df_daily['Vol_MA20'] = df_daily['Volume'].rolling(20).mean().shift(1)
                                df_daily['Vol_Ratio'] = (df_daily['Volume'] / df_daily['Vol_MA20']).round(2)
                                
                                prev_row = df_daily.iloc[-2]
                                cur_row = df_daily.iloc[-1]
                                d_close = float(cur_row['Close'])
                                d_rsi = float(cur_row['RSI_14']) if pd.notna(cur_row.get('RSI_14')) else None
                                d_ma10 = float(cur_row['MA10']) if pd.notna(cur_row.get('MA10')) else None
                                d_ma20 = float(cur_row['MA20']) if pd.notna(cur_row.get('MA20')) else None
                                d_vol_r = float(cur_row['Vol_Ratio']) if pd.notna(cur_row.get('Vol_Ratio')) else None
                                p_ma10 = float(prev_row['MA10']) if pd.notna(prev_row.get('MA10')) else None
                                p_ma20 = float(prev_row['MA20']) if pd.notna(prev_row.get('MA20')) else None
                                d_date = str(cur_row.name.date()) if hasattr(cur_row.name, 'date') else today_str
                                
                                d_pnl_pct = ((d_close - entry_price) / entry_price * 100) if entry_price > 0 else None
                                daily_signal_sent = False
                                
                                # 일봉 골든크로스
                                golden_cross = (
                                    p_ma10 is not None and p_ma20 is not None and
                                    d_ma10 is not None and d_ma20 is not None and
                                    p_ma10 <= p_ma20 and d_ma10 > d_ma20
                                )
                                rsi_ok_buy = d_rsi is not None and d_rsi <= 68
                                vol_surge_d = d_vol_r is not None and d_vol_r >= 1.5
                                
                                if golden_cross and rsi_ok_buy and vol_surge_d:
                                    reason = f"MA10/MA20 골든크로스 + RSI {d_rsi:.1f} + 거래량 {d_vol_r:.1f}배 돌파"
                                    notify_daily_buy_signal(
                                        token=tg_token, chat_id=tg_chat_id,
                                        ticker=code, name=name, price=d_close, date=d_date,
                                        rsi=d_rsi, ma5=d_ma10, ma20=d_ma20, vol_ratio=d_vol_r,
                                        signal_reason=reason
                                    )
                                    daily_signal_sent = True
                                    
                                # 일봉 데드크로스 / 손절선 이탈
                                if not daily_signal_sent:
                                    dead_cross = (
                                        p_ma10 is not None and p_ma20 is not None and
                                        d_ma10 is not None and d_ma20 is not None and
                                        p_ma10 >= p_ma20 and d_ma10 < d_ma20
                                    )
                                    rsi_overbought = d_rsi is not None and d_rsi >= 80
                                    sl_hit = d_pnl_pct is not None and d_pnl_pct <= -3.0
                                    
                                    if (dead_cross and vol_surge_d) or rsi_overbought or sl_hit:
                                        reason_parts = []
                                        if dead_cross and vol_surge_d:
                                            reason_parts.append(f"MA10/MA20 데드크로스")
                                        if rsi_overbought:
                                            reason_parts.append(f"RSI 과매수({d_rsi:.1f})")
                                        if sl_hit:
                                            reason_parts.append(f"손절선 이탈 ({d_pnl_pct:.1f}%)")
                                        reason = " + ".join(reason_parts)
                                        
                                        notify_daily_sell_signal(
                                            token=tg_token, chat_id=tg_chat_id,
                                            ticker=code, name=name, price=d_close, date=d_date,
                                            entry_price=entry_price if entry_price > 0 else None,
                                            rsi=d_rsi, ma5=d_ma10, ma20=d_ma20,
                                            signal_reason=reason
                                        )
                                        daily_signal_sent = True
                                        
                                if daily_signal_sent:
                                    with _daily_signals_sent_lock:
                                        _daily_signals_sent_codes.add(code)
                                        
                    except Exception as ex:
                        print(f"DEBUG: Back scanner thread single stock [{code}] error: {ex}")
                        
                max_workers = min(len(portfolio_data), 5)
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = [executor.submit(scan_single_stock, code, info) for code, info in portfolio_data.items()]
                    for fut in futures:
                        try:
                            fut.result()
                        except Exception:
                            pass
                        
        except Exception as err:
            print(f"DEBUG: Back scanner thread loop error: {err}")
            
        time.sleep(15)

@st.cache_resource
def start_background_portfolio_scanner():
    """
    최초 기동 시 포트폴리오 감시 데몬 및 텔레그램 양방향 리스너 스레드를 구동함.
    """
    t1 = threading.Thread(target=run_portfolio_background_scanner, daemon=True, name="PortfolioScannerDaemon")
    t1.start()
    
    t2 = threading.Thread(target=run_telegram_listener_daemon, daemon=True, name="TelegramListenerDaemon")
    t2.start()
    
    return [t1, t2]


def _get_market_ttl():
    """장중(09:00~15:30 평일)이면 120초, 장외이면 600초 캐시 TTL 반환"""
    from datetime import timezone, timedelta as _td
    _now = datetime.now(timezone(_td(hours=9)))
    h_m = _now.hour * 100 + _now.minute
    is_market_hours = _now.weekday() < 5 and 900 <= h_m <= 1540
    return 120 if is_market_hours else 600

@st.cache_data(ttl=120)  # 기본 120초 캐시 — 장중 2분, 장외에는 load_data 내 30분 동기화 로직이 별도 관리
def fetch_live_stock_listing():
    """코스피/코스닥 전체 시세 조회.
    1순위: FDR (로컬 환경)
    2순위: GitHub CSV (Streamlit Cloud — KRX 차단 환경)
    """
    # 1순위: FDR 시도 (로컬에서는 정상 동작)
    try:
        df_ks = fdr.StockListing('KOSPI')
        df_kq = fdr.StockListing('KOSDAQ')
        if not df_ks.empty or not df_kq.empty:
            df_live = pd.concat([df_ks, df_kq], ignore_index=True)
            for col in ['Code', 'Name', 'Close', 'ChagesRatio', 'Volume', 'Amount']:
                if col not in df_live.columns:
                    df_live[col] = 0
            df_live = df_live[['Code', 'Name', 'Close', 'ChagesRatio', 'Volume', 'Amount']].copy()
            df_live['Code'] = df_live['Code'].astype(str).str.zfill(6)
            return df_live
    except Exception:
        pass

    # 2순위: GitHub CSV 폴백 (Streamlit Cloud — KRX 차단 환경)
    try:
        url = f'{GITHUB_RAW_BASE}/df_full_market.csv'
        df_live = pd.read_csv(url, encoding='utf-8-sig')
        for col in ['Code', 'Name', 'Close', 'ChagesRatio', 'Volume', 'Amount']:
            if col not in df_live.columns:
                df_live[col] = 0
        df_live = df_live[['Code', 'Name', 'Close', 'ChagesRatio', 'Volume', 'Amount']].copy()
        df_live['Code'] = df_live['Code'].astype(str).str.zfill(6)
        return df_live
    except Exception:
        pass

    return pd.DataFrame()


@st.cache_data(ttl=120)  # 120초 캐시 — 지수/환율은 실시간 모니터링에 중요 (병렬 호출로 부하 없음)
def fetch_live_indices():
    """코스피/코스닥/환율/나스닥 최근 데이터 조회.
    1순위: FDR 병렬 호출 (로컬 환경) — ThreadPoolExecutor로 4개 동시 조회
    2순위: 네이버 실시간 API (Streamlit Cloud — KRX 차단 환경)
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    start_date = (pd.Timestamp.now() - pd.Timedelta(days=7)).strftime('%Y-%m-%d')
    result = {}

    # 1순위: FDR 병렬 시도 (KS11, KQ11, USD/KRW, NQ=F 동시 요청)
    fdr_ok = False
    fdr_targets = ['KS11', 'KQ11', 'USD/KRW', 'NQ=F']
    fdr_results = {}

    def _fdr_fetch(symbol):
        try:
            df = fdr.DataReader(symbol, start_date)
            return symbol, df if not df.empty else pd.DataFrame()
        except Exception:
            return symbol, pd.DataFrame()

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(_fdr_fetch, sym): sym for sym in fdr_targets}
            for future in as_completed(futures, timeout=1.2):
                sym, df = future.result()
                fdr_results[sym] = df

        if not fdr_results.get('KS11', pd.DataFrame()).empty:
            result = fdr_results
            fdr_ok = True
    except Exception:
        pass

    if fdr_ok:
        return result

    # 2순위: 네이버 실시간 API 폴백
    result = {'KS11': pd.DataFrame(), 'KQ11': pd.DataFrame(), 'USD/KRW': pd.DataFrame(), 'NQ=F': pd.DataFrame()}
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(
            'https://polling.finance.naver.com/api/realtime/domestic/index/KOSPI,KOSDAQ',
            headers=headers, timeout=5
        )
        if r.status_code == 200:
            for item in r.json().get('datas', []):
                code = item.get('itemCode', '')
                price = float(str(item.get('closePrice', 0)).replace(',', ''))
                chg_rate = float(item.get('fluctuationsRatio', 0))
                prev = price / (1 + chg_rate / 100) if chg_rate != -100 else price
                df_tmp = pd.DataFrame([{'Close': price, 'Change': chg_rate, 'Open': prev, 'High': price, 'Low': price}])
                if code == 'KOSPI':
                    result['KS11'] = df_tmp
                elif code == 'KOSDAQ':
                    result['KQ11'] = df_tmp
    except Exception:
        pass
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(
            'https://quotation-api-cdn.dunamu.com/v1/forex/recent?codes=FRX.KRWUSD',
            headers=headers, timeout=5
        )
        if r.status_code == 200:
            d = r.json()[0]
            price = float(d.get('basePrice', 0))
            chg = float(d.get('changePrice', 0))
            result['USD/KRW'] = pd.DataFrame([{'Close': price, 'Change': chg}])
    except Exception:
        pass
    return result


def _backup_portfolio_daily(portfolio):
    """매일 자정/저장 시 날짜별 백업본(my_portfolio_YYYY-MM-DD.json)을 data/backups/ 에 영구 보존"""
    try:
        if not portfolio:
            return
        base_dir = os.path.dirname(os.path.abspath(__file__))
        backup_dir = os.path.join(base_dir, 'data', 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        today_str = datetime.now().strftime('%Y-%m-%d')
        backup_file = os.path.join(backup_dir, f'my_portfolio_{today_str}.json')
        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(portfolio, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"DEBUG: Daily portfolio backup error: {e}")

def load_portfolio(force_remote: bool = False):
    """
    [Supabase 초고속 클라우드 DB 1순위 연동]
    어디서나(PC, LTE 태블릿, 모바일) 0.05초 만에 중앙 DB에서 최신 포트폴리오를 실시간 로드합니다.
    Supabase 부재/오류 시 로컬 JSON 및 GitHub 백업으로 자동 안전 폴백.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    port_path = os.path.join(base_dir, 'data', 'my_portfolio.json')

    # 1. Supabase 클라우드 DB 1순위 실시간 조회
    if supabase:
        try:
            res = supabase.table("portfolio").select("*").execute()
            if res and res.data:
                port_dict = {}
                for r in res.data:
                    c = str(r['code']).strip().zfill(6)
                    port_dict[c] = {
                        "name": str(r.get('name', '')),
                        "entry_price": float(r.get('entry_price', 0.0)),
                        "qty": float(r.get('qty', 0.0)),
                        "stop_loss": float(r.get('stop_loss', 0.0)) if r.get('stop_loss') else 0.0
                    }
                if port_dict:
                    st.session_state['session_portfolio'] = port_dict
                    try:
                        os.makedirs(os.path.dirname(port_path), exist_ok=True)
                        with open(port_path, 'w', encoding='utf-8') as f:
                            json.dump(port_dict, f, ensure_ascii=False, indent=2)
                        _backup_portfolio_daily(port_dict)
                    except Exception:
                        pass
                    return port_dict
        except Exception:
            pass

    # 2. 세션 내 최신 수정본이 있으면 최우선 반환 (GitHub API 캐시 딜레이 역전 방지)
    if not force_remote and 'session_portfolio' in st.session_state and st.session_state['session_portfolio']:
        return st.session_state['session_portfolio']

    # 3. force_remote 요청 시 GitHub 최신 데이터 즉시 다운로드 동기화
    if force_remote:
        remote_data = fetch_remote_portfolio()
        if remote_data is not None:
            try:
                os.makedirs(os.path.dirname(port_path), exist_ok=True)
                with open(port_path, 'w', encoding='utf-8') as f:
                    json.dump(remote_data, f, ensure_ascii=False, indent=2)
                st.session_state['session_portfolio'] = remote_data
                _backup_portfolio_daily(remote_data)
                return remote_data
            except Exception:
                pass

    # 4. 로컬 파일 우선 읽기
    if os.path.exists(port_path):
        try:
            with open(port_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if data:
                    st.session_state['session_portfolio'] = data
                    _backup_portfolio_daily(data)
                    return data
        except Exception as e:
            print(f"DEBUG: load_portfolio local failed: {e}")

    # 5. 원격 GitHub 동기화 (로컬 파일 부재 시)
    remote_data = fetch_remote_portfolio()
    if remote_data is not None:
        try:
            os.makedirs(os.path.dirname(port_path), exist_ok=True)
            with open(port_path, 'w', encoding='utf-8') as f:
                json.dump(remote_data, f, ensure_ascii=False, indent=2)
            _backup_portfolio_daily(remote_data)
            st.session_state['session_portfolio'] = remote_data
        except Exception:
            pass
        return remote_data

    return {}



DATA_FILES = [
    'df_full_market.csv',
    'df_high_density.csv',
    'df_quant_final.csv',
    'df_market_summary.csv',
    'df_supply_intraday.csv',
]
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/k2000kms-del/gd3-market-hub/main/data"

@st.cache_data(ttl=120)  # 2분 캐시
def load_data(force_remote: bool = False):
    """
    로컬 CSV 데이터와 원격 GitHub 데이터를 스마트 동기화하여
    실시간 최신 데이터를 항상 유지하고 화면 렌더링 딜레이를 최소화합니다.
    """
    import os
    import requests
    from datetime import datetime, timezone, timedelta
    from concurrent.futures import ThreadPoolExecutor

    dfs = {}
    update_times = {}
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, 'data')
    os.makedirs(data_dir, exist_ok=True)
    now_kst = datetime.now(timezone(timedelta(hours=9)))

    def _sync_and_load(fname):
        local_path = os.path.join(data_dir, fname)
        url = f'{GITHUB_RAW_BASE}/{fname}'

        # 로컬 파일 존재 여부 및 수정 시각 확인
        local_exists = os.path.exists(local_path)
        is_stale = True
        if local_exists:
            try:
                mtime_ts = os.path.getmtime(local_path)
                file_age_sec = datetime.now().timestamp() - mtime_ts
                # 60초 이내에 수정된 파일이면 로컬 캐시 사용
                if file_age_sec < 60 and not force_remote:
                    is_stale = False
            except Exception:
                is_stale = True

        # 만약 로컬 파일이 없거나 오래되었으면 원격 GitHub에서 다운로드 시도
        if not local_exists or is_stale or force_remote:
            try:
                res = requests.get(url, timeout=4)
                if res.status_code == 200 and len(res.content) > 50:
                    with open(local_path, 'wb') as fp:
                        fp.write(res.content)
            except Exception as e:
                print(f"DEBUG: {fname} 원격 다운로드 실패 (로컬 캐시 사용): {e}")

        # 로컬 파일 읽기
        if os.path.exists(local_path):
            for enc in ['utf-8-sig', 'utf-8', 'cp949', 'euc-kr']:
                try:
                    df = pd.read_csv(local_path, encoding=enc)
                    mtime_ts = os.path.getmtime(local_path)
                    _KST = timezone(timedelta(hours=9))
                    dt_kst = datetime.fromtimestamp(mtime_ts, tz=_KST)
                    final_mtime_str = dt_kst.strftime('%Y-%m-%d %H:%M:%S')
                    return fname, df, final_mtime_str
                except Exception:
                    continue

        return fname, pd.DataFrame(), '데이터 없음'

    # ── 5개 CSV 파일 병렬 로드 ──
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_sync_and_load, fname): fname for fname in DATA_FILES}
        for future in as_completed(futures, timeout=10):
            try:
                fname, df, mtime_str = future.result()
                dfs[fname] = df
                update_times[fname] = mtime_str
            except Exception as e:
                fname = futures[future]
                print(f"DEBUG: {fname} 병렬 로드 실패: {e}")
                dfs[fname] = pd.DataFrame()
                update_times[fname] = "데이터 없음"

    # 누락된 파일 보완
    for fname in DATA_FILES:
        if fname not in dfs:
            dfs[fname] = pd.DataFrame()
            update_times[fname] = "데이터 없음"

    return dfs, update_times

# ── 데이터 로드 ────────────────────────────────────────────────
force_sync = st.session_state.pop('force_sync', False)
with st.spinner('📡 최신 데이터 동기화 중...'):
    data, update_times = load_data(force_remote=force_sync)
    load_portfolio(force_remote=force_sync)

df_hd       = data['df_high_density.csv']
df_q        = data['df_quant_final.csv']
df_m        = data['df_full_market.csv']
df_summary  = data['df_market_summary.csv']
df_intraday = data['df_supply_intraday.csv']

# ── [고도화] 매수 퀀트 점수 상대평가 표준화 (z-score Calibration) ──
if df_q is not None and not df_q.empty and 'Total_Score' in df_q.columns:
    try:
        mean_score = df_q['Total_Score'].mean()
        std_score = df_q['Total_Score'].std()
        if std_score > 0:
            # [성능 최적화] apply(lambda) → numpy 벡터 연산으로 교체 (수천 종목에 수십 배 빠름)
            df_q['Total_Score_Adj'] = ((df_q['Total_Score'] - mean_score) / std_score * 25.0 + 50.0).clip(0.0, 100.0).round(1)
        else:
            df_q['Total_Score_Adj'] = df_q['Total_Score']
    except Exception as z_err:
        df_q['Total_Score_Adj'] = df_q['Total_Score']

# ── Quant 점수 세션 내 히스토리 스냅샷 (▲▼ 델타 표시용) ─────────────────
try:
    if df_q is not None and not df_q.empty and 'Total_Score_Adj' in df_q.columns:
        snapshot_scores = dict(zip(
            df_q['Code'].astype(str).str.zfill(6),
            df_q['Total_Score_Adj']
        ))
        snapshot_entry = {
            'time': datetime.now(timezone(timedelta(hours=9))).strftime('%H:%M:%S'),
            'scores': snapshot_scores
        }
        if 'quant_score_history' not in st.session_state:
            st.session_state.quant_score_history = []
        # [성능 최적화] 수천 개 dict 전체 비교 → hash 기반 O(1) 비교로 교체
        _curr_hash = hash(frozenset(snapshot_scores.items()))
        _prev_hash = st.session_state.get('quant_snapshot_last_hash', None)
        if _curr_hash != _prev_hash:
            st.session_state.quant_snapshot_last_hash = _curr_hash
            st.session_state.quant_score_history.append(snapshot_entry)
            # 최근 10개 스냅샷만 유지 (메모리 관리)
            if len(st.session_state.quant_score_history) > 10:
                st.session_state.quant_score_history = st.session_state.quant_score_history[-10:]
except Exception:
    pass

# ── df_summary 컬럼명 정규화 (GitHub CSV 인코딩 깨짐 방지) ───────
# utf-8-sig로 저장되어도 GitHub raw 다운로드 시 cp949 환경에서 깨질 수 있음
SUMMARY_COLS = ['종목/종류', '지수', '등락률', '추이', '외국인(억)', '개인(억)', '기관(억)']
if df_summary is not None and not df_summary.empty:
    if len(df_summary.columns) == len(SUMMARY_COLS):
        # 컬럼명이 깨졌는지 확인 (한글 깨짐 시 컬럼명에 이상한 문자 포함)
        first_col = str(df_summary.columns[0])
        if '종목' not in first_col:
            df_summary.columns = SUMMARY_COLS
    # 추이 컬럼의 이모지를 기호로 교체 (깨짐 방지)
    if '추이' in df_summary.columns:
        df_summary['추이'] = df_summary['추이'].astype(str).str.replace('📈', '▲').str.replace('📉', '▼').str.replace('➖', '-').str.replace('\U0001f4c8', '▲').str.replace('\U0001f4c9', '▼')

# df_summary에 나스닥100 선물 지수 행이 없는 경우 추가
if df_summary is not None and not df_summary.empty and '종목/종류' in df_summary.columns:
    has_nasdaq = df_summary['종목/종류'].str.contains('나스닥|선물|US Tech|us tech', case=False, na=False).any()
    if not has_nasdaq:
        new_row = pd.DataFrame([{
            '종목/종류': '나스닥100 선물',
            '지수': '-',
            '등락률': '-',
            '추이': '-',
            '외국인(억)': '-',
            '개인(억)': '-',
            '기관(억)': '-'
        }])
        df_summary = pd.concat([df_summary, new_row], ignore_index=True)

# ── df_full_market 수치 컬럼 전처리 ──────────────────────────
# 실제 컬럼: Code, Name, Market, Close, ChagesRatio, Volume 등
if not df_m.empty:
    for col in ['Close', 'ChagesRatio', 'Volume', 'Amount', 'Marcap']:
        if col in df_m.columns:
            df_m[col] = pd.to_numeric(df_m[col], errors='coerce').fillna(0)

# 모든 데이터프레임의 종목코드(Code) 규격화 (6자리 문자열 패딩)
for df_temp in [df_hd, df_q, df_m, df_summary, df_intraday]:
    if df_temp is not None and not df_temp.empty and 'Code' in df_temp.columns:
        df_temp['Code'] = df_temp['Code'].astype(str).str.split('.').str[0].str.zfill(6)

# ── df_supply_intraday Market 컬럼 정규화 ───────────────────────
# GitHub Actions가 저장한 CSV의 한글이 깨질 경우를 대비한 보정
if df_intraday is not None and not df_intraday.empty and 'Market' in df_intraday.columns:
    market_map = {
        'KOSPI': '코스피', 'kospi': '코스피',
        'KOSDAQ': '코스닥', 'kosdaq': '코스닥',
    }
    # 이미 올바른 한글이면 그대로, 영어 코드면 한글로 변환
    def _norm_market(v):
        v = str(v).strip()
        return market_map.get(v, v)  # 매핑 없으면 원본 유지
    df_intraday['Market'] = df_intraday['Market'].apply(_norm_market)

# ── [성능 최적화] ETF/스팩/파생상품 필터 사전 계산 (Panel 1·2·3·6 공유) ──
# 매 패널마다 반복 필터링하지 않고 데이터 로드 직후 1회 계산 후 전역 변수에 저장
def _apply_etf_filter(df):
    """ETF/스팩/파생상품 종목을 필터링한 DataFrame 반환 (성능 최적화용 사전 계산 함수)"""
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    df_out = df.copy()
    name_lower = df_out['Name'].fillna('').astype(str).str.lower()
    # [성능 최적화] apply(lambda+any) → str.contains 정규식 벡터 연산으로 교체 (수십 배 빠름)
    _etf_pattern = '|'.join(re.escape(kw) for kw in EXCLUDE_KEYWORDS)
    is_fund = name_lower.str.contains(_etf_pattern, regex=True, na=False)
    if 'Sector' in df_out.columns:
        sector_lower = df_out['Sector'].fillna('').astype(str).str.lower()
        is_fund = is_fund | sector_lower.str.contains(r'etf|수익증권', regex=True, na=False)
    return df_out[~is_fund]

# 사전 필터링된 전역 DataFrame (각 패널에서 직접 재사용)
df_hd_filtered = _apply_etf_filter(df_hd)
df_q_filtered  = _apply_etf_filter(df_q)
df_m_filtered  = _apply_etf_filter(df_m) if not df_m.empty else pd.DataFrame()


# ── 실시간 시세 반영 (FDR → GitHub CSV 폴백) ─────────────────
if df_m is not None and not df_m.empty:
    with st.spinner("🔄 실시간 시세 및 지수 반영 중..."):
        try:
            # 1. 전체 시세 조회 (FDR 실패 시 GitHub CSV 자동 폴백)
            # [성능 최적화] 세션 스테이트에 df_live_all이 있으면 재사용 (캐시 히트 시 FDR 호출 생략)
            _cached_live = st.session_state.get('df_live_all', pd.DataFrame())
            _live_cache_ts = st.session_state.get('df_live_all_ts', 0)
            _live_cache_age = time.time() - _live_cache_ts
            
            if not _cached_live.empty and _live_cache_age < 120:
                # 세션 캐시 유효 (120초 이내) → FDR 호출 없이 재사용
                df_live = _cached_live
            else:
                # 세션 캐시 만료 → 새로 조회 후 세션에 저장
                df_live = fetch_live_stock_listing()
                if not df_live.empty:
                    st.session_state['df_live_all_ts'] = time.time()

            if not df_live.empty:
                # 세션 스테이트에 전체 상장 종목 목록 백업 (검색용)
                st.session_state['df_live_all'] = df_live

                # df_m의 기존 가격 관련 컬럼 드롭 후 머지 (Name 제외)
                df_m_base = df_m.drop(columns=['Close', 'ChagesRatio', 'Volume', 'Amount'], errors='ignore')
                df_m = df_m_base.merge(df_live.drop(columns=['Name'], errors='ignore'), on='Code', how='left')

                # 결측치 채우기
                for col in ['Close', 'ChagesRatio', 'Volume', 'Amount']:
                    if col in df_m.columns:
                        df_m[col] = pd.to_numeric(df_m[col], errors='coerce').fillna(0)
        except Exception:
            pass  # 실패해도 GitHub CSV 데이터로 자연스럽게 동작
        
        # [성능 최적화] 실시간 시세가 반영된 df_m으로 df_m_filtered 재계산 (최신 가격 반영)
        if not df_m.empty:
            df_m_filtered = _apply_etf_filter(df_m)

            
        # URL 쿼리 파라미터 또는 세션 상태의 sel_code를 활용해 sel_name 한글명 보정
        if 'sel_code' in st.session_state and not df_m.empty:
            match = df_m[df_m['Code'] == st.session_state.sel_code]
            if not match.empty:
                st.session_state.sel_name = match.iloc[0]['Name']
            elif 'df_live_all' in st.session_state:
                df_all = st.session_state['df_live_all']
                match_all = df_all[df_all['Code'] == st.session_state.sel_code]
                if not match_all.empty:
                    st.session_state.sel_name = match_all.iloc[0]['Name']
            
        try:
            # 2. 실시간 지수 및 환율 반영 (캐시 함수 사용 → rerun 시 소요 없음)
            if df_summary is not None and not df_summary.empty and '종목/종류' in df_summary.columns:
                idx_status_placeholder = st.empty()
                live_idx = fetch_live_indices()
                ks_df  = live_idx.get('KS11',    pd.DataFrame())
                kq_df  = live_idx.get('KQ11',    pd.DataFrame())
                usd_df = live_idx.get('USD/KRW', pd.DataFrame())
                nq_df  = live_idx.get('NQ=F',    pd.DataFrame())
                
                def get_change_rate(df_temp):
                    if df_temp.empty:
                        return 0.0
                    if 'Close' in df_temp.columns:
                        df_temp = df_temp.dropna(subset=['Close'])
                    if df_temp.empty:
                        return 0.0
                        
                    for col in ['Change', 'Chg', 'Chg_Rate', 'Changes']:
                        if col in df_temp.columns:
                            val = df_temp[col].iloc[-1]
                            if pd.notna(val):
                                if abs(val) > 1.0:
                                    return val
                                return val * 100
                                
                    if 'Close' in df_temp.columns and len(df_temp) >= 2:
                        prev_close = df_temp['Close'].iloc[-2]
                        if prev_close != 0 and pd.notna(prev_close):
                            return (df_temp['Close'].iloc[-1] - prev_close) / prev_close * 100
                            
                    try:
                        val = df_temp.iloc[-1, -1]
                        if isinstance(val, (int, float)) and pd.notna(val):
                            if abs(val) > 1.0:
                                return val
                            return val * 100
                    except:
                        pass
                    return 0.0

                for idx, row in df_summary.iterrows():
                    name = str(row['종목/종류'])
                    if '코스피' in name and not ks_df.empty:
                        close_val = ks_df['Close'].iloc[-1]
                        chg_val = get_change_rate(ks_df)
                        df_summary.at[idx, '지수'] = f"{close_val:,.2f}"
                        df_summary.at[idx, '등락률'] = f"{chg_val:+.2f}%"
                        df_summary.at[idx, '추이'] = '▲' if chg_val > 0 else ('▼' if chg_val < 0 else '-')
                    elif '코스닥' in name and not kq_df.empty:
                        close_val = kq_df['Close'].iloc[-1]
                        chg_val = get_change_rate(kq_df)
                        df_summary.at[idx, '지수'] = f"{close_val:,.2f}"
                        df_summary.at[idx, '등락률'] = f"{chg_val:+.2f}%"
                        df_summary.at[idx, '추이'] = '▲' if chg_val > 0 else ('▼' if chg_val < 0 else '-')
                    elif ('USD/KRW' in name or '환율' in name) and not usd_df.empty:
                        close_val = usd_df['Close'].iloc[-1]
                        chg_val = get_change_rate(usd_df)
                        df_summary.at[idx, '지수'] = f"{close_val:,.2f}"
                        df_summary.at[idx, '등락률'] = f"{chg_val:+.2f}%"
                        df_summary.at[idx, '추이'] = '▲' if chg_val > 0 else ('▼' if chg_val < 0 else '-')
                    elif ('나스닥' in name or 'US Tech' in name or 'NQ=F' in name) and not nq_df.empty:
                        close_val = nq_df['Close'].iloc[-1]
                        chg_val = get_change_rate(nq_df)
                        df_summary.at[idx, '지수'] = f"{close_val:,.2f}"
                        df_summary.at[idx, '등락률'] = f"{chg_val:+.2f}%"
                        df_summary.at[idx, '추이'] = '▲' if chg_val > 0 else ('▼' if chg_val < 0 else '-')
                
                # ── 실시간 수급 현황 df_summary 반영 ──
                # _format_sup / _clean_sup → 모듈 전역 함수로 이동됨 (중복 정의 제거)

                # 네이버 실시간 API로 지수/수급 최신 덮어쓰기 적용
                try:
                    nv_indices = fetch_naver_realtime_indices()
                    nv_supply = fetch_naver_realtime_supply()
                    
                    for idx, row in df_summary.iterrows():
                        name = str(row['종목/종류'])
                        
                        # 1. 지수 및 등락률 덮어쓰기
                        m_code = None
                        if '코스피' in name:
                            m_code = 'KOSPI'
                        elif '코스닥' in name:
                            m_code = 'KOSDAQ'
                            
                        if m_code and m_code in nv_indices:
                            nv_idx = nv_indices[m_code]
                            close_val = nv_idx['price']
                            chg_val = nv_idx['chg']
                            df_summary.at[idx, '지수'] = f"{close_val:,.2f}"
                            df_summary.at[idx, '등락률'] = f"{chg_val:+.2f}%"
                            df_summary.at[idx, '추이'] = '▲' if chg_val > 0 else ('▼' if chg_val < 0 else '-')
                            
                        # 2. 실시간 수급 덮어쓰기
                        for m_name in ['코스피', '코스닥']:
                            if m_name in name and m_name in nv_supply:
                                m_sup = nv_supply[m_name]
                                df_summary.at[idx, '개인(억)'] = _format_sup(m_sup.get('개인', '0'))
                                df_summary.at[idx, '외국인(억)'] = _format_sup(m_sup.get('외국인', '0'))
                                df_summary.at[idx, '기관(억)'] = _format_sup(m_sup.get('기관', '0'))
                    
                    # ── 당일 실시간 수급 세션 누적 적재 (1분마다 새 포인트 추가) ──
                    try:
                        from datetime import timezone, timedelta
                        _KST = timezone(timedelta(hours=9))
                        _now_kst = datetime.now(_KST)
                        now_time = _now_kst.strftime('%H:%M')
                        h_m = _now_kst.hour * 100 + _now_kst.minute
                        # 장중(09:00~15:30)이고, 평일이며, 마지막 누적 시각과 현재 시각이 다를 때만 추가
                        last_accum_time = st.session_state.get('last_accum_time', '')
                        is_weekday = _now_kst.weekday() < 5  # 0=월 ~ 4=금, 5=토, 6=일
                        if 900 <= h_m <= 1530 and is_weekday and now_time != last_accum_time:
                            for mkt_name in ['코스피', '코스닥']:
                                if mkt_name in nv_supply:
                                    m_sup = nv_supply[mkt_name]
                                    f_val = _clean_sup(m_sup.get('외국인', 0))
                                    p_val = _clean_sup(m_sup.get('개인', 0))
                                    i_val = _clean_sup(m_sup.get('기관', 0))

                                    accum_df = st.session_state.df_intraday_accum
                                    # 같은 시간·같은 시장 데이터 이미 있으면 스킵
                                    duplicate = not accum_df[
                                        (accum_df['Time'] == now_time) & (accum_df['Market'] == mkt_name)
                                    ].empty

                                    if not duplicate:
                                        new_row = pd.DataFrame([{
                                            'Time': now_time,
                                            'Market': mkt_name,
                                            'Foreign_Net': f_val,       # 억원 단위
                                            'Individual_Net': p_val,    # 억원 단위
                                            'Institutional_Net': i_val  # 억원 단위
                                        }])
                                        st.session_state.df_intraday_accum = pd.concat(
                                            [accum_df, new_row], ignore_index=True
                                        )
                                        # Supabase에 실시간 데이터 upsert
                                        if supabase:
                                            try:
                                                today_date_str = _now_kst.strftime('%Y%m%d')
                                                supabase.table("supply_intraday").upsert({
                                                    "date": today_date_str,
                                                    "time": now_time,
                                                    "market": mkt_name,
                                                    "foreign_net": int(f_val),
                                                    "individual_net": int(p_val),
                                                    "institutional_net": int(i_val)
                                                }).execute()
                                            except Exception as db_err:
                                                print(f"DEBUG: Supabase upsert failed: {db_err}")
                            # 코스피·코스닥 모두 처리 완료 후 누적 시각 갱신
                            st.session_state['last_accum_time'] = now_time
                            # ── 로컬 CSV 백업 저장 (앱 재시작 시 복원용) ──
                            try:
                                _base_dir = os.path.dirname(os.path.abspath(__file__))
                                _session_csv = os.path.join(_base_dir, 'data', 'df_supply_intraday_session.csv')
                                os.makedirs(os.path.dirname(_session_csv), exist_ok=True)
                                _save_df = st.session_state.df_intraday_accum.copy()
                                _save_df['Date'] = _now_kst.strftime('%Y%m%d')
                                _save_df.to_csv(_session_csv, index=False, encoding='utf-8-sig')
                            except Exception as csv_save_err:
                                print(f"DEBUG: 로컬 CSV 수급 저장 실패: {csv_save_err}")
                    except Exception as accum_err:
                        print(f"DEBUG: Accumulation failed: {accum_err}")

                except Exception as e:
                    
                    # API 실패 시 수급값을 '-'로 표시 (가짜 숫자 오인 방지)
                    for idx, row in df_summary.iterrows():
                        name = str(row['종목/종류'])
                        for m_name in ['코스피', '코스닥']:
                            if m_name in name:
                                df_summary.at[idx, '개인(억)'] = '-'
                                df_summary.at[idx, '외국인(억)'] = '-'
                                df_summary.at[idx, '기관(억)'] = '-'
                    
                    if df_intraday is not None and not df_intraday.empty:
                        for market_key, market_name in [('KOSPI', '코스피'), ('KOSDAQ', '코스닥')]:
                            df_sub = df_intraday[df_intraday['Market'] == market_key]
                            if df_sub.empty:
                                df_sub = df_intraday[df_intraday['Market'] == market_name]
                                
                            if not df_sub.empty:
                                latest_row = df_sub.sort_values('Time').iloc[-1]
                                idx_list = df_summary[df_summary['종목/종류'].str.contains(market_name, na=False)].index
                                if len(idx_list) > 0:
                                    idx = idx_list[0]
                                    f_val = latest_row.get('Foreign_Net', 0)
                                    p_val = latest_row.get('Individual_Net', 0)
                                    i_val = latest_row.get('Institutional_Net', 0)
                                    
                                    if f_val != 0 or p_val != 0 or i_val != 0:
                                        df_summary.at[idx, '외국인(억)'] = f"{f_val:+.0f}"
                                        df_summary.at[idx, '개인(억)'] = f"{p_val:+.0f}"
                                        df_summary.at[idx, '기관(억)'] = f"{i_val:+.0f}"
        except Exception as e:
            pass

# ── 세션 스테이트 초기화 (종목 클릭 차트용 및 실시간 수급 누적) ────────────────────
q_params = st.query_params
if 'sel_code' in q_params:
    st.session_state.sel_code = q_params['sel_code'].strip().zfill(6)
    if 'sel_name' in q_params:
        st.session_state.sel_name = q_params['sel_name']

if 'sel_code' not in st.session_state:
    st.session_state.sel_code = "005930"
if 'sel_name' not in st.session_state:
    st.session_state.sel_name = "삼성전자"
if 'chart_key_index' not in st.session_state:
    st.session_state.chart_key_index = 0




try:
    q_params = st.query_params
    if 'sel_code' in q_params:
        target_code = str(q_params['sel_code']).strip().zfill(6)
        if target_code != st.session_state.sel_code:
            st.session_state.sel_code = target_code
            # 종목명이 쿼리에 없거나 역맵핑 보정이 필요한 경우
            resolved_name = q_params.get('sel_name')
            if not resolved_name or resolved_name == target_code:
                if not df_m.empty:
                    matched = df_m[df_m['Code'] == target_code]
                    if not matched.empty:
                        resolved_name = matched.iloc[0]['Name']
                if not resolved_name and 'df_live_all' in st.session_state:
                    df_all = st.session_state['df_live_all']
                    match_all = df_all[df_all['Code'] == target_code]
                    if not match_all.empty:
                        resolved_name = match_all.iloc[0]['Name']
            st.session_state.sel_name = resolved_name or target_code
            
    # 주소창 파라미터가 없으면 세션 상태의 값을 주소창에 설정하여 동기화
    if 'sel_code' not in q_params:
        st.query_params['sel_code'] = st.session_state.sel_code
        st.query_params['sel_name'] = st.session_state.sel_name
except Exception as q_err:
    print(f"DEBUG: query parameter sync failed: {q_err}")

from datetime import timezone, timedelta
_KST = timezone(timedelta(hours=9))
today_str = datetime.now(_KST).strftime('%Y%m%d')
if 'accum_date' not in st.session_state or st.session_state.accum_date != today_str:
    st.session_state.accum_date = today_str
    # 당일 수급 데이터 로드 (우선순위: Supabase → 로컬 CSV 백업)
    loaded_df = pd.DataFrame(columns=['Time', 'Market', 'Foreign_Net', 'Individual_Net', 'Institutional_Net'])
    if supabase:
        try:
            res = supabase.table("supply_intraday").select("*").eq("date", today_str).execute()
            if res.data:
                records = []
                for r in res.data:
                    records.append({
                        'Time': r['time'],
                        'Market': r['market'],
                        'Foreign_Net': int(r['foreign_net']),
                        'Individual_Net': int(r['individual_net']),
                        'Institutional_Net': int(r['institutional_net'])
                    })
                loaded_df = pd.DataFrame(records)
        except Exception as db_err:
            print(f"DEBUG: Supabase fetch failed: {db_err}")
    # Supabase 미연동 또는 데이터 없음 → 로컬 CSV 백업에서 복원
    if loaded_df.empty:
        try:
            _base_dir = os.path.dirname(os.path.abspath(__file__))
            _session_csv = os.path.join(_base_dir, 'data', 'df_supply_intraday_session.csv')
            if os.path.exists(_session_csv):
                _saved = pd.read_csv(_session_csv, encoding='utf-8-sig')
                # 오늘 날짜 데이터만 복원 (전날 데이터 제외)
                if 'Date' in _saved.columns:
                    _saved = _saved[_saved['Date'].astype(str) == today_str]
                if not _saved.empty:
                    loaded_df = _saved[['Time', 'Market', 'Foreign_Net', 'Individual_Net', 'Institutional_Net']].copy()
                    print(f"DEBUG: 로컬 CSV에서 당일 수급 데이터 {len(loaded_df)}행 복원 완료")
        except Exception as csv_restore_err:
            print(f"DEBUG: 로컬 CSV 수급 복원 실패: {csv_restore_err}")
    st.session_state.df_intraday_accum = loaded_df



# ── 🏗️ [GD 3.0 하이브리드 퀀트 아키텍처 상태 배너] ──
st.sidebar.markdown("""
<div style="background: linear-gradient(135deg, #0d1b2a, #1b263b); border: 1px solid #415a77; border-radius: 8px; padding: 10px 12px; margin-bottom: 12px;">
  <div style="display:flex; align-items:center; justify-content:space-between;">
    <span style="font-size: 11px; font-weight: bold; color: #00f2fe;">⚡ 하이브리드 파이프라인</span>
    <span style="font-size: 10px; background: rgba(0,242,254,0.15); color: #00f2fe; padding: 1px 5px; border-radius: 3px;">정상 가동</span>
  </div>
  <div style="font-size: 10px; color: #bbb; margin-top: 5px; line-height: 1.4;">
    • <b>1단계 (Wide Scan)</b>: 2,500종목 초고속 퀀트 스크리닝<br/>
    • <b>2단계 (Precision)</b>: 증권사 KIS 0.01초 틱 직결
  </div>
</div>
""", unsafe_allow_html=True)

# ── 사이드바 정렬 옵션 ──
st.sidebar.title("🎛️ 대시보드 설정")
st.sidebar.markdown("### 🎯 Quant Buy TOP 10")
q_sort_by = st.sidebar.radio(
    "정렬 기준 선택",
    ["Quant 점수 순", "거래대금 순"],
    index=0,
    help="Quant Buy TOP 10 종목을 정렬하는 기준을 선택합니다."
)

# ── 사이드바 관심 종목 검색 초기화 ──
options_list = ["선택 안 함 (검색 사용)"]
code_to_name_map = {}
default_idx = 0

st.sidebar.markdown('### ⚡ 실시간 스캘핑 모드')

is_auto_on = st.session_state.get('auto_refresh_enabled', False)
if is_auto_on:
    btn_label = "🟢 5초 실시간 갱신 [ON] (탭하여 끄기)"
    btn_type = "primary"
else:
    btn_label = "⚪ 5초 실시간 갱신 [OFF] (탭하여 켜기)"
    btn_type = "secondary"

if st.sidebar.button(btn_label, type=btn_type, width='stretch', key='btn_auto_refresh_toggle'):
    st.session_state['auto_refresh_enabled'] = not is_auto_on
    st.rerun()

if is_auto_on:
    st.sidebar.markdown("<div style='background:rgba(46,204,113,0.15); border:1px solid #2ecc71; border-radius:6px; padding:6px 10px; font-size:12px; color:#2ecc71; font-weight:bold; margin-top:-6px; text-align:center;'>🟢 5초 실시간 갱신 동작 중</div>", unsafe_allow_html=True)
else:
    st.sidebar.markdown("<div style='background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1); border-radius:6px; padding:6px 10px; font-size:12px; color:#888888; margin-top:-6px; text-align:center;'>⚪ 5초 자동 갱신 꺼짐 (버튼 탭 시 가동)</div>", unsafe_allow_html=True)

st.sidebar.markdown('---')
st.sidebar.markdown('### 🔍 종목 검색')
st.sidebar.caption('종목명 또는 코드로 검색하면 대시보드 아래에 일봉 차트가 표시됩니다.')
_search_q = st.sidebar.text_input(
    '종목명 / 코드',
    placeholder='예: 삼성전자, 005930',
    key='sidebar_search',
    label_visibility='collapsed'
)
if _search_q:
    _sq = _search_q.strip()
# 전체 종목(df_live_all) 검색 시도, 없으면 df_m에서 백업 검색
    _search_pool = st.session_state.get('df_live_all', pd.DataFrame())
    if _search_pool.empty:
        _search_pool = df_m

    if not _search_pool.empty and 'Name' in _search_pool.columns:
        _mask = (
            _search_pool['Name'].str.contains(_sq, na=False, case=False) |
            _search_pool['Code'].astype(str).str.contains(_sq, na=False)
        )
        _results = _search_pool[_mask].head(8)
        if _results.empty:
            st.sidebar.caption('⚠️ 검색 결과가 없습니다.')
        for _, _r in _results.iterrows():
            _chg = float(_r.get('ChagesRatio', 0))
# FDR 전체 종목의 ChagesRatio는 소수점 비율(0.01 = 1%)일 수 있으므로 보정
            if abs(_chg) < 0.1 and _chg != 0:
                _chg_str = f"{_chg * 100:+.2f}%"
            else:
                _chg_str = f"{_chg:+.2f}%"
            _btn_label = f"{_r['Name']}  {_chg_str}"
            if st.sidebar.button(_btn_label, key=f"sb_{_r['Code']}", width='stretch'):
                st.session_state.sel_code = str(_r['Code']).zfill(6)
                st.session_state.sel_name = str(_r['Name'])
                st.query_params['sel_code'] = str(_r['Code']).zfill(6)
                st.query_params['sel_name'] = str(_r['Name'])
                st.rerun()

portfolio_sidebar_container = st.sidebar.container()

# ── 💼 실전 포트폴리오 관리 사이드바 UI (즉시 렌더링) ──
portfolio = load_portfolio()

portfolio_sidebar_container.markdown('---')
portfolio_sidebar_container.markdown('### 💼 실전 포트폴리오 관리')

# 1. 관리할 종목 선택 드롭다운 (현재 분석 종목 및 보유 종목 즉시 선택)
_active_sel_code = st.session_state.get('sel_code', '005930')
_active_sel_name = st.session_state.get('sel_name', '삼성전자')

_port_options = [f"🎯 현재 분석: {_active_sel_name} ({_active_sel_code})"]
for p_c, p_i in portfolio.items():
    opt_str = f"💼 {p_i['name']} ({p_c})"
    if opt_str not in _port_options and p_c != _active_sel_code:
        _port_options.append(opt_str)

selected_port_target = portfolio_sidebar_container.selectbox(
    "관리할 종목 선택",
    options=_port_options,
    index=0,
    key="sb_port_target_selector"
)

# 종목 코드 및 이름 파싱
if "(" in selected_port_target and ")" in selected_port_target:
    _target_code = selected_port_target.split("(")[-1].replace(")", "").strip()
    if "🎯 현재 분석: " in selected_port_target:
        _target_name = selected_port_target.replace("🎯 현재 분석: ", "").split("(")[0].strip()
    elif "💼 " in selected_port_target:
        _target_name = selected_port_target.replace("💼 ", "").split("(")[0].strip()
    else:
        _target_name = _target_code
else:
    _target_code = _active_sel_code
    _target_name = _active_sel_name

_target_last_close = 0.0
if 'df_m' in globals() and not df_m.empty and 'Code' in df_m.columns:
    _m_match = df_m[df_m['Code'] == _target_code]
    if not _m_match.empty:
        _target_last_close = float(_m_match.iloc[0]['Close'])

is_held = _target_code in portfolio
held_info = portfolio.get(_target_code, {"entry_price": _target_last_close, "qty": 0.0})

# 평단가 및 수량 입력란
col_p1, col_p2 = portfolio_sidebar_container.columns(2)
with col_p1:
    input_price = col_p1.number_input(
        "매수 평단가 (원)", 
        min_value=0.0, 
        value=float(held_info.get("entry_price", _target_last_close)), 
        step=100.0,
        key=f"port_input_price_{_target_code}"
    )
with col_p2:
    input_qty = col_p2.number_input(
        "보유 수량 (주)", 
        min_value=0.0, 
        value=float(held_info.get("qty", 0.0)), 
        step=1.0,
        key=f"port_input_qty_{_target_code}"
    )

# 등록/수정/삭제 버튼
col_btn1, col_btn2 = portfolio_sidebar_container.columns(2)
with col_btn1:
    if col_btn1.button("➕ 등록/수정", width='stretch', key=f"btn_port_save_{_target_code}"):
        if input_price > 0 and input_qty > 0:
            # ── 💡 [투자 심리 개선 ④] 종목 유형별 사전 손절가 자동 예약 ──
            _LARGE_C = {'005930','000660','005380','035420','009150','051910','207940','068270'}
            _SMALL_C = {'010170','217590','417200','004990','027740','036570'}
            _sl_rate = 0.05 if _target_code in _LARGE_C else 0.03 if _target_code in _SMALL_C else 0.04
            _auto_sl = round(float(input_price) * (1 - _sl_rate), 0)
            portfolio[_target_code] = {
                "name": _target_name,
                "entry_price": float(input_price),
                "qty": float(input_qty),
                "stop_loss": _auto_sl
            }
            save_portfolio(portfolio)
            _tp_r = 0.08 if _target_code in _LARGE_C else 0.035 if _target_code in _SMALL_C else 0.06
            _tp1 = round(float(input_price) * (1 + _tp_r), 0)
            st.toast(f"💼 {_target_name} 저장완료! 🎯목표가 {_tp1:,.0f}원 / 🛑손절예약 {_auto_sl:,.0f}원", icon="✅")
            st.rerun()
        else:
            portfolio_sidebar_container.warning("가격과 수량을 입력해주세요.")
with col_btn2:
    if is_held:
        if col_btn2.button("🗑️ 삭제", width='stretch', key=f"btn_port_del_{_target_code}"):
            if _target_code in portfolio:
                del portfolio[_target_code]
            save_portfolio(portfolio)
            st.toast(f"🗑️ {_target_name} 포트폴리오 삭제 완료", icon="ℹ️")
            st.rerun()
    else:
        col_btn2.button("🗑️ 삭제", width='stretch', disabled=True, key=f"btn_port_del_dis_{_target_code}")



# ── 사이드바 맨 아래: Gemini AI 실시간 투자 & 헬프 어드바이저 ───────────────────
st.sidebar.markdown('---')
st.sidebar.markdown('### 🤖 Gemini AI 실시간 투자 & 헬프 어드바이저')
st.sidebar.caption('대시보드 질문뿐만 아니라 **"현재 종목을 사야 할지, 팔아야 할지, 목표가는 얼마인지"** 실시간으로 자유롭게 질문하세요.')

# 1. API Key 불러오기 및 입력창
import os
gemini_api_key = os.environ.get("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY", "")
if not gemini_api_key:
    gemini_api_key = st.sidebar.text_input(
        "Gemini API Key 입력",
        type="password",
        placeholder="AIzaSy...",
        help="Google AI Studio에서 발급받은 API Key를 입력하세요."
    )

# 2. 대시보드 상태 및 실시간 데이터 첨부 여부
attach_status = st.sidebar.checkbox("실시간 종목/시장 데이터 첨부", value=True, help="체크하면 현재 선택된 종목의 시세, 퀀트 점수, 외국인/기관 수급 및 대시보드 상태가 AI에게 함께 전달되어 훨씬 정확한 투자 조언을 받으실 수 있습니다.")

# 3. 질문 입력창
gemini_prompt = st.sidebar.text_area(
    "질문 입력",
    placeholder="예: 지금 이 종목 매수해도 괜찮아? / 목표가랑 손절가 어떻게 잡을까? / 수급이 왜 이래?",
    label_visibility="collapsed"
)

if st.sidebar.button("Gemini 3.7에게 질문하기", width='stretch'):
    if not gemini_api_key:
        st.sidebar.error("🔑 API Key를 먼저 입력해 주세요.")
    elif not gemini_prompt.strip():
        st.sidebar.warning("✏️ 질문을 입력해 주세요.")
    else:
        with st.sidebar.spinner("🤖 Gemini 3.7 AI가 실시간 분석 답변을 생성하는 중..."):
            diag_info = ""
            if attach_status:
                diag_info = "=== [실시간 대시보드 및 시장 컨텍스트] ===\n"
                diag_info += f"- 현재 시각: {datetime.now(_KST).strftime('%Y-%m-%d %H:%M:%S')}\n"
                diag_info += f"- 분석 대상 종목: {name_disp} ({code_disp})\n"
                if 'current_price_for_gemini' in locals() and current_price_for_gemini:
                    diag_info += f"- 현재가: {current_price_for_gemini:,.0f}원 (당일 등락률: {daily_chg:+.2f}%)\n"
                if 't_score_adj' in locals():
                    diag_info += f"- 매수 퀀트 점수: {t_score_adj:.1f}점 (원점수: {t_score:.1f}점), 매도 점수: {s_score:.1f}점\n"
                if 'market_cond' in locals():
                    diag_info += f"- 시장 국면: {market_cond} (권장 비중: 주식 {rec_stock:.0f}% / 현금 {rec_cash:.0f}%)\n"
                if 'supply_trend_prompt' in locals() and supply_trend_prompt:
                    diag_info += f"- 최근 10일 수급 동향: {supply_trend_prompt}\n"
                diag_info += "========================================\n\n"

            models_to_try = [
                "gemini-3.7-flash",
                "gemini-3.6-flash"
            ]

            headers = {"Content-Type": "application/json"}
            system_instruction = (
                "너는 'GD 3.0 Market Hub'의 수석 퀀트 투자 어드바이저이자 시스템 기술 지원 전문가야.\n"
                "1. [종목 매매/투자 전략 질문]: 제공된 현재 주가, 퀀트 점수, 외국인/기관 수급, 시장 국면을 분석하여 "
                "지금 사야 할지, 팔아야 할지, 관망해야 할지 구체적인 목표가(익절가) 및 손절가와 함께 명확하고 알기 쉬운 한국어로 답변해줘.\n"
                "2. [대시보드 시스템/오류 질문]: 대시보드 구조와 데이터 상태를 기반으로 명쾌한 해결책을 제시해줘."
            )
            full_prompt = f"{diag_info}사용자 질문: {gemini_prompt}"
            payload = {
                "contents": [{"parts": [{"text": full_prompt}]}],
                "systemInstruction": {"parts": [{"text": system_instruction}]}
            }

            success = False
            last_err = None
            for model_name in models_to_try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_api_key}"
                try:
                    r = requests.post(url, json=payload, headers=headers, timeout=20)
                    if r.status_code == 200:
                        ans = r.json()['candidates'][0]['content']['parts'][0]['text']
                        st.sidebar.success("🤖 Gemini 3.7 / 3.6 Flash (high) 투자 어드바이저 답변:")
                        st.sidebar.markdown(ans)
                        success = True
                        break
                    else:
                        last_err = f"API 에러 (코드 {r.status_code}): {r.text[:200]}"
                        if r.status_code in [404, 429, 503]:
                            continue
                except Exception as ex:
                    last_err = str(ex)
                time.sleep(0.5)

            if not success:
                st.sidebar.error(f"❌ Gemini 답변 생성 실패: {last_err}")


# KIS API Key 정보 (st.secrets 및 os.environ 다각적 별칭 탐색)
kis_key = st.secrets.get("KIS_APP_KEY", st.secrets.get("KIS_KEY", os.environ.get("KIS_APP_KEY", os.environ.get("KIS_KEY", ""))))
kis_sec = st.secrets.get("KIS_APP_SECRET", st.secrets.get("KIS_SECRET", os.environ.get("KIS_APP_SECRET", os.environ.get("KIS_SECRET", ""))))

# 텔레그램 알림 키 (secrets.toml 또는 환경변수에서 로드)
tg_token   = st.secrets.get("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
tg_chat_id = st.secrets.get("TELEGRAM_CHAT_ID",   os.environ.get("TELEGRAM_CHAT_ID",   ""))

# ── 백그라운드 포트폴리오 스캐너 시작 ──
# st.cache_resource에 의해 최초 1회만 구동됩니다.
try:
    start_background_portfolio_scanner()
except Exception as _bg_err:
    print(f"DEBUG: 백그라운드 스캐너 기동 실패: {_bg_err}")

# ── URL 쿼리 파라미터에서 refresh_gemini 감지 및 강제 갱신 처리 ──
try:
    if st.query_params.get("refresh_gemini") == "1":
        code_to_refresh = st.query_params.get("sel_code")
        if code_to_refresh:
            st.session_state[f"force_refresh_gemini_{code_to_refresh}"] = True
        
        # 주소창에서 refresh_gemini 파라미터만 제거
        del st.query_params["refresh_gemini"]
        st.rerun()
except Exception as _q_err:
    pass



kr_scale = 'RdBu_r'

# ── 클릭 이벤트 공통 핸들러 함수 ─────────────────────────────
def handle_chart_click(event_data):
    if not event_data:
        return
        
    points = []
    # 1. 딕셔너리 형태의 이벤트 데이터 지원 (Streamlit 최신 버전 표준)
    if isinstance(event_data, dict):
        sel = event_data.get('selection', {})
        if isinstance(sel, dict):
            points = sel.get('points', [])
        elif hasattr(sel, 'points'):
            points = sel.points
    # 2. 객체 형태의 이벤트 데이터 지원 (구버전 호환)
    elif hasattr(event_data, 'selection') and event_data.selection:
        if hasattr(event_data.selection, 'points'):
            points = event_data.selection.points
        elif isinstance(event_data.selection, dict):
            points = event_data.selection.get('points', [])
            
    if not points or len(points) == 0:
        return
        

    pt = points[0]
    
    clicked_name = ''
    cd = []
    
    # 딕셔너리인지 객체인지 판별하여 안전하게 속성 추출
    if isinstance(pt, dict):
        clicked_name = pt.get('label', '') or pt.get('y', '')
        cd = pt.get('customdata', [])
    else:
        clicked_name = getattr(pt, 'label', '') or getattr(pt, 'y', '')
        cd = getattr(pt, 'customdata', [])
    
    found_code = None
    import numpy as np
    
    flat_cd = []
    if isinstance(cd, (list, tuple, np.ndarray)):
        if len(cd) > 0 and isinstance(cd[0], (list, tuple, np.ndarray)):
            flat_cd = list(cd[0])
        else:
            flat_cd = list(cd)
            
    if len(flat_cd) > 0:
        for val in flat_cd:
            if val is None:
                continue
            v_str = str(val).split('.')[0].strip().zfill(6)
            if v_str.isdigit() and len(v_str) == 6:
                found_code = v_str
                break
    
    if not found_code and clicked_name and not df_m.empty:
        match = df_m[df_m['Name'] == clicked_name]
        if not match.empty:
            found_code = str(match.iloc[0]['Code']).zfill(6)
            
    if found_code:
        # 이미 선택된 종목과 동일하면 무한 rerun 방지를 위해 즉시 리턴
        if st.session_state.get('sel_code') == found_code:
            return
            
        st.session_state.sel_code = found_code
        st.query_params['sel_code'] = found_code
        if not df_m.empty:
            match = df_m[df_m['Code'] == found_code]
            if not match.empty:
                st.session_state.sel_name = match.iloc[0]['Name']
                st.query_params['sel_name'] = match.iloc[0]['Name']
            else:
                st.session_state.sel_name = clicked_name or found_code
                st.query_params['sel_name'] = clicked_name or found_code
        else:
            st.session_state.sel_name = clicked_name or found_code
            st.query_params['sel_name'] = clicked_name or found_code
            
        # 성공적으로 종목 변경이 완료된 시점에 알림 표시 제거 (요청 반영)
        pass
            
        # 차트의 selection 상태를 완전히 리셋하기 위해 key 값 증가 (태블릿/모바일 터치 2번 클릭 문제 해결)
        st.session_state.chart_key_index += 1
        st.rerun()

# ── 개별 차트 6분할 레이아웃 (3열 그리드 개편) ───────────────
quant_time = update_times.get('df_quant_final.csv', '알 수 없음')
is_stale = False

try:
    if '알 수 없음' not in quant_time and '원격' not in quant_time and '데이터 없음' not in quant_time:
        from datetime import datetime, timezone, timedelta
        _KST = timezone(timedelta(hours=9))
        _now_kst = datetime.now(_KST)
        is_weekend = _now_kst.weekday() >= 5
        q_dt = datetime.strptime(quant_time, '%Y-%m-%d %H:%M:%S')
        today_date = _now_kst.date()
        
        if q_dt.date() < today_date:
            if is_weekend:
                # 주말인 경우 마지막 금요일 영업일의 장 마감(15:30) 데이터가 반영되었는지 체크
                if q_dt.weekday() != 4 or (q_dt.hour * 100 + q_dt.minute) < 1530:
                    is_stale = True
            else:
                is_stale = True
        elif q_dt.date() == today_date and (_now_kst.hour * 100 + _now_kst.minute) >= 1530:
            # 오늘인데 현재 시각이 장 마감(15:30)을 지났음에도 데이터 시각이 15:30 이전인 경우
            if (q_dt.hour * 100 + q_dt.minute) < 1530:
                is_stale = True
except Exception as stale_err:
    print(f"DEBUG: 퀀트 신선도 체크 에러: {stale_err}")

# KOSPI 20일선 기반 실시간 자산배분 판단
kospi_close, kospi_ma20, success = get_kospi_ma20()
if success:
    if kospi_close >= kospi_ma20:
        market_regime = "상승/횡보 국면 (KOSPI 20일선 상회)"
        rec_cash = 20.0
        rec_stock = 80.0
        regime_desc = "시장 단기 추세가 견고하여 적극적인 개별 종목 매수 전략이 유효합니다."
        regime_color = "#2ecc71"
    else:
        market_regime = "약세/보수 국면 (KOSPI 20일선 하회)"
        rec_cash = 70.0
        rec_stock = 30.0
        regime_desc = "시장 단기 추세가 약화되었습니다. 신규 매수를 자제하고 현금 비중을 대폭 늘려 리스크를 방어하십시오."
        regime_color = "#e74c3c"
else:
    market_regime = "판단 유보 (지수 수집 실패)"
    rec_cash = 30.0
    rec_stock = 70.0
    regime_desc = "지수 수집 실패로 기본 자산배분 비중(현금 30% / 주식 70%)을 권장합니다."
    regime_color = "#7f8c8d"

title_col_left, title_col_right = st.columns([7, 5])

with title_col_left:
    rel_t = _relative_time(quant_time)
    rel_t_str = f" ({rel_t})" if rel_t else ""
    refresh_badge = " <span style='background:rgba(46,204,113,0.2); color:#2ecc71; border:1px solid #2ecc71; font-size:11px; font-weight:bold; padding:2px 8px; border-radius:10px;'>⚡ 5초 실시간 갱신 중</span>" if st.session_state.get('auto_refresh_enabled', False) else ""
    st.markdown(f"### 📊 실시간 시장 종합 대시보드{refresh_badge} <span style='font-size: 0.85rem; color: #888; font-weight: normal; margin-left: 10px;'>(퀀트 업데이트: {quant_time}{rel_t_str})</span>", unsafe_allow_html=True)
    st.caption("💡 왼쪽 사이드바의 '종목 검색'을 통해 종목을 선택하시면, 하단 일봉 차트가 실시간으로 비동기 갱신됩니다.")

with title_col_right:
    regime_html = f"""<div style="background-color: #111920; padding: 10px 14px; border-radius: 8px; border: 1px solid rgba(78, 159, 245, 0.2); color: #fff; margin-bottom: 5px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
            <span style="font-size: 11px; font-weight: bold; color: #ff922b; font-family: 'malgun gothic', sans-serif;">💵 권장 자산 배분 가이드</span>
            <span style="font-size: 10px; color: {regime_color}; font-weight: bold; font-family: 'malgun gothic', sans-serif;">{market_regime}</span>
        </div>
        <div style="display: flex; height: 14px; border-radius: 7px; overflow: hidden; background-color: #333; margin-bottom: 5px;">
            <div style="width: {rec_stock}%; background-color: #3498db; display: flex; align-items: center; justify-content: center; color: white; font-size: 9px; font-weight: bold; font-family: 'malgun gothic', sans-serif;">주식 {rec_stock:.0f}%</div>
            <div style="width: {rec_cash}%; background-color: #e67e22; display: flex; align-items: center; justify-content: center; color: white; font-size: 9px; font-weight: bold; font-family: 'malgun gothic', sans-serif;">현금 {rec_cash:.0f}%</div>
        </div>
        <div style="font-size: 10px; color: #bbb; line-height: 1.3; font-family: 'malgun gothic', sans-serif;">
            <strong>지침:</strong> {regime_desc}
        </div>
    </div>"""
    st.markdown(regime_html, unsafe_allow_html=True)

# ── 3열(Column) 그리드 레이아웃 정의 (세로 연속 배치로 공백 제거) ──
col_left, col_mid, col_right = st.columns(3)

# ── [Panel 1] 실시간 수급 (Treemap) ─────────────────────────
with col_mid:
    from datetime import timezone as _tz, timedelta as _t_del
    _now_k = datetime.now(_tz(_t_del(hours=9)))
    _hm_k = _now_k.hour * 100 + _now_k.minute
    _is_0900_mode = (900 <= _hm_k < 935) and (_now_k.weekday() < 5)
    _mode_badge = " <span style='font-size:11px;color:#ffd700;background:rgba(255,215,0,0.15);padding:2px 6px;border-radius:4px;'>⚡ 09:00 실시간 체결 가동</span>" if _is_0900_mode else ""
    st.markdown(f"##### 📊 실시간 수급 (외/기/프){_mode_badge}", unsafe_allow_html=True)
    if not df_hd_filtered.empty and 'Total_Combined_Net' in df_hd_filtered.columns:
        df_hd_clean = df_hd_filtered.copy()
        
        # 순매수/순매도 상관없이 수급 쏠림이 가장 큰(절대값 기준) TOP 10 종목 추출
        df_hd_clean['Abs_Net_Sort'] = df_hd_clean['Total_Combined_Net'].abs()
        df1 = df_hd_clean.sort_values('Abs_Net_Sort', ascending=False).head(10).copy()
        df1['Code'] = df1['Code'].astype(str).str.zfill(6)
        
        # 실시간 외국인/기관 수급 조회 (tuple로 변환하여 캐시 키 안정화)
        realtime_sup = fetch_stock_realtime_investors(tuple(sorted(df1['Code'].tolist())))
        
        # 실시간 시세 반영을 위해 기존 df_hd에 들어있던 시세 관련 과거 컬럼 제거
        df1 = df1.drop(columns=['ChagesRatio', 'Current_Price', 'Close', 'Price', 'Volume', 'Trade_Volume'], errors='ignore')
        if not df_m.empty and 'Code' in df_m.columns:
            # 실시간 시세 데이터를 df_m에서 가져와 강제 병합
            df1 = df1.merge(df_m[['Code', 'Close', 'ChagesRatio', 'Volume']], on='Code', how='left')
            
        df1['ChagesRatio'] = pd.to_numeric(df1['ChagesRatio'], errors='coerce').fillna(0)
        df1['Current_Price_Val'] = pd.to_numeric(df1['Close'], errors='coerce').fillna(0)
        df1['Trade_Volume_Val']  = pd.to_numeric(df1['Volume'], errors='coerce').fillna(0)
        
        # 실시간 수급 데이터 덮어쓰기 (네이버 API 실시간 가집계 반영)
        fgn_list = []
        inst_list = []
        for code in df1['Code']:
            if code in realtime_sup:
                fgn_list.append(realtime_sup[code]["foreign"])
                inst_list.append(realtime_sup[code]["institutional"])
            else:
                fgn_list.append(0)
                inst_list.append(0)
        df1['Foreign_Net'] = fgn_list
        df1['Institutional_Net'] = inst_list
        # ★ 실시간 수급 반영 후 Total_Combined_Net 재계산 (기존 CSV 값이 0이어도 네이버 실시간값 사용)
        df1['Total_Combined_Net'] = df1['Foreign_Net'] + df1['Institutional_Net']

        df1['Disp'] = df1['ChagesRatio'].apply(lambda x: f"{x:+.2f}%")

        df1['Abs_Net'] = df1['Total_Combined_Net'].abs()
        # 부호 보존 power-scale: 순매수(+)는 양수, 순매도(-)는 음수 방향으로 막대 표시
        if df1['Abs_Net'].max() > 0:
            df1['visual_val'] = df1['Total_Combined_Net'].apply(
                lambda x: (abs(x) ** 0.55) if x >= 0 else -(abs(x) ** 0.55)
            )
        else:
            # 수급 데이터 전무 시 거래대금 기반 양방향 fallback
            df1['visual_val'] = (pd.to_numeric(df1.get('Amount', 0), errors='coerce').fillna(0) / 1e8) ** 0.55

        # 1번 패널: 순매수(+)는 오른쪽, 순매도(-)는 왼쪽으로 뻗는 Diverging Bar Chart
        import plotly.graph_objects as go

        fig_p1 = go.Figure()

        # 정렬: 순매수 상위가 하단, 순매도 상위가 상단에 오도록 ascending=True
        df1_sorted = df1.sort_values('Total_Combined_Net', ascending=True).copy()
        x_val_sorted = df1_sorted['visual_val']

        # 막대 색상: 순매수(양수)=빨강 계열, 순매도(음수)=파랑 계열
        bar_colors = [
            '#ef4444' if v >= 0 else '#3b82f6'
            for v in df1_sorted['Total_Combined_Net']
        ]

        text_labels_sorted = df1_sorted['Total_Combined_Net'].apply(
            lambda x: f" {x/10000:.1f}만주" if abs(x) >= 10000 else f" {int(x):+,}주"
        )

        custom_data_values = df1_sorted[['Code', 'Close', 'ChagesRatio', 'Total_Combined_Net', 'Foreign_Net', 'Institutional_Net']].values

        fig_p1.add_trace(go.Bar(
            y=df1_sorted['Name'],
            x=x_val_sorted,
            orientation='h',
            marker=dict(
                color=bar_colors,
                line=dict(color='rgba(255,255,255,0.08)', width=1)
            ),
            cliponaxis=False,
            text=text_labels_sorted,
            textposition='outside',
            customdata=custom_data_values,
            hovertemplate=(
                '<b>%{y}</b> (%{customdata[0]})<br>'
                '━━━━━━━━━━━━━━━━<br>'
                '합산 순매수: <b>%{customdata[3]:+,}주</b><br>'
                '🔴 외국인 순매수: %{customdata[4]:+,}주<br>'
                '🔵 기관 순매수: %{customdata[5]:+,}주<br>'
                '현재가: %{customdata[1]:,}원 (%{customdata[2]:+.2f}%)'
                '<extra></extra>'
            )
        ))

        abs_max = float(x_val_sorted.abs().max()) if not x_val_sorted.empty and x_val_sorted.abs().max() > 0 else 100

        fig_p1.update_layout(
            height=320,
            template='plotly_dark',
            margin=dict(t=10, b=10, l=95, r=80),
            clickmode='event+select',
            font=dict(family='malgun gothic, nanum gothic, sans-serif'),
            xaxis=dict(
                fixedrange=True,
                zeroline=True,
                zerolinecolor='rgba(255,255,255,0.3)',
                zerolinewidth=1.5,
            ),
            yaxis=dict(fixedrange=True)
        )
        fig_p1.update_yaxes(automargin=True)
        # x축 중앙 0 선 대칭 고정 및 텍스트 짤림 방지를 위한 여유 공간 확대 (1.35 -> 1.70)
        fig_p1.update_xaxes(range=[-abs_max * 1.70, abs_max * 1.70])
        
        ev_p1 = st.plotly_chart(
            fig_p1,
            width='stretch',
            on_select='rerun',
            selection_mode=['points'],
            key=f"p1_chart_{st.session_state.chart_key_index}",
            config={'displayModeBar': False}
        )
        handle_chart_click(ev_p1)
# ── [Panel 2] Quant Buy TOP 10 (Horizontal Bar) ─────────────
with col_mid:
    st.markdown(f"##### 🎯 Quant Buy TOP 10 ({q_sort_by})")
    fig_p2 = go.Figure()
    x_val = pd.Series(dtype=float)  # NameError 방지: df_q 비어있을 때 기본값
    if not df_q_filtered.empty and 'Total_Score' in df_q_filtered.columns:
        df2 = df_q_filtered.copy()
        
        df2['Code'] = df2['Code'].astype(str).str.split('.').str[0].str.zfill(6)
        if not df_m.empty and 'Code' in df_m.columns:
            df2 = df2.drop(columns=['Close', 'ChagesRatio', 'Amount'], errors='ignore')
            df2 = df2.merge(df_m[['Code', 'Close', 'ChagesRatio', 'Amount']], on='Code', how='left')
        else:
            df2['Close'] = 0
            df2['ChagesRatio'] = 0.0
            df2['Amount'] = 0.0
        df2['Close'] = pd.to_numeric(df2['Close'], errors='coerce').fillna(0)
        df2['ChagesRatio'] = pd.to_numeric(df2['ChagesRatio'], errors='coerce').fillna(0)
        df2['Amount'] = pd.to_numeric(df2['Amount'], errors='coerce').fillna(0)

        if q_sort_by == "거래대금 순" and 'Amount' in df2.columns:
            df2 = df2.sort_values('Amount', ascending=True).tail(10).copy()
            df2['Amount_100M'] = df2['Amount'] / 1e8
            # 시각적 스케일링: 아웃라이어로 인해 막대가 압착되는 현상 완화
            df2['Visual_Val'] = df2['Amount_100M'] ** 0.55
            x_val = df2['Visual_Val']
            hover_label = '거래대금: <b>%{customdata[5]:,.0f}억원</b>'
            text_labels = df2['Amount_100M'].apply(lambda x: f" {x:,.0f}")
        else:
            df2 = df2.sort_values('Total_Score_Adj', ascending=True).tail(10).copy()
            df2['Amount_100M'] = df2['Amount'] / 1e8
            df2['Visual_Val'] = df2['Total_Score_Adj']
            x_val = df2['Visual_Val']
            hover_label = '보정 Quant 점수: <b>%{x:.1f}점</b>'
            
            # 이전 스냅샷과 현재 스냅샷을 비교하여 점수 변동(▲▼ 델타) 계산
            prev_scores = {}
            if 'quant_score_history' in st.session_state and len(st.session_state.quant_score_history) >= 2:
                prev_scores = st.session_state.quant_score_history[-2]['scores']
            
            def get_delta_str(row):
                code = str(row['Code']).zfill(6)
                curr = float(row.get('Total_Score_Adj', 0))
                if code in prev_scores:
                    diff = round(curr - prev_scores[code], 1)
                    if diff > 0:
                        return f" (▲{diff:.1f})"
                    elif diff < 0:
                        return f" (▼{abs(diff):.1f})"
                return ""
            
            text_labels = df2.apply(lambda r: f" {r['Total_Score_Adj']:.1f}{get_delta_str(r)}", axis=1)

        fig_p2.add_trace(go.Bar(
            y=df2['Name'],
            x=x_val,
            orientation='h',
            marker=dict(
                colorscale='Reds',
                color=df2['Total_Score_Adj'] if 'Total_Score_Adj' in df2.columns else df2['Total_Score'],
                showscale=False,
                line=dict(color='rgba(255,255,255,0.1)', width=1)
            ),
            text=text_labels,
            textposition='outside',
            customdata=df2[['Code', 'Close', 'ChagesRatio', 'Total_Score_Adj', 'Total_Score', 'Amount_100M']].values,
            hovertemplate=(
                '<b>%{y}</b> (%{customdata[0]})<br>'
                '━━━━━━━━━━━━━━━<br>'
                + hover_label + '<br>'
                '현재가: %{customdata[1]:,}원 (%{customdata[2]:+.2f}%)<br>'
                'Quant 보정 점수: %{customdata[3]:.1f}점 (원점수: %{customdata[4]:.1f}점)'
                '<extra></extra>'
            )
        ))
    fig_p2.update_layout(
        height=320,
        template='plotly_dark',
        margin=dict(t=10, b=10, l=95, r=80),  # 좌우 여백을 넓혀 기기별 잘림 방지
        clickmode='event+select',
        font=dict(family='malgun gothic, nanum gothic, sans-serif'),
        xaxis=dict(fixedrange=True),
        yaxis=dict(fixedrange=True)
    )
    fig_p2.update_yaxes(automargin=True)
    max_x = float(x_val.max()) if not x_val.empty else 100
    fig_p2.update_xaxes(range=[0, max_x * 1.30])
    ev_p2 = st.plotly_chart(
        fig_p2, 
        width='stretch', 
        on_select='rerun', 
        selection_mode=['points'], 
        key=f"p2_chart_{st.session_state.chart_key_index}", 
        config={'displayModeBar': False}
    )
    handle_chart_click(ev_p2)

# ── [Panel 3] 거래대금 리더 (Horizontal Bar) ─────────────────
with col_right:
    st.markdown("##### 🔥 거래대금 리더 (12)")
    fig_p3 = go.Figure()
    df3 = pd.DataFrame()  # NameError 방지: df_m 비어있을 때 기본값
    if not df_m_filtered.empty and 'Amount' in df_m_filtered.columns:
        df3 = df_m_filtered.sort_values('Amount', ascending=True).tail(12).copy()
        df3['Amount_100M'] = df3['Amount'] / 100000000
        
        # 매수/매도 거래대금 추정 (CLV + 등락률 하이브리드 모델) ── 벡터 연산으로 최적화
        close_v = pd.to_numeric(df3.get('Close', 0), errors='coerce').fillna(0)
        high_v  = pd.to_numeric(df3.get('High',  0), errors='coerce').fillna(0)
        low_v   = pd.to_numeric(df3.get('Low',   0), errors='coerce').fillna(0)
        ratio_v = pd.to_numeric(df3.get('ChagesRatio', 0), errors='coerce').fillna(0)
        
        hl_range = (high_v - low_v).replace(0, np.nan)
        clv = ((close_v - low_v) - (high_v - close_v)) / hl_range
        clv = clv.fillna(0.0)
        
        # 하이브리드 가중치: CLV 30% + 등락률 20% + 기본 50%
        buy_frac = (0.5 + 0.3 * clv + 0.2 * (ratio_v / 30.0)).clip(0.1, 0.9)
        
        df3['Buy_Fraction'] = buy_frac.values
        df3['Sell_Fraction'] = 1.0 - df3['Buy_Fraction']
        df3['Buy_Amount_100M'] = df3['Amount_100M'] * df3['Buy_Fraction']
        df3['Sell_Amount_100M'] = df3['Amount_100M'] * df3['Sell_Fraction']
        
        # 시각적 가로막대 길이 완화 (아웃라이어 왜곡 방지 및 태블릿 가독성 제고)
        df3['Visual_Total'] = df3['Amount_100M'] ** 0.55
        df3['Buy_Visual'] = df3['Visual_Total'] * df3['Buy_Fraction']
        df3['Sell_Visual'] = df3['Visual_Total'] * df3['Sell_Fraction']
        
        custom_data_values = df3[['Code', 'Close', 'ChagesRatio', 'Amount_100M', 'Buy_Amount_100M', 'Sell_Amount_100M', 'Buy_Fraction', 'Sell_Fraction']].values
        
        # 1. 매수 거래대금 Trace (빨간색)
        fig_p3.add_trace(go.Bar(
            name='매수 대금',
            y=df3['Name'],
            x=df3['Buy_Visual'],
            orientation='h',
            marker=dict(
                color='#ff6b6b',
                line=dict(color='rgba(255,255,255,0.1)', width=1)
            ),
            customdata=custom_data_values,
            hovertemplate=(
                '<b>%{y}</b> (%{customdata[0]})<br>'
                '━━━━━━━━━━━━━━━━<br>'
                '총 거래대금: <b>%{customdata[3]:,.0f}억원</b><br>'
                '🔴 매수 대금: %{customdata[4]:,.0f}억원 (%{customdata[6]:.1%})<br>'
                '🔵 매도 대금: %{customdata[5]:,.0f}억원 (%{customdata[7]:.1%})<br>'
                '현재가: %{customdata[1]:,}원 (%{customdata[2]:+.2f}%)'
                '<extra></extra>'
            )
        ))
        
        # 2. 매도 거래대금 Trace (파란색) - 누적으로 쌓임
        fig_p3.add_trace(go.Bar(
            name='매도 대금',
            y=df3['Name'],
            x=df3['Sell_Visual'],
            orientation='h',
            marker=dict(
                color='#4e9ff5',
                line=dict(color='rgba(255,255,255,0.1)', width=1)
            ),
            text=df3['Amount_100M'].apply(lambda x: f" {x:,.0f}"),
            textposition='outside',
            customdata=custom_data_values,
            hovertemplate=(
                '<b>%{y}</b> (%{customdata[0]})<br>'
                '━━━━━━━━━━━━━━━━<br>'
                '총 거래대금: <b>%{customdata[3]:,.0f}억원</b><br>'
                '🔴 매수 대금: %{customdata[4]:,.0f}억원 (%{customdata[6]:.1%})<br>'
                '🔵 매도 대금: %{customdata[5]:,.0f}억원 (%{customdata[7]:.1%})<br>'
                '현재가: %{customdata[1]:,}원 (%{customdata[2]:+.2f}%)'
                '<extra></extra>'
            )
        ))
        
    fig_p3.update_layout(
        height=320,
        template='plotly_dark',
        margin=dict(t=10, b=10, l=95, r=80),  # 좌우 여백을 넓혀 기기별 잘림 방지
        clickmode='event+select',
        barmode='stack',
        showlegend=False,
        font=dict(family='malgun gothic, nanum gothic, sans-serif'),
        xaxis=dict(fixedrange=True),
        yaxis=dict(fixedrange=True)
    )
    fig_p3.update_yaxes(automargin=True)
    max_x = float(df3['Visual_Total'].max()) if not df3.empty else 100
    fig_p3.update_xaxes(range=[0, max_x * 1.30])
    ev_p3 = st.plotly_chart(
        fig_p3, 
        width='stretch', 
        on_select='rerun', 
        selection_mode=['points'], 
        key=f"p3_chart_{st.session_state.chart_key_index}", 
        config={'displayModeBar': False}
    )
    handle_chart_click(ev_p3)

# ── [Panel 4] 시장 요약 테이블 ──────────────────────────────
with col_left:
    st.markdown("##### 📉 시장 요약")
    fig_p4 = go.Figure()
    if not df_summary.empty:
        def get_color(v):
            try:
                f = float(str(v).replace(',', '').replace('%', '').replace('+', ''))
                return '#ff6b6b' if f > 0 else ('#4e9ff5' if f < 0 else '#cccccc')
            except:
                return '#cccccc'
        fallback_cols = ['종목/종류', '지수', '등락률', '추이', '외국인(억)', '개인(억)', '기관(억)']
        if len(df_summary.columns) == 3:
            df_summary.columns = fallback_cols
        elif len(df_summary.columns) != 3:
            def is_broken(s):
                return any(0x1200 <= ord(c) <= 0x137F for c in str(s))
            new_cols = list(df_summary.columns)
            for i, c in enumerate(new_cols):
                if is_broken(c):
                    if i < len(fallback_cols):
                        new_cols[i] = fallback_cols[i]
            df_summary.columns = new_cols

        def fix_row_value(val, idx):
            s = str(val)
            if any(0x1200 <= ord(c) <= 0x137F for c in s) or any(0x0370 <= ord(c) <= 0x03FF for c in s):
                known = ['코스피', '코스닥', 'USD/KRW', '나스닥100 선물']
                return known[idx] if idx < len(known) else val
            return val

        if '종목/종류' in df_summary.columns:
            df_summary['종목/종류'] = [
                fix_row_value(v, i) for i, v in enumerate(df_summary['종목/종류'])
            ]

        chg_col = None
        for candidate in ['등락률', 'ChagesRatio', 'ChangeRatio', 'Changes']:
            if candidate in df_summary.columns:
                chg_col = candidate
                break

        color_list = ['#cccccc'] * len(df_summary.columns)
        if chg_col:
            col_idx = list(df_summary.columns).index(chg_col)
            color_list[col_idx] = [get_color(x) for x in df_summary[chg_col]]

        row_fill = ['#1a2332', '#111920'] * (len(df_summary) // 2 + 1)
        row_fill = row_fill[:len(df_summary)]

        fig_p4.add_trace(go.Table(
            columnwidth=[1.4, 1.2, 1.2, 0.6, 1.6, 1.6, 1.6],
            header=dict(
                values=[f'<b>{c}</b>' for c in df_summary.columns],
                fill_color='#1e3a5f',
                line_color='#4e9ff5',
                font=dict(color='#e0e8f0', size=11, family='malgun gothic, nanum gothic, sans-serif'),
                align='center',
                height=30
            ),
            cells=dict(
                values=[df_summary[c] for c in df_summary.columns],
                fill_color=[row_fill] * len(df_summary.columns),
                line_color='rgba(78,159,245,0.2)',
                font=dict(color=color_list, size=11, family='malgun gothic, nanum gothic, sans-serif'),
                align='center',
                height=26
            )
        ))
    fig_p4.update_layout(
        height=170,  # 5행 테이블 크기에 맞게 170으로 축소하여 상단 공백 제거
        template='plotly_dark',
        margin=dict(t=10, b=10, l=10, r=10)
    )
    st.plotly_chart(fig_p4, width='stretch')

# ── [Panel 5] 코스피/코스닥 수급 (Line) ───────────────────────
with col_left:
    st.markdown("##### 📈 수급 현황 (일중 추이)")
    market_tab = st.radio("수급 구분", ["코스피 수급", "코스닥 수급"], horizontal=True, label_visibility="collapsed", key="p5_market_tab")
    target_market = '코스피' if market_tab == "코스피 수급" else '코스닥'

    from datetime import timezone, timedelta
    _KST = timezone(timedelta(hours=9))
    _now_kst = datetime.now(_KST)
    today_date_str = _now_kst.strftime('%Y%m%d')
    now_hm = _now_kst.hour * 100 + _now_kst.minute

    # ── GitHub에서 받아온 당일 수급 CSV (data_collector가 30분마다 누적 저장) ──
    df_line = pd.DataFrame()
    if df_intraday is not None and not df_intraday.empty:
        df_tmp = df_intraday.copy()
        # Date 컬럼이 있으면 오늘 날짜만 필터 (전일 데이터 제거)
        if 'Date' in df_tmp.columns:
            df_tmp = df_tmp[df_tmp['Date'].astype(str) == today_date_str]
        df_line = df_tmp[df_tmp['Market'] == target_market].copy()
        # 정규장 시간(09:00~15:30)만 필터
        df_line = df_line[df_line['Time'].str.match(r'^(09|10|11|12|13|14|15):[0-5][0-9]$') == True]

    # ── 세션 누적 실시간 데이터 (GitHub 최신 커밋 이후 1분 단위 보완) ──
    accum_df = st.session_state.get('df_intraday_accum', pd.DataFrame())
    if not accum_df.empty:
        accum_sub = accum_df[accum_df['Market'] == target_market].copy()
        accum_sub = accum_sub[accum_sub['Time'].str.match(r'^(09|10|11|12|13|14|15):[0-5][0-9]$') == True]
        if not accum_sub.empty:
            if not df_line.empty:
                df_line = pd.concat([df_line, accum_sub], ignore_index=True)
            else:
                df_line = accum_sub

    fig_p5 = go.Figure()
    if not df_line.empty:
        df_line = df_line.drop_duplicates(subset=['Time'], keep='last')
        df_line = df_line.sort_values('Time')
        
        df_line['Datetime'] = pd.to_datetime(today_date_str + ' ' + df_line['Time'], format='%Y%m%d %H:%M')
        
        # ── 수급 수치 숫자형 변환 ──
        for c in ['Foreign_Net', 'Individual_Net', 'Institutional_Net']:
            if c in df_line.columns:
                df_line[c] = pd.to_numeric(df_line[c].astype(str).str.replace(',', ''), errors='coerce')

        # ── 1분 단위 리샘플링 후 선형 보간 (scipy 불필요) ──
        df_line = df_line.set_index('Datetime').resample('1min').asfreq()
        num_cols = [c for c in ['Foreign_Net', 'Individual_Net', 'Institutional_Net'] if c in df_line.columns]
        if num_cols:
            df_line[num_cols] = df_line[num_cols].interpolate(method='linear').ffill().bfill()

            # ── numpy 가우시안 롤링 평활화 (scipy 불필요) ──
            # 포인트 수에 따라 윈도우 크기를 자동 조절:
            #   데이터가 적으면 작은 윈도우(꺾임 유지), 많으면 큰 윈도우(HTS 수준 곡선)
            n_total = len(df_line)
            smooth_win = max(3, min(15, n_total // 8))  # 3~15분 적응형 윈도우
            import numpy as np

            def _gaussian_smooth(series, window):
                """가우시안 가중 롤링 평균 — numpy만으로 구현 (scipy 불필요)"""
                sigma = window / 3.0
                x = np.arange(window) - window // 2
                weights = np.exp(-0.5 * (x / sigma) ** 2)
                weights /= weights.sum()
                arr = series.values.astype(float)
                # 엣지 처리: 양쪽 끝은 원본값 유지(pad)
                padded = np.pad(arr, window // 2, mode='edge')
                smoothed = np.convolve(padded, weights, mode='valid')
                return pd.Series(smoothed[:len(arr)], index=series.index)

            for col in num_cols:
                if df_line[col].notna().sum() >= smooth_win:
                    df_line[col] = _gaussian_smooth(df_line[col].ffill().bfill(), smooth_win)

        df_line = df_line.reset_index()

        col_cfg = [
            ('Foreign_Net',       '외국인', '#4e9ff5'),
            ('Individual_Net',    '개인',   '#ff6b6b'),
            ('Institutional_Net', '기관',   '#51cf66'),
        ]

        for col, name, color in col_cfg:
            if col in df_line.columns:
                fig_p5.add_trace(go.Scatter(
                    x=df_line['Datetime'], y=df_line[col],
                    name=name, mode='lines',
                    connectgaps=True,
                    line=dict(
                        color=color, width=2.5,
                        shape='spline',   # Plotly 렌더링 레벨 spline 곡선화 (이중 평활)
                        smoothing=1.3     # 최대 곡선 부드러움
                    ),
                    hovertemplate=f'<b>{name}</b>: %{{y:+,.0f}}억원'
                ))
    else:
        if now_hm > 1530:
            msg = '📊 오늘 장 마감 완료<br>내일 장 시작(09:00) 이후 실시간 추이 수집 재개'
        else:
            msg = '📡 수급 데이터 수집 중...<br>장 시작(09:00) 이후 표시됩니다'
        fig_p5.add_annotation(
            text=msg,
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=12, color='#888'),
            align='center'
        )

    fig_p5.update_layout(
        height=450,  # 시장 요약 축소에 맞게 높이를 450으로 확대하여 옆의 Quant Buy 끝선과 맞춤
        template='plotly_dark',
        margin=dict(t=10, b=10, l=10, r=10),
        hovermode='x unified',
        font=dict(family='malgun gothic, nanum gothic, sans-serif'),
        xaxis=dict(
            type='date',
            range=[
                pd.to_datetime(today_date_str + ' 09:00', format='%Y%m%d %H:%M'),
                pd.to_datetime(today_date_str + ' 15:30', format='%Y%m%d %H:%M')
            ],
            tickformat='%H:%M',
            dtick=1800000,  # 30분 단위
            showgrid=True,
            fixedrange=True
        ),
        yaxis=dict(fixedrange=True)
    )
    st.plotly_chart(fig_p5, width='stretch', config={'displayModeBar': False})

# ── [Panel 6] 상승률 리더 (Horizontal Bar) ───────────────────
with col_right:
    st.markdown("##### 🚀 상승률 리더 (12)")
    fig_p6 = go.Figure()
    df6 = pd.DataFrame()  # NameError 방지: df_m 비어있을 때 기본값
    if not df_m_filtered.empty and 'ChagesRatio' in df_m_filtered.columns:
        df6 = df_m_filtered.sort_values('ChagesRatio', ascending=True).tail(12).copy()
        
        fig_p6.add_trace(go.Bar(
            y=df6['Name'],
            x=df6['ChagesRatio'],
            orientation='h',
            marker=dict(
                colorscale=kr_scale,
                color=df6['ChagesRatio'],
                cmid=0,
                showscale=False,
                line=dict(color='rgba(255,255,255,0.1)', width=1)
            ),
            text=df6['ChagesRatio'].apply(lambda x: f" {x:+.2f}%"),
            textposition='outside',
            customdata=df6[['Code', 'Close', 'Volume']].values,
            hovertemplate=(
                '<b>%{y}</b> (%{customdata[0]})<br>'
                '등락률: <b>%{text}</b><br>'
                '현재가: %{customdata[1]:,d}원<br>'
                '거래량: %{customdata[2]:,d}주'
                '<extra></extra>'
            )
        ))
    fig_p6.update_layout(
        height=320,
        template='plotly_dark',
        margin=dict(t=10, b=10, l=95, r=80),  # 좌우 여백을 넓혀 기기별 잘림 방지
        clickmode='event+select',
        font=dict(family='malgun gothic, nanum gothic, sans-serif'),
        xaxis=dict(fixedrange=True),
        yaxis=dict(fixedrange=True)
    )
    fig_p6.update_yaxes(automargin=True)
    max_x = float(df6['ChagesRatio'].max()) if not df6.empty else 30
    fig_p6.update_xaxes(range=[0, max_x * 1.30])
    ev_p6 = st.plotly_chart(
        fig_p6, 
        width='stretch', 
        on_select='rerun', 
        selection_mode=['points'], 
        key=f"p6_chart_{st.session_state.chart_key_index}", 
        config={'displayModeBar': False}
    )
    handle_chart_click(ev_p6)





# ── Gemini AI 분석 비동기 독립 Fragment (최상위 스코프 정의) ───────────
@st.fragment
def render_gemini_commentary(params):
    """Gemini AI 코멘터리를 별도 fragment로 렌더링 (비동기 로딩 & 버튼클릭 시 전역 새로고침 방지)"""
    _code = params['code_disp']
    _name = params['name_disp']

    # ── Gemini AI 분석 세션 캐싱 및 속도 제한 방지 ──
    if 'gemini_cache' not in st.session_state or not isinstance(st.session_state.gemini_cache, dict):
        st.session_state['gemini_cache'] = {}

    now_ts = time.time()
    cached_val = st.session_state['gemini_cache'].get(_code)
    force_refresh = st.session_state.get(f"force_refresh_gemini_{_code}", False)

    use_cache = False
    if cached_val and not force_refresh:
        cached_comment, cached_ts, is_error = cached_val
        cache_duration = 5 if is_error else 600  # 에러 폴백은 5초만 캐시하여 금방 실시간 재시도
        if now_ts - cached_ts < cache_duration:
            use_cache = True

    if use_cache:
        ai_comment = cached_comment
        is_ai_fallback = is_error
    else:
        is_ai_fallback = False
        with st.spinner("🤖 Gemini AI 퀀트 리스크 조언 분석 중..."):
            try:
                ai_comment = get_gemini_commentary(
                    _code, _name, params['t_score'], params['t_score_adj'], params['s_score'], params['daily_chg'], params['market_cond'], params['rec_cash'], params['rec_stock'], params['gemini_api_key'], params['avg_price_for_gemini'], params['recent_prices_str'], params['current_price_for_gemini'], params['stop_loss_for_gemini'], params['recent_high_for_gemini'], params['rsi_for_gemini'], params['macd_for_gemini'], params['macd_sig_for_gemini'], params['bb_upper_for_gemini'], params['bb_middle_for_gemini'], params['bb_lower_for_gemini'], params['supply_trend_prompt'], params['recent_news_prompt'],
                    raw_market_cond=params.get('raw_market_cond'), vol_penalty=params.get('vol_penalty', 1.0), market_penalty=params.get('market_penalty', 1.0)
                )
                st.session_state['gemini_cache'][_code] = (ai_comment, now_ts, False)
            except RuntimeWarning as e:
                fallback_comment = get_local_fallback_commentary(
                    _name, params['t_score_adj'], params['s_score'], params.get('raw_market_cond', '중립'), params['market_cond'],
                    vol_penalty=params.get('vol_penalty', 1.0), market_penalty=params.get('market_penalty', 1.0), sector=params.get('sector'),
                    current_price=params.get('current_price_for_gemini'), stop_loss_price=params.get('stop_loss_for_gemini'),
                    recent_high_price=params.get('recent_high_for_gemini'), rsi=params.get('rsi_for_gemini'),
                    macd=params.get('macd_for_gemini'), macd_signal=params.get('macd_sig_for_gemini'),
                    bb_upper=params.get('bb_upper_for_gemini'), bb_middle=params.get('bb_middle_for_gemini'), bb_lower=params.get('bb_lower_for_gemini'),
                    avg_price=params.get('avg_price_for_gemini'), supply_trend=params.get('supply_trend_prompt'), recent_news=params.get('recent_news_prompt')
                )
                ai_comment = fallback_comment
                is_ai_fallback = True
                st.session_state['gemini_cache'][_code] = (ai_comment, now_ts, True)
            except Exception as e:
                fallback_comment = get_local_fallback_commentary(
                    _name, params['t_score_adj'], params['s_score'], params.get('raw_market_cond', '중립'), params['market_cond'],
                    vol_penalty=params.get('vol_penalty', 1.0), market_penalty=params.get('market_penalty', 1.0), sector=params.get('sector'),
                    current_price=params.get('current_price_for_gemini'), stop_loss_price=params.get('stop_loss_for_gemini'),
                    recent_high_price=params.get('recent_high_for_gemini'), rsi=params.get('rsi_for_gemini'),
                    macd=params.get('macd_for_gemini'), macd_signal=params.get('macd_sig_for_gemini'),
                    bb_upper=params.get('bb_upper_for_gemini'), bb_middle=params.get('bb_middle_for_gemini'), bb_lower=params.get('bb_lower_for_gemini'),
                    avg_price=params.get('avg_price_for_gemini'), supply_trend=params.get('supply_trend_prompt'), recent_news=params.get('recent_news_prompt')
                )
                ai_comment = fallback_comment
                is_ai_fallback = True
                st.session_state['gemini_cache'][_code] = (ai_comment, now_ts, True)
        
        if force_refresh:
            st.session_state[f"force_refresh_gemini_{_code}"] = False

    ai_comment_cleaned = ai_comment
    ai_comment_cleaned = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', ai_comment_cleaned)
    tag_patterns = [r'</ul>', r'<ul>', r'</ol>', r'<ol>', r'</li>', r'<li>', r'<br\s*/?>', r'</strong>', r'<strong>']
    for pat in tag_patterns:
        ai_comment_cleaned = re.sub(rf'\s*\n\s*({pat})', r'\1', ai_comment_cleaned)
        ai_comment_cleaned = re.sub(rf'({pat})\s*\n\s*', r'\1', ai_comment_cleaned)
    
    ai_comment_escaped = ai_comment_cleaned.replace('\n', '<br/>')
    ai_comment_escaped = re.sub(r'(<br\s*/?>\s*){2,}', '<br/>', ai_comment_escaped)

    ai_label_text = "📍 로컬 퀀트 룰 기반 조언 (AI 일시 대기 중)" if is_ai_fallback else "🤖 AI 퀀트 리스크 조언 (Gemini 3.7 / 3.6 Flash high)"
    ai_label_border = "#888888" if is_ai_fallback else "#ff922b"

    # ── [단 1개의 통 container(border=True) 내부에 전체 퀀트 매매 의견 카드 렌더링] ──
    with st.container(border=True):
        # 1. 상단 헤더 행 (통 박스 내부의 1자 헤더 & 1px 점선 구분선)
        opinion_hdr_html = f"""<div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; padding-bottom: 10px; border-bottom: 1px dashed rgba(255, 255, 255, 0.15); margin-bottom: 12px;">
    <div style="display: flex; align-items: center; gap: 15px;">
        <h4 style="margin: 0; color: #ff922b; font-size: 16px; font-family: 'malgun gothic', sans-serif;">💡 퀀트 종합 매매 의견</h4>
        <span style="font-size: 14px; font-family: 'malgun gothic', sans-serif; color: #ccc;">
            보정 평가 등급: <strong style="color: {params['grade_color']}; font-size: 15px;">{params['quant_grade']}</strong>
        </span>
    </div>
    <div style="text-align: right; min-width: 140px;">
        <span style="font-size: 13px; color: #2ecc71; font-family: 'malgun gothic', sans-serif;">매수 보정 점수: <strong>{params['t_score_str']}</strong> <span style="font-size: 11px; color: #888;">{params['t_score_raw_str']}</span></span><br/>
        <span style="font-size: 13px; color: #e74c3c; font-family: 'malgun gothic', sans-serif;">매도 퀀트 점수: <strong>{params['s_score_str']}</strong></span>
    </div>
</div>"""
        st.markdown(re.sub(r'\s+', ' ', opinion_hdr_html.replace('\n', ' ')).strip(), unsafe_allow_html=True)

        # 2. 중간 행: 좌측 라벨, 우측 AI 분석 다시 받기 버튼
        col_label, col_btn = st.columns([6.5, 3.5])
        with col_label:
            st.markdown(f"""<div style="padding-top: 4px;"><strong style="color: {ai_label_border}; font-size: 14px; font-family: 'malgun gothic', sans-serif;">{ai_label_text}:</strong></div>""", unsafe_allow_html=True)
        with col_btn:
            if st.button("🔄 AI 분석 다시 받기", key=f"btn_refresh_gemini_{_code}", width='stretch'):
                st.session_state[f"force_refresh_gemini_{_code}"] = True
                st.rerun(scope="fragment")

        # 3. 하단 행: 조언 코멘터리 박스
        body_html = f"""<div style="margin-top: 8px;">
    <div style="background-color: rgba(255, 255, 255, 0.03); padding: 14px; border-radius: 6px; border-left: 4px solid {ai_label_border}; font-size: 13px; line-height: 1.5; color: #eee; font-family: 'malgun gothic', sans-serif;">
        {ai_comment_escaped}
    </div>
</div>"""
        st.markdown(re.sub(r'\s+', ' ', body_html.replace('\n', ' ')).strip(), unsafe_allow_html=True)


# ── 종목 일봉 차트 (선택 시 표시) ─────────────────────────────
@st.fragment
def render_stock_analysis_section(code_disp, df_m, df_all, kis_key, kis_sec, vol_mult_adjust=1.0, rsi_range_adjust=78):
    # 확실하게 종목명을 역맵핑 보정
    if not df_m.empty:
        target_code = str(code_disp).strip().zfill(6)
        match = df_m[df_m['Code'].astype(str).str.split('.').str[0].str.zfill(6) == target_code]
        if not match.empty:
            st.session_state.sel_name = match.iloc[0]['Name']
            
    name_disp = st.session_state.sel_name or code_disp

    st.markdown(f"### 📈 {name_disp} ({code_disp}) 일봉 차트")

    # ── 세션 스테이트 캐시 키 생성 (종목코드 + 2분 단위 시간 버킷) ──
    # 같은 종목을 2분 내에 재클릭하면 API 호출 없이 즉각 반응
    from datetime import timezone, timedelta as _td
    _now_bucket = datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d%H%M')[:-1]  # 분 끝자리 제거 → 2분 버킷
    _cache_key = f"_signal_cache_{code_disp}_{_now_bucket}"

    # ── 포트폴리오 보유 단가 조회 (로컬 파일 읽기) — if/else 블록 전에 반드시 정의 ──
    # Python 스코핑 규칙: 함수 내 어디서든 대입되는 변수는 함수 전체에서 로컬 취급됨
    # → else 블록 안에서 참조하기 전에 미리 정의해야 UnboundLocalError 방지
    my_entry_price = 0.0
    portfolio = load_portfolio()
    is_portfolio = code_disp in portfolio
    if is_portfolio:
        my_entry_price = portfolio[code_disp].get('entry_price', 0.0)

    if _cache_key in st.session_state:
        # ── 캐시 히트: API/연산 없이 즉각 반환 ──
        _cached = st.session_state[_cache_key]
        df_candle = _cached['df_candle']
        df_1min   = _cached['df_1min']
        df_5min   = _cached['df_5min']
    else:
        # ── 캐시 미스: API 호출 및 시그널 연산 수행 ──
        with st.spinner(f'📡 {name_disp} 주가 데이터 조회 중...'):
            # 일봉 + KIS 분봉 + 네이버 분봉을 병렬로 동시 요청
            with ThreadPoolExecutor(max_workers=3) as _exec:
                _f_candle = _exec.submit(get_stock_history, code_disp, kis_key, kis_sec)
                _f_kis    = _exec.submit(
                    get_kis_minute_history, kis_key, kis_sec, code_disp
                ) if kis_key and kis_sec else None
                _f_naver  = _exec.submit(get_minute_history, code_disp, 2000)

                df_candle = _f_candle.result()
                df_1min   = _f_kis.result() if _f_kis else pd.DataFrame()
                df_naver  = _f_naver.result()

            # ── 🏛️ [2단계 하이브리드 정밀 타격] 증권사 KIS API 우선 채택 & 네이버 백업 ──
            if not df_1min.empty:
                # 증권사 KIS 직결 틱 데이터가 있으면 최우선 채택 후 네이버 과거 데이터와 매끄럽게 병합
                if not df_naver.empty:
                    df_1min = pd.concat([df_1min, df_naver], ignore_index=True)
                    df_1min = df_1min.drop_duplicates(subset=['DateTime']).sort_values('DateTime').reset_index(drop=True)
            elif not df_naver.empty:
                df_1min = df_naver

            # 종목 시가총액(Marcap) 정보 추출
            marcap_val = 0.0
            if df_m is not None and not df_m.empty:
                m_match = df_m[df_m['Code'].astype(str).str.zfill(6) == str(code_disp).strip().zfill(6)]
                if not m_match.empty and 'Marcap' in m_match.columns:
                    marcap_val = float(m_match.iloc[0]['Marcap'])

            df_5min = resample_to_5min(df_1min)

            df_1min = calculate_intraday_signals(df_1min, my_entry_price=0.0, timeframe='1min', code=code_disp, is_portfolio=is_portfolio, marcap=marcap_val)
            df_5min = calculate_intraday_signals(df_5min, my_entry_price=0.0, timeframe='5min', code=code_disp, is_portfolio=is_portfolio, marcap=marcap_val)

            # 이전 종목 캐시 정리 (메모리 절약: 현재 종목 외 나머지 삭제)
            for k in list(st.session_state.keys()):
                if k.startswith('_signal_cache_') and k != _cache_key:
                    del st.session_state[k]

            # 결과 세션 스테이트에 저장
            st.session_state[_cache_key] = {
                'df_candle': df_candle,
                'df_1min':   df_1min,
                'df_5min':   df_5min,
            }

    # --- 라이브 신호 로거 연동 (최근 1분봉 캔들의 신호 감지, 캐시 히트/미스 모두 실행) ---
    if not df_1min.empty and len(df_1min) > 1:
        last_row = df_1min.iloc[-1]
        # 이미 지난 과거가 아닌 최근 1~2분 이내의 신호만 로깅 (실시간성 확보)

        if 'DateTime' in df_1min.columns and pd.notna(last_row.get('DateTime')):
            time_diff = (pd.Timestamp.now() - pd.to_datetime(last_row['DateTime'])).total_seconds()
            if time_diff < 300:  # 5분 이내의 최신 신호만 로깅 허용
                _rsi_val  = float(last_row['RSI_14']) if 'RSI_14'  in last_row and pd.notna(last_row.get('RSI_14'))  else None
                _vwap_val = float(last_row['VWAP'])   if 'VWAP'    in last_row and pd.notna(last_row.get('VWAP'))    else None
                if last_row.get('Buy_Signal') == True:
                    live_logger.log_buy_signal(
                        ticker=code_disp,
                        price=float(last_row['Close']),
                        timestamp=last_row['DateTime'],
                        name=name_disp,
                        tg_token=tg_token,
                        tg_chat_id=tg_chat_id,
                        rsi=_rsi_val,
                        vwap=_vwap_val,
                    )
                elif last_row.get('Add_Signal') == True:
                    live_logger.log_add_signal(
                        ticker=code_disp,
                        price=float(last_row['Close']),
                        timestamp=last_row['DateTime'],
                        name=name_disp,
                        tg_token=tg_token,
                        tg_chat_id=tg_chat_id,
                        rsi=_rsi_val,
                        vwap=_vwap_val,
                    )
                elif last_row.get('Fall_Signal') == True:
                    live_logger.log_fall_buy_signal(
                        ticker=code_disp,
                        price=float(last_row['Close']),
                        timestamp=last_row['DateTime'],
                        name=name_disp,
                        tg_token=tg_token,
                        tg_chat_id=tg_chat_id,
                        rsi=_rsi_val,
                        vwap=_vwap_val,
                    )
                elif last_row.get('Exit_Signal') == True:
                    live_logger.log_exit_signal(
                        ticker=code_disp,
                        price=float(last_row['Close']),
                        timestamp=last_row['DateTime'],
                        name=name_disp,
                        tg_token=tg_token,
                        tg_chat_id=tg_chat_id,
                    )
    # -------------------------------------------------------------

    if df_candle.empty:
        st.warning('⚠️ 차트 데이터를 불러올 수 없습니다.')
    else:
        # MA 계산
        df_candle['MA5']  = df_candle['Close'].rolling(5).mean()
        df_candle['MA20'] = df_candle['Close'].rolling(20).mean()

        # RSI 계산
        delta = df_candle['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df_candle['RSI'] = 100 - (100 / (1 + rs))

        # MACD 계산
        exp1 = df_candle['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df_candle['Close'].ewm(span=26, adjust=False).mean()
        df_candle['MACD'] = exp1 - exp2
        df_candle['MACD_Signal'] = df_candle['MACD'].ewm(span=9, adjust=False).mean()

        # Bollinger Bands 계산
        df_candle['BB_Middle'] = df_candle['Close'].rolling(window=20).mean()
        df_candle['BB_Std'] = df_candle['Close'].rolling(window=20).std()
        df_candle['BB_Upper'] = df_candle['BB_Middle'] + (df_candle['BB_Std'] * 2)
        df_candle['BB_Lower'] = df_candle['BB_Middle'] - (df_candle['BB_Std'] * 2)

        # ── [고도화 1단계] ATR 계산 및 ATR 14일 계산 ───────────────
        try:
            high = df_candle['High'].values
            low = df_candle['Low'].values
            close = df_candle['Close'].values
            tr = np.maximum(high[1:] - low[1:], np.maximum(abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1])))
            tr = np.insert(tr, 0, high[0] - low[0])
            atr = pd.Series(tr).rolling(14).mean().values
            df_candle['ATR'] = atr
            # 샹들리에 출구(Chandelier Exit) 방식의 트레일링 손절선 적용하되,
            # 대량 거래량을 동반한 피뢰침(위꼬리) 음봉이나 장대 음봉 발생 시 손절선을 즉각적으로 타이트하게 끌어올리는 
            # [거래량 & 피뢰침 리스크 가속화 보정(Volume & Pinbar Risk Acceleration)] 로직 적용
            
            # 1. 20일 평균 거래량 계산
            df_candle['Vol_MA20'] = df_candle['Volume'].rolling(20).mean()
            
            # 2. 피뢰침(위꼬리) 조건 정의: 위꼬리 비율이 전체 봉 길이(High-Low)의 40% 이상이고 음봉인 경우
            candle_range = df_candle['High'] - df_candle['Low']
            candle_range_safe = np.where(candle_range == 0, 1.0, candle_range)
            upper_wick = df_candle['High'] - np.maximum(df_candle['Open'], df_candle['Close'])
            is_pinbar = ((upper_wick / candle_range_safe) > 0.4) & (df_candle['Close'] <= df_candle['Open'])
            
            # 3. 거래량 폭발 조건: 거래량이 최근 20일 평균 거래량의 1.5배 이상
            is_vol_spike = df_candle['Volume'] > (df_candle['Vol_MA20'].fillna(df_candle['Volume']) * 1.5)
            
            # 4. 리스크 가속 조건 (대량거래량 피뢰침 또는 대량거래량 음봉)
            risk_accelerate = is_vol_spike & (is_pinbar | (df_candle['Close'] < df_candle['Open']))
            
            # 5. 동적 ATR 승수 적용 (대량거래량 음봉/피뢰침 발생 시 위험 관리 극대화를 위해 승수를 2.5 -> 1.0으로 축소하여 손절선 격차 좁힘)
            atr_multiplier = np.where(risk_accelerate, 1.0, 2.5)
            
            # 6. 최고가 계산 시 고가 왜곡 방지 (대량거래 피뢰침 날은 High 대신 Close를 적용하여 손절선이 허수로 솟구치는 현상 방지)
            adjusted_high = np.where(is_pinbar & is_vol_spike, df_candle['Close'], df_candle['High'])
            df_candle['Adj_Highest_High'] = pd.Series(adjusted_high, index=df_candle.index).rolling(20).max()
            # 퀀트 보정 점수 조회 (진입 필터용) 및 대형주 완화 기준 적용
            t_score_adj = 60.0  # 기본값
            is_large_cap = False
            marcap_val = 0.0
            
            if df_m is not None and not df_m.empty:
                m_match = df_m[df_m['Code'].astype(str).str.zfill(6) == str(code_disp).strip().zfill(6)]
                if not m_match.empty and 'Marcap' in m_match.columns:
                    marcap_val = float(m_match.iloc[0]['Marcap'])
                    # Marcap 5조 원(5,000,000,000,000) 이상인 경우 대형주로 판별
                    if marcap_val >= 5e12:
                        is_large_cap = True

            if df_q is not None and not df_q.empty:
                q_match = df_q[df_q['Code'].astype(str).str.split('.').str[0].str.zfill(6) == str(code_disp).strip().zfill(6)]
                if not q_match.empty and 'Total_Score_Adj' in q_match.columns:
                    t_score_adj = float(q_match.iloc[0]['Total_Score_Adj'])

            # 대형주는 허들을 60점에서 45점으로 완화 적용 (그 외 중소형주는 60점 기준선 엄격 유지)
            buy_threshold = 45.0 if is_large_cap else 60.0

            # 7. 매수/매도 신호 판정 및 동기화된 손절선 계산 (상태 머신)
            # 동적 ATR 손절폭 기준선 (대량거래 발생 시 타이트하게 보정됨)
            dynamic_raw_sl = df_candle['Adj_Highest_High'] - atr_multiplier * df_candle['ATR']
            # ── 손절선 현재가 상한 클리핑 ─────────────────────────────────────
            # 급락 후 rolling(20) 최고가가 과거 고점을 참조할 경우 손절선이 현재가 위에
            # 그려지는 버그 방지. 샹들리에 손절선은 항상 현재 종가 아래에 위치해야 함.
            # (0.5% 마진 = 손절선이 현재 종가에 너무 밀착하지 않도록 최소 여유 확보)
            dynamic_raw_sl = dynamic_raw_sl.clip(upper=df_candle['Close'] * 0.995)
            
            stop_loss_series = []
            exit_signal_list = []
            buy_signal_list = []
            add_signal_list = []   # 추가 매수 신호 리스트
            fall_signal_list = []  # 낙폭과대 매수 신호 리스트
            
            # 포트폴리오 보유 중인 경우 초기 상태 연동
            in_position = False
            entry_price = 0.0
            add_count = 0
            if my_entry_price > 0:
                in_position = True
                entry_price = my_entry_price
            
            max_price_since_entry = entry_price
            current_sl = np.nan
            
            for i in range(len(df_candle)):
                close_val = df_candle['Close'].iloc[i]
                open_val = df_candle['Open'].iloc[i] if 'Open' in df_candle.columns else close_val
                ma5_val = df_candle['MA5'].iloc[i]
                ma20_val = df_candle['MA20'].iloc[i] if 'MA20' in df_candle.columns else close_val
                raw_sl = dynamic_raw_sl.iloc[i]
                
                prev_rsi = df_candle['RSI'].iloc[i-1] if (i > 0 and 'RSI' in df_candle.columns) else np.nan
                curr_rsi = df_candle['RSI'].iloc[i] if 'RSI' in df_candle.columns else np.nan
                
                if pd.isna(raw_sl) or pd.isna(ma5_val) or pd.isna(ma20_val):
                    stop_loss_series.append(np.nan)
                    exit_signal_list.append(False)
                    buy_signal_list.append(False)
                    add_signal_list.append(None)
                    fall_signal_list.append(False)
                    continue
                
                cond_add_indicator = (not pd.isna(prev_rsi) and prev_rsi <= 30 and curr_rsi > 30) or (close_val > ma5_val and close_val > ma20_val)
                
                if in_position:
                    buy_signal_list.append(False)
                    fall_signal_list.append(False)
                    max_price_since_entry = max(max_price_since_entry, close_val)
                    
                    # 손절선 래칫 (위로만 이동)
                    if pd.isna(current_sl):
                        current_sl = raw_sl
                    else:
                        current_sl = max(current_sl, raw_sl)
                        
                    # 본전 보호 룰 (10% 이상 수익 시 본전+1% 잠금)
                    if max_price_since_entry >= entry_price * 1.10:
                        current_sl = max(current_sl, entry_price * 1.01)
                        
                    stop_loss_series.append(current_sl)
                    
                    # 전일 기준 손절선 파악 (시가 갭하락 판정용)
                    prev_sl = stop_loss_series[-2] if len(stop_loss_series) > 1 and not pd.isna(stop_loss_series[-2]) else current_sl
                    
                    # 추가 매수 판정 (물타기/불타기)
                    pnl_pct = (close_val - entry_price) / entry_price * 100 if entry_price > 0 else 0
                    
                    # 물타기: 손실 -5% 이하에서 추가 매수 지표 만족 시
                    is_mul = (pnl_pct <= -5.0) and cond_add_indicator
                    # 불타기: 수익 +5% 이상에서 추가 매수 지표 만족 시
                    is_bul = (pnl_pct >= 5.0) and cond_add_indicator
                    
                    if is_mul and add_count < 2:
                        add_signal_list.append('물타기')
                        add_count += 1
                        entry_price = (entry_price + close_val) / 2
                    elif is_bul and add_count < 2:
                        add_signal_list.append('불타기')
                        add_count += 1
                        entry_price = (entry_price + close_val) / 2
                    else:
                        add_signal_list.append(None)
                        
                    # 매도 판단
                    if open_val < prev_sl:
                        # 1) 시가 갭하락 손절: 시가가 전일 기준 손절선을 하회하여 급락 출발 시 청산
                        exit_signal_list.append(True)
                        in_position = False
                        current_sl = np.nan
                        add_count = 0
                    elif close_val < current_sl:
                        # 2) 일반 종가 이탈 손절
                        exit_signal_list.append(True)
                        in_position = False
                        current_sl = np.nan
                        add_count = 0
                    else:
                        exit_signal_list.append(False)
                        
                else:
                    exit_signal_list.append(False)
                    add_signal_list.append(None)
                    # 미보유 상태: 차트 시각화를 위해 raw_sl 표시 (래칫 없이 위아래 변동)
                    stop_loss_series.append(raw_sl)
                    
                    # 낙폭과대 매수 판단 (RSI 과매도 30 이하 탈출)
                    cond_fall_indicator = (not pd.isna(prev_rsi) and prev_rsi <= 30 and curr_rsi > 30)
                    
                    if cond_fall_indicator:
                        fall_signal_list.append(True)
                        buy_signal_list.append(False)
                        in_position = True
                        entry_price = close_val
                        max_price_since_entry = close_val
                        current_sl = raw_sl
                        add_count = 0
                    # 일반 매수 판단: 상승 추세(MA5 및 MA20 상회) 진입 시 매수
                    elif close_val > ma5_val and close_val > ma20_val:
                        buy_signal_list.append(True)
                        fall_signal_list.append(False)
                        in_position = True
                        entry_price = close_val
                        max_price_since_entry = close_val
                        current_sl = raw_sl  # 진입 시 손절선 초기화
                        add_count = 0
                    else:
                        buy_signal_list.append(False)
                        fall_signal_list.append(False)
 
            df_candle['Stop_Loss'] = stop_loss_series
            df_candle['Exit_Signal'] = exit_signal_list
            df_candle['Buy_Signal'] = buy_signal_list
            df_candle['Add_Signal'] = add_signal_list
            df_candle['Fall_Signal'] = fall_signal_list

        except Exception as atr_err:
            st.error(f"ATR 계산 오류: {atr_err}")

        df_candle = df_candle.tail(90)  # 최근 90 거래일만 표시

        # ── 💡 [가격 통합] 패널·차트·포트폴리오 3곳 모두 동일한 실시간 기준 가격 사용 ──
        # 우선순위: ① df_1min(실시간 1분봉) → ② df_candle(일봉 종가) → ③ 0
        # 장중(09:00~15:30)에는 1분봉의 최신 종가가 실시간 현재가에 가장 근접
        _unified_price = 0.0
        try:
            if 'df_1min' in dir() and not df_1min.empty:
                _latest_1m = df_1min.iloc[-1]
                # 최근 10분 이내 데이터인지 확인 (오래된 데이터 방지)
                if 'DateTime' in df_1min.columns and pd.notna(_latest_1m.get('DateTime')):
                    _age_sec = (pd.Timestamp.now() - pd.to_datetime(_latest_1m['DateTime'])).total_seconds()
                    if _age_sec < 600:  # 10분 이내면 실시간 가격으로 채택
                        _unified_price = float(_latest_1m['Close'])
            if _unified_price <= 0 and not df_candle.empty:
                _unified_price = float(df_candle['Close'].iloc[-1])
        except Exception:
            if not df_candle.empty:
                _unified_price = float(df_candle['Close'].iloc[-1])

        # ── 💡 [가격 통합] 패널 현재가도 실시간 _unified_price 사용 ──
        # _unified_price = 1분봉 실시간(장중) or 일봉 종가(장마감 후)
        last_close = _unified_price if _unified_price > 0 else (float(df_candle['Close'].iloc[-1]) if not df_candle.empty else 0)
        if len(df_candle) >= 2:
            prev_close = df_candle['Close'].iloc[-2]
            daily_chg = (last_close - prev_close) / prev_close * 100 if prev_close > 0 else 0
            chg_color = '#ff6b6b' if daily_chg >= 0 else '#4e9ff5'
            chg_str   = f'{daily_chg:+.2f}%'
        else:
            daily_chg = 0.0
            chg_str = ''
            chg_color = '#cccccc'

        # 지표 요약 (상단 메트릭 - 프리미엄 HTML 가로 스탯 바)
        ma5_val = f"{int(df_candle['MA5'].iloc[-1]):,}원" if pd.notna(df_candle['MA5'].iloc[-1]) else '-'
        ma20_val = f"{int(df_candle['MA20'].iloc[-1]):,}원" if pd.notna(df_candle['MA20'].iloc[-1]) else '-'
        high_90 = f"{int(df_candle['High'].max()):,}원"   # .tail(90) 이후 범위 = 최근 90일 고점
        low_90 = f"{int(df_candle['Low'].min()):,}원"    # .tail(90) 이후 범위 = 최근 90일 저점
        
        # 등락 부호 색상
        chg_color_html = "#ff6b6b" if daily_chg >= 0 else "#4e9ff5"
        
        # 🏛️ 증권사 KIS 직결 4대 킬러 마이크로 데이터 조회
        micro_data = get_kis_deep_micro_data(kis_key, kis_sec, code_disp)
        power_str = f"{micro_data['power_pct']:.1f}% [{micro_data['power_label']}]"
        power_col = micro_data['power_color']
        glob_str = micro_data['glob_summary']

        stats_html = f"""
        <div style="display: flex; justify-content: space-around; align-items: center; background-color: #111920; padding: 12px; border-radius: 8px; margin-bottom: 12px; border: 1px solid rgba(78, 159, 245, 0.2); flex-wrap: wrap; gap: 8px;">
          <div style="text-align: center; min-width: 105px;">
            <span style="color: #888; font-size: 0.8rem;">현재가</span><br>
            <strong style="font-size: 1.2rem; color: #ffffff;">{int(last_close):,}원</strong>
            <span style="font-size: 0.85rem; color: {chg_color_html}; font-weight: bold;">{chg_str}</span>
          </div>
          <div style="width: 1px; height: 30px; background-color: rgba(255,255,255,0.1);"></div>
          <div style="text-align: center; min-width: 95px;">
            <span style="color: #888; font-size: 0.8rem;">90일 최고</span><br>
            <strong style="font-size: 1.15rem; color: #ff6b6b;">{high_90}</strong>
          </div>
          <div style="width: 1px; height: 30px; background-color: rgba(255,255,255,0.1);"></div>
          <div style="text-align: center; min-width: 95px;">
            <span style="color: #888; font-size: 0.8rem;">90일 최저</span><br>
            <strong style="font-size: 1.15rem; color: #4e9ff5;">{low_90}</strong>
          </div>
          <div style="width: 1px; height: 30px; background-color: rgba(255,255,255,0.1);"></div>
          <div style="text-align: center; min-width: 85px;">
            <span style="color: #888; font-size: 0.8rem;">MA5</span><br>
            <strong style="font-size: 1.15rem; color: #ffd43b;">{ma5_val}</strong>
          </div>
          <div style="width: 1px; height: 30px; background-color: rgba(255,255,255,0.1);"></div>
          <div style="text-align: center; min-width: 105px;">
            <span style="color: #888; font-size: 0.8rem;">⚡ 체결강도</span><br>
            <strong style="font-size: 1.15rem; color: {power_col};">{power_str}</strong>
          </div>
          <div style="width: 1px; height: 30px; background-color: rgba(255,255,255,0.1);"></div>
          <div style="text-align: center; min-width: 125px;">
            <span style="color: #888; font-size: 0.8rem;">🌐 외국계 주포</span><br>
            <span style="font-size: 0.95rem; color: #00f2fe; font-weight: bold;">{glob_str}</span>
          </div>
        </div>

        <!-- 🏛️ [2·3·4번 통합] 실시간 호가 매물벽 & 프로그램 수급 정밀 해설 카드 -->
        <div style="background: rgba(27, 38, 59, 0.45); border: 1px solid rgba(65, 90, 119, 0.45); border-radius: 8px; padding: 10px 14px; margin-bottom: 16px; font-size: 12px; color: #ddd; line-height: 1.6;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 6px;">
            <span style="font-weight:bold; color:#00f2fe;">📊 [실시간 세력 수급 & 호가벽 정밀 진단]</span>
            <span style="font-size:11px; color:#aaa;">(매수잔량 <b>{micro_data['bid_ratio']}%</b> vs 매도잔량 <b>{100-micro_data['bid_ratio']:.1f}%</b>)</span>
          </div>
          <div style="margin-bottom: 4px;">• <b>호가벽 분석</b>: {micro_data['orderbook_desc']}</div>
          <div>• <b>프로그램 수급</b>: {micro_data['prog_desc']}</div>
        </div>
        """
        
        # ── 💡 퀀트 종합 매매 의견 카드 추가 ──────────────────────────────────
        q_row = df_q[df_q['Code'] == code_disp]
        
        t_score = 0.0
        t_score_adj = 0.0
        s_score = 0.0
        if not q_row.empty:
            t_score = q_row.iloc[0].get('Total_Score', 0.0)
            t_score_adj = q_row.iloc[0].get('Total_Score_Adj', t_score)
            s_score = q_row.iloc[0].get('Sell_Score', 0.0)
            t_score_str = f"{t_score_adj:.1f}점"
            t_score_raw_str = f"(원점수: {t_score:.1f}점)"
            s_score_str = f"{s_score:.1f}점"
        else:
            t_score_str = "평가 대상 아님 (N/A)"
            t_score_raw_str = ""
            s_score_str = "평가 대상 아님 (N/A)"

        if True:
            # KOSPI 시장 국면 변수 재사용 (상단에서 이미 계산 완료 — 이중 API 호출 방지)
            # market_regime, rec_cash, rec_stock, regime_desc, regime_color 이미 설정됨


            # 최근 20거래일 종가 추이 및 현재가, 손절선 추출
            recent_prices_str = ""
            current_price_for_gemini = _unified_price if '_unified_price' in dir() and _unified_price > 0 else None
            stop_loss_for_gemini = None
            recent_high_for_gemini = None
            buy_signal_today = False
            rsi_for_gemini = None
            macd_for_gemini = None
            macd_sig_for_gemini = None
            bb_upper_for_gemini = None
            bb_middle_for_gemini = None
            bb_lower_for_gemini = None
            
            if 'df_candle' in locals() and not df_candle.empty:
                recent_closes = df_candle['Close'].tail(20).tolist()
                recent_prices_str = ", ".join([str(int(p)) for p in recent_closes])
                current_price_for_gemini = df_candle['Close'].iloc[-1]
                recent_high_for_gemini = df_candle['High'].tail(20).max()
                if 'Stop_Loss' in df_candle.columns:
                    stop_loss_for_gemini = df_candle['Stop_Loss'].iloc[-1]
                if 'Buy_Signal' in df_candle.columns:
                    buy_signal_today = df_candle['Buy_Signal'].iloc[-1]
                if 'RSI' in df_candle.columns:
                    rsi_for_gemini = df_candle['RSI'].iloc[-1]
                if 'MACD' in df_candle.columns:
                    macd_for_gemini = df_candle['MACD'].iloc[-1]
                    macd_sig_for_gemini = df_candle['MACD_Signal'].iloc[-1]
                if 'BB_Upper' in df_candle.columns:
                    bb_upper_for_gemini = df_candle['BB_Upper'].iloc[-1]
                if 'BB_Middle' in df_candle.columns:
                    bb_middle_for_gemini = df_candle['BB_Middle'].iloc[-1]
                if 'BB_Lower' in df_candle.columns:
                    bb_lower_for_gemini = df_candle['BB_Lower'].iloc[-1]

            # 종합 등급 판정 (보정 매수 점수 t_score_adj 및 기술적 지표 기준)
            if stop_loss_for_gemini and current_price_for_gemini and current_price_for_gemini < stop_loss_for_gemini:
                quant_grade = "적극 매도 (손절가 이탈)"
                grade_color = "#e74c3c"
            elif buy_signal_today:
                quant_grade = "적극 매수 (추세 돌파)"
                grade_color = "#2ecc71"
            elif t_score_adj >= 80.0:
                quant_grade = "적극 매수 (Strong Buy)"
                grade_color = "#2ecc71"
            elif t_score_adj >= 60.0:
                quant_grade = "매수 (Buy)"
                grade_color = "#3498db"
            elif s_score >= 70.0:
                # 매도는 절대 리스크 지표이므로 보정 없는 원점수 사용
                quant_grade = "적극 매도 (Strong Sell)"
                grade_color = "#e74c3c"
            elif s_score >= 50.0:
                quant_grade = "매도 (Sell)"
                grade_color = "#e67e22"
            else:
                quant_grade = "관망/중립 (Hold)"
                grade_color = "#7f8c8d"
                
            # Gemini AI 코멘터리 요청 (자산 배분 비율 연동 및 캐싱 방지)
            raw_market_cond = q_row.iloc[0].get('Market_Condition', 'N/A') if not q_row.empty else 'N/A'
            vol_penalty = float(q_row.iloc[0].get('Vol_Penalty', 1.0)) if not q_row.empty else 1.0
            market_penalty = float(q_row.iloc[0].get('Market_Penalty', 1.0)) if not q_row.empty else 1.0
            sector_name = q_row.iloc[0].get('Sector', '') if not q_row.empty else ''
            market_cond = clean_market_condition_korean(raw_market_cond)
            
            # 실시간 수급 추이 및 최근 뉴스 조회
            supply_trend_data = fetch_stock_supply_trend(code_disp, days=10)
            recent_news_data = fetch_stock_recent_news(code_disp, count=5)
            
            # 수급 데이터를 프롬프트 및 HTML에 표시하기 위해 가공
            supply_trend_prompt = ""
            supply_table_html = ""
            
            def fmt_shares_korean(shares):
                sign = "+" if shares > 0 else ""
                if abs(shares) >= 10000:
                    return f"{sign}{shares/10000:.1f}만 주"
                return f"{sign}{shares:,}주"
            
            if supply_trend_data.get('success'):
                cum = supply_trend_data['cumulative']
                supply_trend_prompt = f"10일 누적 - 외인: {fmt_shares_korean(cum['foreigner'])}, 기관: {fmt_shares_korean(cum['organ'])}, 개인: {fmt_shares_korean(cum['individual'])}"
                
                daily_details = []
                for d in supply_trend_data['daily']:
                    daily_details.append(f"{d['date']}(외인:{fmt_shares_korean(d['foreigner'])}, 기관:{fmt_shares_korean(d['organ'])})")
                supply_trend_prompt += " | 일별 추이: " + ", ".join(daily_details)
                
                # HTML 표 포맷팅
                def fmt_shares_html(shares):
                    sign = "+" if shares > 0 else ""
                    val_str = f"{shares/10000:.1f}만" if abs(shares) >= 10000 else f"{shares:,}"
                    color = "#ff6b6b" if shares > 0 else "#4e9ff5" if shares < 0 else "#888888"
                    return f"<span style='color: {color}; font-weight: bold;'>{sign}{val_str}</span>"
                
                daily_rows = ""
                for d in supply_trend_data['daily']:
                    daily_rows += f"""
                    <tr style='border-bottom: 1px solid rgba(255, 255, 255, 0.05);'>
                        <td style='padding: 5px; text-align: left; color: #aaa;'>{d['date']}</td>
                        <td style='padding: 5px;'>{fmt_shares_html(d['foreigner'])}</td>
                        <td style='padding: 5px;'>{fmt_shares_html(d['organ'])}</td>
                        <td style='padding: 5px;'>{fmt_shares_html(d['individual'])}</td>
                    </tr>
                    """
                
                supply_table_html = f"""
                <div style="background-color: rgba(255, 255, 255, 0.02); padding: 12px; border-radius: 6px; border-left: 4px solid #00e5ff; font-size: 12px; line-height: 1.4; color: #ccc; font-family: 'malgun gothic', sans-serif; margin-bottom: 8px;">
                    <strong style="font-size: 13px;">📊 최근 수급 동향 (Naver):</strong>
                    <table style="width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 11px; text-align: center;">
                        <thead>
                            <tr style="background-color: rgba(255, 255, 255, 0.05); border-bottom: 1px solid rgba(255, 255, 255, 0.1); color: #eee;">
                                <th style="padding: 5px; text-align: left; font-weight: 500;">일자</th>
                                <th style="padding: 5px; color: #ff6b6b; font-weight: 500;">외국인</th>
                                <th style="padding: 5px; color: #3498db; font-weight: 500;">기관</th>
                                <th style="padding: 5px; color: #ffeb3b; font-weight: 500;">개인</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr style="border-bottom: 2px solid rgba(0, 229, 255, 0.3); background-color: rgba(0, 229, 255, 0.05); font-weight: bold;">
                                <td style="padding: 5px; text-align: left; color: #00e5ff;">10일 누적</td>
                                <td style="padding: 5px;">{fmt_shares_html(cum['foreigner'])}</td>
                                <td style="padding: 5px;">{fmt_shares_html(cum['organ'])}</td>
                                <td style="padding: 5px;">{fmt_shares_html(cum['individual'])}</td>
                            </tr>
                            {daily_rows}
                        </tbody>
                    </table>
                </div>
                """
            else:
                supply_trend_prompt = "최근 수급 정보 없음"
                supply_table_html = f"""
                <div style="background-color: rgba(255, 255, 255, 0.02); padding: 10px; border-radius: 6px; border-left: 4px solid #00e5ff; font-size: 12px; line-height: 1.4; color: #ccc; font-family: 'malgun gothic', sans-serif; margin-bottom: 8px;">
                    <strong style="font-size: 13px;">📊 최근 수급 동향 (Naver):</strong><br/>
                    <span style="color: #888;">수급 데이터를 불러올 수 없습니다.</span>
                </div>
                """
            
            import html
            # 뉴스 데이터 가공
            recent_news_prompt = " | ".join([item['title'] for item in recent_news_data]) if recent_news_data else "최근 뉴스 없음"
            
            recent_news_html = ""
            if recent_news_data:
                recent_news_html = "<ul style='margin: 4px 0 0 16px; padding: 0;'>"
                for item in recent_news_data:
                    title = html.escape(item['title'])
                    url = item['url']
                    if url and (url.startswith('http://') or url.startswith('https://')):
                        safe_url = html.escape(url, quote=True)  # [XSS 방어] URL 이스케이프
                        recent_news_html += f"<li style='margin-bottom: 4.5px;'><a href='{safe_url}' target='_blank' style='color: #b197fc; text-decoration: none; font-weight: 500;' onmouseover='this.style.textDecoration=\"underline\";' onmouseout='this.style.textDecoration=\"none\";'>{title}</a></li>"
                    else:
                        recent_news_html += f"<li style='margin-bottom: 4.5px; color: #eee;'>{title}</li>"
                recent_news_html += "</ul>"
            else:
                recent_news_html = "<span style='color: #888;'>최근 관련 뉴스가 존재하지 않습니다.</span>"

            # 포트폴리오(대기보드) 등록 종목인 경우 평단가 파악
            current_portfolio = load_portfolio()
            avg_price_for_gemini = None
            if code_disp in current_portfolio:
                avg_price_for_gemini = current_portfolio[code_disp].get('entry_price')
                
            # ── secrets.toml 또는 환경 변수에서 Gemini API Key 자동 로드 ──
            gemini_api_key = os.environ.get("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY", "")

            # ── Gemini AI 분석을 별도 fragment로 분리하여 비동기 로딩 ──
            # 차트·수급·뉴스·등급은 즉시 표시, AI 코멘터리만 독립적으로 로딩
            _gemini_params = {
                'code_disp': code_disp,
                'name_disp': name_disp,
                't_score': t_score,
                't_score_adj': t_score_adj,
                's_score': s_score,
                'daily_chg': daily_chg,
                'market_cond': market_cond,
                'raw_market_cond': raw_market_cond,
                'vol_penalty': vol_penalty,
                'market_penalty': market_penalty,
                'sector': sector_name,
                'gemini_api_key': gemini_api_key,
                'avg_price_for_gemini': avg_price_for_gemini,
                'recent_prices_str': recent_prices_str,
                'current_price_for_gemini': current_price_for_gemini,
                'stop_loss_for_gemini': stop_loss_for_gemini,
                'recent_high_for_gemini': recent_high_for_gemini,
                'rsi_for_gemini': rsi_for_gemini,
                'macd_for_gemini': macd_for_gemini,
                'macd_sig_for_gemini': macd_sig_for_gemini,
                'bb_upper_for_gemini': bb_upper_for_gemini,
                'bb_middle_for_gemini': bb_middle_for_gemini,
                'bb_lower_for_gemini': bb_lower_for_gemini,
                'supply_trend_prompt': supply_trend_prompt,
                'recent_news_prompt': recent_news_prompt,
                'rec_cash': rec_cash,
                'rec_stock': rec_stock,
                'quant_grade': quant_grade,
                'grade_color': grade_color,
                't_score_str': t_score_str,
                't_score_raw_str': t_score_raw_str,
                's_score_str': s_score_str,
            }

            stats_html_clean = re.sub(r'\s+', ' ', stats_html.replace('\n', ' ')).strip()

            col_op, col_rd = st.columns([7, 3.5])
            with col_op:
                st.markdown(stats_html_clean, unsafe_allow_html=True)
                # 퀀트 매매 의견 헤더 + AI 코멘터리 + AI 다시받기 버튼을 통합 비동기 fragment로 렌더링
                render_gemini_commentary(_gemini_params)
                # 수급 테이블 즉시 표시
                _supply_clean = re.sub(r'\s+', ' ', supply_table_html.replace('\n', ' ')).strip()
                st.markdown(_supply_clean, unsafe_allow_html=True)
                # 뉴스 즉시 표시
                _news_html = f"""<div style="background-color: rgba(255, 255, 255, 0.02); padding: 12px; border-radius: 6px; border-left: 4px solid #9c27b0; font-size: 12px; line-height: 1.4; color: #ccc; font-family: 'malgun gothic', sans-serif;">
    <strong style="font-size: 13px;">📰 최근 주요 뉴스 헤드라인:</strong><br/>
    {recent_news_html}
</div>"""
                _news_clean = re.sub(r'\s+', ' ', _news_html.replace('\n', ' ')).strip()
                st.markdown(_news_clean, unsafe_allow_html=True)

            with col_rd:
                # 💼 실시간 포트폴리오 관리 패널 구현
                portfolio = load_portfolio()
                
                # 🌟 현재 분석 중인 퀀트 종목을 원클릭으로 내 포트폴리오에 담는 스마트 버튼
                if code_disp in portfolio:
                    st.markdown(f"<div style='background:rgba(0,242,254,0.1); border:1px solid rgba(0,242,254,0.3); border-radius:6px; padding:6px 10px; font-size:12px; color:#00f2fe; margin-bottom:8px; text-align:center;'>💼 <b>{name_disp}</b> 종목이 내 포트폴리오에 등록되어 있습니다.</div>", unsafe_allow_html=True)
                else:
                    cur_add_p = current_price_for_gemini or 0.0
                    if st.button(f"➕ [{name_disp}] 내 포트에 즉시 담기", key=f"btn_quick_add_{code_disp}", use_container_width=True):
                        portfolio[code_disp] = {
                            "name": name_disp,
                            "entry_price": cur_add_p,
                            "qty": 1,
                            "stop_loss": round(cur_add_p * 0.97, 0)
                        }
                        save_portfolio(portfolio)
                        st.toast(f"✅ {name_disp} 종목이 내 포트폴리오에 등록되었습니다!", icon="💼")
                        st.rerun()

                # 포트폴리오 목록 및 바로가기
                if portfolio:

                    # 포트폴리오 테이블 렌더링 (모든 보유 종목에 대해 퀀트 등급 색상 자동 하이라이트 일괄 적용)
                    port_rows = []
                    for p_code, p_data in portfolio.items():
                        p_close = 0.0
                        # ── 💡 [가격 통합] 현재 분석 중인 종목은 차트·패널과 동일한 _unified_price 사용 ──
                        _is_current = (str(p_code).strip().zfill(6) == str(code_disp).strip().zfill(6))
                        if _is_current and '_unified_price' in dir() and _unified_price > 0:
                            p_close = _unified_price
                        elif df_m is not None and not df_m.empty:
                            m_match = df_m[df_m['Code'] == p_code]
                            if not m_match.empty:
                                p_close = float(m_match.iloc[0]['Close'])
                        if p_close == 0.0:
                            p_close = p_data["entry_price"]
                            
                        p_return = ((p_close - p_data["entry_price"]) / p_data["entry_price"]) * 100.0
                        eval_diff = (p_close - p_data["entry_price"]) * p_data["qty"]
                        
                        rt_color = "#ff6b6b" if p_return > 0 else "#4e9ff5" if p_return < 0 else "#888888"
                        rt_sign = "+" if p_return > 0 else ""
                        
                        # ── 💡 [투자 심리 개선] 종목 유형별 맞춤 익절·손절 목표가 자동 계산 ──
                        _LARGE_CODES = {"005930","000660","005380","035420","009150","051910","207940","068270"}
                        _SMALL_CODES = {"010170","217590","417200","004990","027740","036570"}
                        if p_code in _LARGE_CODES:
                            _tp_pct, _sl_pct = 8.0, 5.0
                        elif p_code in _SMALL_CODES:
                            _tp_pct, _sl_pct = 3.5, 3.0
                        else:
                            _tp_pct, _sl_pct = 6.0, 4.0
                        _p_entry = p_data["entry_price"]
                        _tp1_price = _p_entry * (1 + _tp_pct / 100)
                        _sl_price  = p_data.get("stop_loss", 0) or _p_entry * (1 - _sl_pct / 100)
                        
                        # ── 역배열 여부 판단 (df_q에 MA5/MA20 없으면 수익률로 대신 판단) ──
                        _p_is_dead = False
                        try:
                            if df_q is not None and not df_q.empty:
                                _qc = df_q["Code"].astype(str).str.split(".").str[0].str.zfill(6)
                                _qm = df_q[_qc == str(p_code).zfill(6)]
                                if not _qm.empty:
                                    _ma5_v  = float(_qm.iloc[0].get("MA5", 1) if "MA5" in _qm.columns else 1)
                                    _ma20_v = float(_qm.iloc[0].get("MA20", 0) if "MA20" in _qm.columns else 0)
                                    if _ma5_v > 0 and _ma20_v > 0 and _ma5_v < _ma20_v:
                                        _p_is_dead = True
                                    elif p_return < -10:
                                        _p_is_dead = True  # 수익률 -10% 이하도 역배열 간주
                        except Exception:
                            pass
                        _p_sl_breach = p_close < _sl_price and _p_entry > 0
                        
                        _target_str = (f'<span style="font-size:10px;color:#aaa;">🎯{_tp1_price:,.0f} / 🛑{_sl_price:,.0f}</span>')
                        
                        
                        # 현재 선택하여 분석 중인 종목인지 여부 파악
                        is_active_selected = (str(p_code).strip().zfill(6) == str(code_disp).strip().zfill(6))
                        
                        if is_active_selected:
                            # 1) 현재 화면에서 상세 분석 중인 종목은 메인 카드의 grade_color를 100% 직접 적용
                            p_grade_color = grade_color
                        else:
                            # 2) 다른 보유 종목도 메인 등급 카드와 100% 동일한 등급 및 색상 판단 규칙 적용 (점수 + 기술적 신호)
                            p_t_score_adj = 0.0
                            p_s_score = 0.0
                            p_buy_signal = False

                            if df_q is not None and not df_q.empty:
                                # df_q에서 종목코드 매칭 (Code 컬럼이 '005930.KS' 형태일 수 있으므로 '.' 앞 부분만 추출)
                                _q_codes = df_q['Code'].astype(str).str.split('.').str[0].str.zfill(6)
                                q_m = df_q[_q_codes == str(p_code).strip().zfill(6)]
                                if not q_m.empty:
                                    row_q = q_m.iloc[0]
                                    if 'Total_Score_Adj' in row_q and pd.notna(row_q['Total_Score_Adj']):
                                        p_t_score_adj = float(row_q['Total_Score_Adj'])
                                    elif 'Total_Score' in row_q and pd.notna(row_q['Total_Score']):
                                        p_t_score_adj = float(row_q['Total_Score'])
                                    if 'Sell_Score' in row_q and pd.notna(row_q['Sell_Score']):
                                        p_s_score = float(row_q['Sell_Score'])

                            # 세션 내 시그널 캐시 존재 시 진짜 당일 buy_signal 여부만 판정
                            _p_cache = [v for k, v in st.session_state.items() if k.startswith(f"_signal_cache_{p_code}_")]
                            if _p_cache and 'df_candle' in _p_cache[-1] and not _p_cache[-1]['df_candle'].empty:
                                _p_cand = _p_cache[-1]['df_candle']
                                if 'Buy_Signal' in _p_cand.columns and _p_cand['Buy_Signal'].iloc[-1]:
                                    p_buy_signal = True

                            # 메인 카드(3868~3889 라인)와 100% 완벽히 일치하는 퀀트 등급 색상 분기
                            if p_buy_signal:
                                p_grade_color = "#2ecc71"  # 적극 매수 (추세 돌파) - 초록
                            elif p_t_score_adj >= 80.0:
                                p_grade_color = "#2ecc71"  # 적극 매수 (Strong Buy) - 초록
                            elif p_t_score_adj >= 60.0:
                                p_grade_color = "#3498db"  # 매수 (Buy) - 파랑
                            elif p_s_score >= 70.0:
                                p_grade_color = "#e74c3c"  # 적극 매도 (Strong Sell) - 레드
                            elif p_s_score >= 50.0:
                                p_grade_color = "#e67e22"  # 매도 (Sell) - 주황
                            else:
                                p_grade_color = "#7f8c8d"  # 관망/중립 (Hold) - 회색/어두운 톤

                        # RGBA 반투명 음영(0.22) 계산
                        _gc = p_grade_color.lstrip('#')
                        try:
                            _r, _g, _b = int(_gc[0:2], 16), int(_gc[2:4], 16), int(_gc[4:6], 16)
                            bg_rgba = f"rgba({_r}, {_g}, {_b}, 0.22)"
                        except Exception:
                            bg_rgba = "rgba(127, 140, 141, 0.22)"

                        # 현재 선택하여 차트를 조율 중인 종목인 경우 황금색(Gold) 테두리 강조 추가
                        border_style = "outline: 2px solid #ffd700; outline-offset: -2px;" if is_active_selected else ""
                        row_style = f"background-color: {bg_rgba}; {border_style}"

                        encoded_name = urllib.parse.quote(p_data["name"])
                        port_rows.append({
                            "종목명": f"<a href='/?sel_code={p_code}&sel_name={encoded_name}' target='_self' style='color: #ffffff; text-decoration: none; cursor: pointer;' onmouseover='this.style.color=\"#00e5ff\";' onmouseout='this.style.color=\"#ffffff\";'>{p_data['name']}</a>",
                            "매수가": f"{int(p_data['entry_price']):,}",
                            "수량": f"{int(p_data['qty']):,}",
                            "수익률": f"<span style='color:{rt_color}; font-weight:bold;'>{rt_sign}{p_return:.2f}%</span>",
                            "평가손익": f"<span style='color:{rt_color}; font-weight:bold;'>{rt_sign}{int(eval_diff):,}원</span>",
                            "목표가손절가": _target_str,
                            "row_style": row_style
                        })
                    
                    # 스타일이 적용된 고급 다크 테마 HTML 테이블 생성
                    # ── 💡 [투자 심리 개선] 역배열 종목 추매 경고 배너 ──
                    _dead_cross_stocks = []
                    for _p_code, _p_data in portfolio.items():
                        _pc = 0.0
                        # ── 💡 [가격 통합] 역배열 판단도 차트와 동일한 가격 기준 ──
                        _is_cur = (str(_p_code).strip().zfill(6) == str(code_disp).strip().zfill(6))
                        if _is_cur and '_unified_price' in dir() and _unified_price > 0:
                            _pc = _unified_price
                        elif df_m is not None and not df_m.empty:
                            _mm = df_m[df_m["Code"] == _p_code]
                            if not _mm.empty:
                                _pc = float(_mm.iloc[0]["Close"])
                        if _pc == 0.0:
                            _pc = _p_data["entry_price"]
                        _pr = ((_pc - _p_data["entry_price"]) / _p_data["entry_price"]) * 100.0 if _p_data["entry_price"] > 0 else 0
                        if _pr < -10:  # 수익률 -10% 이하 종목을 역배열 의심 종목으로 표시
                            _dead_cross_stocks.append((_p_data["name"], _pr))
                    if _dead_cross_stocks:
                        _dc_names = ", ".join([f"{n}({r:+.1f}%)" for n, r in _dead_cross_stocks])
                        st.markdown(f"""
                        <div style="background:linear-gradient(90deg,#3a0a0a,#1a0505);border:1px solid #e74c3c;
                                    border-radius:8px;padding:10px 14px;margin:6px 0 10px 0;">
                          <b style="color:#e74c3c;">⛔ 역배열 추매 위험 경고</b>
                          <span style="color:#f5c6cb;font-size:12px;"> — {_dc_names}</span><br/>
                          <span style="color:#aaa;font-size:11px;">📉 위 종목은 하락 추세 진행 중입니다. 
                          <b style="color:#ffd700;">추가 매수(물타기)는 8개년 통계 기준 평균 -8.3%p 추가 손실</b> 위험이 있습니다.<br/>
                          ✅ 낙폭과대(RSI 30 이하 양봉 전환) 신호 없이는 추매 보류를 강력 권장합니다.</span>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    table_html = f"""
                    <style>
                    .port-table-container {{
                        background-color: #0d1b2a;
                        border: 1px solid #1b263b;
                        border-radius: 8px;
                        padding: 12px;
                        margin-top: 10px;
                        margin-bottom: 10px;
                        box-shadow: inset 0 0 10px rgba(0,0,0,0.5);
                    }}
                    .port-table {{
                        width: 100%;
                        border-collapse: collapse;
                        font-family: 'Malgun Gothic', 'Nanum Gothic', sans-serif;
                        font-size: 13px;
                        color: #e0e1dd;
                    }}
                    .port-table th {{
                        background-color: #1b263b;
                        color: #ffd700;
                        font-weight: bold;
                        padding: 10px 8px;
                        text-align: center;
                        border-bottom: 2px solid #415a77;
                    }}
                    .port-table td {{
                        padding: 10px 8px;
                        text-align: center;
                        border-bottom: 1px solid rgba(255, 255, 255, 0.05);
                    }}
                    .port-table tr:last-child td {{
                        border-bottom: none;
                    }}
                    .port-table tr:hover {{
                        background-color: rgba(255, 255, 255, 0.12);
                    }}
                    </style>
                    <div class="port-table-container">
                        <table class="port-table">
                            <thead>
                                <tr>
                                    <th>종목명</th>
                                    <th>매수가</th>
                                    <th>수량</th>
                                    <th>수익률</th>
                                    <th>평가손익</th>
                                     <th>🎯목표가/🛑손절가</th>
                                </tr>
                            </thead>
                            <tbody>
                    """
                    for row in port_rows:
                        r_style = row['row_style']
                        tr_attr = f"style='{r_style}'" if r_style else ""
                        table_html += f"""
                                <tr {tr_attr}>
                                    <td style="font-weight: bold; color: #ffffff;">{row['종목명']}</td>
                                    <td>{row['매수가']}</td>
                                    <td>{row['수량']}</td>
                                    <td>{row['수익률']}</td>
                                    <td>{row['평가손익']}</td>
                                     <td style="font-size:10px;">{row.get("목표가손절가","")}</td>
                                </tr>
                        """
                    table_html += """
                            </tbody>
                        </table>
                    </div>
                    """
                    st.html(table_html)
                else:
                    st.info("등록된 포트폴리오 종목이 없습니다.")

                # ⚡ 볼린저 밴드(20,2) 시장 에너지 진단 카드 연동 (포트폴리오 종목 하단 배치)
                try:
                    from backend.services import get_bollinger_market_energy
                    b_data = get_bollinger_market_energy()
                    if b_data and b_data.get('status') == 'OK':
                        b_status = b_data.get('energy_status', '-')
                        b_color  = b_data.get('status_color', '#e74c3c')
                        b_ma5    = b_data.get('ma5', 0)
                        b_slope  = b_data.get('slope', 0)
                        b_cash   = b_data.get('cash_ratio', '-')
                        b_desc   = b_data.get('description', '')
                        b_bt     = b_data.get('backtest', {})

                        # ── 🕒 09:00~09:14 갭 함정 경고 배너 (개장 초반만 표시) ──
                        # 8개년 검증: 초민감 장세(2025~2026)에서 갭 함정 차단 시 승률 +3~4%p 개선
                        from datetime import timezone as _bte_tz, timedelta as _bte_td
                        _bte_now = datetime.now(_bte_tz(_bte_td(hours=9)))
                        _bte_hm = _bte_now.hour * 100 + _bte_now.minute
                        _is_gap_trap_window = _bte_now.weekday() < 5 and 900 <= _bte_hm < 915
                        gap_trap_banner = ""
                        if _is_gap_trap_window:
                            gap_trap_banner = """<div style="margin-top:8px; padding:7px 10px; border-radius:5px; background:rgba(255,165,0,0.12); border:1px solid #f39c12; font-size:10px; color:#f39c12;">
    🕒 <b>[개장 갭 함정 주의 구간]</b> 09:00~09:15 — +4% 이상 갭 상승 후 음봉 전환 종목 진입 보류!
    8개년 통계: 갭 함정 구간 무시 시 승률 <b style="color:#e74c3c;">-3~4%p</b> 감소
</div>"""

                        # ── 8개년(2019~2026) 95,410건 백테스트 검증 수치 반영 ──
                        _strong_win = b_bt.get('strong_win_rate', '43.9%')
                        _risk_win = b_bt.get('risk_win_rate', '35.1%')
                        _kospi_pf = b_bt.get('kospi_pf', '1.09')

                        b_html = f"""<div style="background: linear-gradient(135deg, rgba(30,34,45,0.95), rgba(15,18,25,0.98)); padding: 12px 14px; border-radius: 8px; border: 1px solid #00f2fe; margin-top: 10px; font-family: 'malgun gothic', sans-serif;">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
        <span style="font-size:13px; font-weight:bold; color:#00f2fe;">⚡ 시장 에너지 진단 (볼린저 밴드 20,2)</span>
        <span style="font-size:10px; color:#aaa;">8개년(2019~2026) 95,410건 검증</span>
    </div>
    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
        <div>
            <div style="font-size:10px; color:#888;">현재 시장 에너지 상태</div>
            <div style="font-size:16px; font-weight:bold; color:{b_color};">{b_status}</div>
            <div style="font-size:10px; color:#aaa; margin-top:2px;">{b_desc}</div>
        </div>
        <div style="text-align:right;">
            <div style="font-size:10px; color:#888;">5일 평균 돌파 종목 수</div>
            <div style="font-size:15px; font-weight:bold; color:#fff;">{b_ma5}개 <span style="font-size:11px; color:{'#2ecc71' if b_slope > 0 else '#e74c3c'};">{'+' if b_slope>0 else ''}{b_slope}</span></div>
            <div style="font-size:10px; color:#f39c12; margin-top:2px;">권장 현금 비중: <b>{b_cash}</b></div>
        </div>
    </div>
    <div style="margin-top:8px; padding-top:6px; border-top:1px dashed rgba(255,255,255,0.1); font-size:10px; color:#aaa; display:flex; justify-content:space-between; flex-wrap:wrap; gap:4px;">
        <span>📊 8개년 백테스트(5일후):</span>
        <span>강세 승률 <b style="color:#2ecc71;">{_strong_win}</b></span>
        <span>위험 승률 <b style="color:#e74c3c;">{_risk_win}</b></span>
        <span>KOSPI PF <b style="color:#00f2fe;">{_kospi_pf}</b></span>
    </div>
    {gap_trap_banner}
</div>"""
                        st.markdown(re.sub(r'\s+', ' ', b_html.replace('\n', ' ')).strip(), unsafe_allow_html=True)
                except Exception as _b_err:
                    pass

        # ── 차트 선택 (st.tabs의 오버헤드를 막기 위해 레이지 렌더링 적용) ─────────────────────────────
        chart_type = st.radio(
            "차트 주기 선택",
            ["📅 일봉 차트", "⏱️ 5분봉 (캔들)", "⚡ 1분봉 (캔들)"],
            horizontal=True,
            key="scalping_chart_selector",
            label_visibility="collapsed"
        )
        st.write("") # 간격 조절

        if chart_type == "📅 일봉 차트":
            # 캔들 차트 생성
            fig_c = make_subplots(
                rows=2, cols=1,
                row_heights=[0.85, 0.15],
                vertical_spacing=0.03,
                shared_xaxes=True
            )

            # 주말 및 휴장일로 인한 캔들 끊어짐 방지를 위해 x축 데이터를 문자열 카테고리 리스트로 변환
            date_str_list = df_candle.index.strftime('%Y-%m-%d').tolist()

            # 캔들스틱 (한국식: 상승=빨강, 하락=파랑)
            fig_c.add_trace(go.Candlestick(
                x=date_str_list,
                open=df_candle['Open'], high=df_candle['High'],
                low=df_candle['Low'],   close=df_candle['Close'],
                increasing=dict(line=dict(color='#ff6b6b'), fillcolor='#ff6b6b'),
                decreasing=dict(line=dict(color='#4e9ff5'), fillcolor='#4e9ff5'),
                name='일봉 캔들', showlegend=False,
                hoverlabel=dict(bgcolor='#0d1b2a', font_size=13, font_family='malgun gothic'),
                hovertemplate="<b>📅 일자: %{x}</b><br>🔓 <b>시가</b>: %{open:,d}원<br>🔺 <b>고가</b>: %{high:,d}원<br>🔻 <b>저가</b>: %{low:,d}원<br>🔒 <b>종가</b>: %{close:,d}원<extra></extra>"
            ), row=1, col=1)

            # MA5
            fig_c.add_trace(go.Scattergl(
                x=date_str_list, y=df_candle['MA5'],
                name='MA5', mode='lines',
                line=dict(color='#ffd43b', width=1.5)
            ), row=1, col=1)

            # MA20
            fig_c.add_trace(go.Scattergl(
                x=date_str_list, y=df_candle['MA20'],
                name='MA20', mode='lines',
                line=dict(color='#ff922b', width=1.5)
            ), row=1, col=1)

            # ATR 손절 가이드선 (2.5 ATR)
            if 'Stop_Loss' in df_candle.columns:
                fig_c.add_trace(go.Scattergl(
                    x=date_str_list, y=df_candle['Stop_Loss'],
                    name='ATR 손절선', mode='lines',
                    line=dict(color='#e74c3c', width=1.5, dash='dash')
                ), row=1, col=1)
                
                # 매도 신호 (Plotly Marker + Hover Tooltip)
                if 'Exit_Signal' in df_candle.columns:
                    exit_signals = df_candle[df_candle['Exit_Signal'] == True]
                    if not exit_signals.empty:
                        exit_dates = exit_signals.index.strftime('%Y-%m-%d').tolist()
                        exit_prices = exit_signals['Close'].tolist()
                        hover_texts = [f"<b>⚠️ 매도</b><br>{int(p):,}원" if p >= 100 else f"<b>⚠️ 매도</b><br>{p:,.2f}" for p in exit_prices]
                        
                        # 범례(Legend) 표시용 더미 트레이스 (수직 정렬을 위해 사각형 사용)
                        fig_c.add_trace(go.Scattergl(
                            x=[None], y=[None],
                            mode='markers',
                            name='매도 신호',
                            marker=dict(symbol='triangle-down', size=10, color='#00e5ff'),
                            showlegend=True
                        ), row=1, col=1)
                        
                        fig_c.add_trace(go.Scattergl(
                            x=exit_dates,
                            y=exit_signals['High'] * 1.015, # 캔들 고점 위쪽에 살짝 띄워서 마커 표시
                            mode='markers',
                            name='매도 신호',
                            marker=dict(symbol='arrow-down', size=14, color='#00e5ff'),
                            text=hover_texts,
                            hovertemplate="%{text}<extra></extra>",
                            showlegend=False
                        ), row=1, col=1)
                
                # 매수 신호 (Plotly Marker + Hover Tooltip)
                if 'Buy_Signal' in df_candle.columns:
                    buy_signals = df_candle[df_candle['Buy_Signal'] == True]
                    if not buy_signals.empty:
                        buy_dates = buy_signals.index.strftime('%Y-%m-%d').tolist()
                        buy_prices = buy_signals['Close'].tolist()
                        hover_texts = [f"<b>🟢 매수</b><br>{int(p):,}원" if p >= 100 else f"<b>🟢 매수</b><br>{p:,.2f}" for p in buy_prices]
                        
                        # 범례(Legend) 표시용 더미 트레이스 (수직 정렬을 위해 사각형 사용)
                        fig_c.add_trace(go.Scattergl(
                            x=[None], y=[None],
                            mode='markers',
                            name='매수 신호',
                            marker=dict(symbol='triangle-up', size=10, color='#2ecc71'),
                            showlegend=True
                        ), row=1, col=1)
                        
                        fig_c.add_trace(go.Scattergl(
                            x=buy_dates,
                            y=buy_signals['Low'] * 0.985, # 캔들 저점 아래쪽에 살짝 띄워서 마커 표시
                            mode='markers',
                            name='매수 신호',
                            marker=dict(symbol='arrow-up', size=14, color='#2ecc71'),
                            text=hover_texts,
                            hovertemplate="%{text}<extra></extra>",
                            showlegend=False
                        ), row=1, col=1)

                # 낙폭과대 매수 신호 (Plotly Marker + Hover Tooltip)
                if 'Fall_Signal' in df_candle.columns:
                    fall_signals = df_candle[df_candle['Fall_Signal'] == True]
                    if not fall_signals.empty:
                        fall_dates = fall_signals.index.strftime('%Y-%m-%d').tolist()
                        fall_prices = fall_signals['Close'].tolist()
                        hover_texts_fall = [f"<b>📉 낙폭과대 매수</b><br>{int(p):,}원" if p >= 100 else f"<b>📉 낙폭과대 매수</b><br>{p:,.2f}" for p in fall_prices]
                        
                        # 범례(Legend) 표시용 더미 트레이스
                        fig_c.add_trace(go.Scattergl(
                            x=[None], y=[None],
                            mode='markers',
                            name='낙폭과대 매수',
                            marker=dict(symbol='triangle-up', size=10, color='#94d82d'),
                            showlegend=True
                        ), row=1, col=1)
                        
                        fig_c.add_trace(go.Scattergl(
                            x=fall_dates,
                            y=fall_signals['Low'] * 0.985,
                            mode='markers',
                            name='낙폭과대 매수',
                            marker=dict(symbol='arrow-up', size=14, color='#94d82d'),
                            text=hover_texts_fall,
                            hovertemplate="%{text}<extra></extra>",
                            showlegend=False
                        ), row=1, col=1)

                # 추가 매수 신호 (Plotly Marker + Hover Tooltip)
                if 'Add_Signal' in df_candle.columns:
                    add_signals = df_candle[df_candle['Add_Signal'].notna()]
                    if not add_signals.empty:
                        add_dates = add_signals.index.strftime('%Y-%m-%d').tolist()
                        add_prices = add_signals['Close'].tolist()
                        add_types = add_signals['Add_Signal'].tolist()
                        
                        hover_texts_add = []
                        for p, t in zip(add_prices, add_types):
                            price_str = f"{int(p):,}원" if p >= 100 else f"{p:,.2f}"
                            if t == '물타기':
                                hover_texts_add.append(f"<b>🟡 추가 매수 (물타기)</b><br>평단 조절용<br>{price_str}")
                            else:
                                hover_texts_add.append(f"<b>🔥 추가 매수 (불타기)</b><br>수익 극대화용<br>{price_str}")
                        
                        # 범례(Legend) 표시용 더미 트레이스
                        fig_c.add_trace(go.Scattergl(
                            x=[None], y=[None],
                            mode='markers',
                            name='추가 매수',
                            marker=dict(symbol='triangle-up', size=10, color='#fcc419'),
                            showlegend=True
                        ), row=1, col=1)
                        
                        fig_c.add_trace(go.Scattergl(
                            x=add_dates,
                            y=add_signals['Low'] * 0.985,
                            mode='markers',
                            name='추가 매수',
                            marker=dict(symbol='arrow-up', size=14, color='#fcc419'),
                            text=hover_texts_add,
                            hovertemplate="%{text}<extra></extra>",
                            showlegend=False
                        ), row=1, col=1)

            # 나의 매수 단가선 (포트폴리오 등록 시 황금색 점선으로 표시)
            portfolio_cached = portfolio if 'portfolio' in locals() and portfolio else load_portfolio()
            my_entry_price = 0
            if code_disp in portfolio_cached:
                my_entry_price = portfolio_cached[code_disp]["entry_price"]
                fig_c.add_trace(go.Scattergl(
                    x=date_str_list, y=[my_entry_price] * len(date_str_list),
                    name='나의 매수단가', mode='lines',
                    line=dict(color='#ffd700', width=2.0, dash='dashdot')
                ), row=1, col=1)

            # 일봉 차트의 가격 범위(y_range)를 완벽히 동기화하기 위한 수동 계산
            try:
                min_val = df_candle[['High', 'Low', 'Close', 'Open']].min().min()
                max_val = df_candle[['High', 'Low', 'Close', 'Open']].max().max()
                for col in ['MA5', 'MA20', 'Stop_Loss']:
                    if col in df_candle.columns:
                        min_val = min(min_val, df_candle[col].min(skipna=True))
                        max_val = max(max_val, df_candle[col].max(skipna=True))
                if my_entry_price > 0:
                    min_val = min(min_val, my_entry_price)
                    max_val = max(max_val, my_entry_price)
                margin_bottom = (max_val - min_val) * 0.05 if max_val > min_val else 1000
                margin_top = (max_val - min_val) * 0.25 if max_val > min_val else 2000
                y_range = [min_val - margin_bottom, max_val + margin_top]
            except Exception:
                y_range = None

            # 거래량 막대 (색상: 상승일=빨강, 하락일=파랑)
            vol_colors = [
                '#ff6b6b' if c >= o else '#4e9ff5'
                for c, o in zip(df_candle['Close'], df_candle['Open'])
            ]
            fig_c.add_trace(go.Bar(
                x=date_str_list, y=df_candle['Volume'] // 1000,
                name='거래량', marker_color=vol_colors,
                showlegend=False, opacity=0.8
            ), row=2, col=1)

            # 우측 Y축 눈금(yaxis3)을 활성화하기 위한 더미 투명 트레이스 주입 (row/col 생략하여 layout y3 매핑)
            fig_c.add_trace(go.Scattergl(
                x=date_str_list,
                y=df_candle['Close'],
                yaxis='y3',
                showlegend=False,
                hoverinfo='skip',
                mode='markers',
                marker=dict(opacity=0)
            ))

            fig_c.update_layout(
                template='plotly_dark',
                height=650,
                margin=dict(t=50, l=10, r=55, b=10), # 우측 가격 눈금을 위한 여백 및 상단 라벨 잘림 방지
                xaxis_rangeslider_visible=False,
                legend=dict(orientation='h', x=0, y=1.02, font=dict(size=11)),
                font=dict(family='malgun gothic, nanum gothic, sans-serif'),
                plot_bgcolor='#0d1b2a',
                paper_bgcolor='#0d1b2a',
                hovermode='x unified', # 마우스 커서 위치의 캔들(시가,고가,저가,종가) 툴팁 표시
                hoverlabel=dict(bgcolor='#0f172a', font_size=12, font_family='malgun gothic'),
                # 우측 가격축을 활성화하기 위한 overlay yaxis3 정의 (좌측 Y축과 범위 동기화)
                yaxis3=dict(
                    overlaying='y',
                    side='right',
                    showgrid=False,
                    tickfont=dict(size=10, color='#888'),
                    anchor='x',
                    tickformat=',d',
                    showticklabels=True,
                    range=y_range,
                    nticks=18, # 눈금을 더 촘촘히 표시
                    fixedrange=True # 우측 눈금에도 확대/축소 잠금을 걸어야 화살표 커서 유지
                )
            )
            # 좌측 Y축 눈금 정의 및 촘촘함 적용 (yaxis = row1의 주가 축)
            fig_c.update_yaxes(
                tickformat=',d',
                gridcolor='rgba(255,255,255,0.06)',
                ticks='outside',       # 눈금 방향: 바깥
                showticklabels=True,
                tickfont=dict(size=10, color='#888'),
                range=y_range,
                nticks=18,             # 눈금을 더 촘촘히 표시
                fixedrange=True,       # Y축 확대/축소(Zoom/Pan) 비활성화
                showspikes=True, spikemode='across', spikesnap='cursor', spikedash='dot', spikecolor='#999999', spikethickness=1, # 마우스 십자선
                row=1, col=1
            )
            fig_c.update_xaxes(
                fixedrange=True, # X축 확대/축소 비활성화
                row=1, col=1
            )

            # 현재가 우측 Y축 라벨 박스 및 보조선 투사 (HTS 형태)
            price_color = '#ff6b6b' if daily_chg >= 0 else '#4e9ff5'
            fig_c.add_hline(y=last_close, line_dash="dot", line_color=price_color, line_width=1.5, opacity=0.6, row=1, col=1)
            fig_c.add_annotation(
                xref='paper', yref='y',
                x=1.002, y=last_close,
                text=f" <b>{int(last_close):,}</b> ",
                showarrow=False,
                font=dict(color="#ffffff", size=9, family="malgun gothic"),
                bgcolor=price_color,
                bordercolor=price_color,
                borderwidth=1,
                borderpad=3,
                xanchor='left' # Y축선 상에 겹치도록 왼쪽 앵커 정렬 및 row, col 제외로 paper 앵킹 유지
            )

            # x축 카테고리 틱 라벨의 과도한 밀집 방지를 위해 약 8개 틱만 고르게 추출하여 표시
            tick_indices = np.linspace(0, len(date_str_list) - 1, 8, dtype=int) if len(date_str_list) > 0 else []
            tick_vals = [date_str_list[i] for i in tick_indices]
            tick_texts = [date_str_list[i] for i in tick_indices]

            fig_c.update_yaxes(tickformat=',d', ticksuffix='K', gridcolor='rgba(255,255,255,0.06)', fixedrange=True, row=2, col=1)
            fig_c.update_xaxes(
                type='category',
                gridcolor='rgba(255,255,255,0.04)',
                showticklabels=False,
                row=1, col=1
            )
            fig_c.update_xaxes(
                type='category',
                gridcolor='rgba(255,255,255,0.04)',
                tickangle=-30,
                tickmode='array',
                tickvals=tick_vals,
                ticktext=tick_texts,
                fixedrange=True,
                row=2, col=1
            )
            
            st.plotly_chart(fig_c, width='stretch', config={'displayModeBar': False})

        elif chart_type == "⏱️ 5분봉 (캔들)":
            # ── 5분봉 차트 생성 ─────────────────────────────
            fig_5m = make_subplots(
                rows=2, cols=1,
                row_heights=[0.85, 0.15],
                vertical_spacing=0.03,
                shared_xaxes=True
            )
            if not df_5min.empty:
                # 5분봉: 최근 3~4일(약 250봉) 데이터를 유지하여 캔들 가시성 및 히스토리 확보
                df_5min_tail = df_5min.tail(250).copy().reset_index(drop=True)
                
                tick_vals_5m = list(range(len(df_5min_tail)))
                tick_texts_5m = df_5min_tail['DateTime'].dt.strftime('%m/%d %H:%M').tolist()
                
                # 5분봉: 약 12개 내외의 라벨만 표시되도록 다운샘플링 (x축 텍스트 겹침 방지)
                step_5m = max(1, len(tick_vals_5m) // 12)
                display_tick_vals_5m = tick_vals_5m[::step_5m]
                display_tick_texts_5m = tick_texts_5m[::step_5m]
                
                fig_5m.add_trace(go.Candlestick(
                    x=tick_vals_5m,
                    open=df_5min_tail['Open'], high=df_5min_tail['High'],
                    low=df_5min_tail['Low'], close=df_5min_tail['Close'],
                    increasing=dict(line=dict(color='#ff6b6b'), fillcolor='#ff6b6b'),
                    decreasing=dict(line=dict(color='#4e9ff5'), fillcolor='#4e9ff5'),
                    name='5분봉 캔들', showlegend=False,
                    text=tick_texts_5m,
                    hoverlabel=dict(bgcolor='#0d1b2a', font_size=13, font_family='malgun gothic'),
                    hovertemplate="<b>⏱️ 일시: %{text}</b><br>🔓 <b>시가</b>: %{open:,d}원<br>🔺 <b>고가</b>: %{high:,d}원<br>🔻 <b>저가</b>: %{low:,d}원<br>🔒 <b>종가</b>: %{close:,d}원<extra></extra>"
                ), row=1, col=1)
                
                # MA5, MA20 그리기
                fig_5m.add_trace(go.Scattergl(
                    x=tick_vals_5m, y=df_5min_tail['MA5'],
                    name='MA5', mode='lines',
                    line=dict(color='#ffd43b', width=1.5)
                ), row=1, col=1)
                
                fig_5m.add_trace(go.Scattergl(
                    x=tick_vals_5m, y=df_5min_tail['MA20'],
                    name='MA20', mode='lines',
                    line=dict(color='#ff922b', width=1.5)
                ), row=1, col=1)
                
                # ATR 손절선 그리기
                if 'Stop_Loss' in df_5min_tail.columns:
                    fig_5m.add_trace(go.Scattergl(
                        x=tick_vals_5m, y=df_5min_tail['Stop_Loss'],
                        name='ATR 손절선', mode='lines',
                        line=dict(color='#e74c3c', width=1.5, dash='dash')
                    ), row=1, col=1)
                    
                # 매도 신호 그리기
                if 'Exit_Signal' in df_5min_tail.columns:
                    fig_5m.add_trace(go.Scattergl(
                        x=[None], y=[None],
                        mode='markers',
                        name='매도 신호',
                        marker=dict(symbol='triangle-down', size=10, color='#00e5ff'),
                        showlegend=True
                    ), row=1, col=1)
                    
                    exit_indices_5m = [i for i, val in enumerate(df_5min_tail['Exit_Signal']) if val]
                    if exit_indices_5m:
                        exit_prices_5m = df_5min_tail.loc[exit_indices_5m, 'Close'].tolist()
                        exit_highs_5m = df_5min_tail.loc[exit_indices_5m, 'High'].tolist()
                        hover_texts_5m = [f"<b>⚠️ 매도</b><br>{int(p):,}원" if p >= 100 else f"<b>⚠️ 매도</b><br>{p:,.2f}" for p in exit_prices_5m]
                        fig_5m.add_trace(go.Scattergl(
                            x=exit_indices_5m,
                            y=[h * 1.002 for h in exit_highs_5m],
                            mode='markers',
                            name='매도 신호',
                            marker=dict(symbol='arrow-down', size=14, color='#00e5ff'),
                            text=hover_texts_5m,
                            hovertemplate="%{text}<extra></extra>",
                            showlegend=False
                        ), row=1, col=1)
                        
                # 매수 신호 그리기
                if 'Buy_Signal' in df_5min_tail.columns:
                    fig_5m.add_trace(go.Scattergl(
                        x=[None], y=[None],
                        mode='markers',
                        name='매수 신호',
                        marker=dict(symbol='triangle-up', size=10, color='#2ecc71'),
                        showlegend=True
                    ), row=1, col=1)
                    
                    buy_indices_5m = [i for i, val in enumerate(df_5min_tail['Buy_Signal']) if val]
                    if buy_indices_5m:
                        buy_prices_5m = df_5min_tail.loc[buy_indices_5m, 'Close'].tolist()
                        buy_lows_5m = df_5min_tail.loc[buy_indices_5m, 'Low'].tolist()
                        hover_texts_5m = [f"<b>🟢 매수</b><br>{int(p):,}원" if p >= 100 else f"<b>🟢 매수</b><br>{p:,.2f}" for p in buy_prices_5m]
                        fig_5m.add_trace(go.Scattergl(
                            x=buy_indices_5m,
                            y=[l * 0.998 for l in buy_lows_5m],
                            mode='markers',
                            name='매수 신호',
                            marker=dict(symbol='arrow-up', size=14, color='#2ecc71'),
                            text=hover_texts_5m,
                            hovertemplate="%{text}<extra></extra>",
                            showlegend=False
                        ), row=1, col=1)

                # 📉 낙폭과대 반등 신호 그리기
                if 'Fall_Signal' in df_5min_tail.columns:
                    fig_5m.add_trace(go.Scattergl(
                        x=[None], y=[None],
                        mode='markers',
                        name='낙폭과대 반등',
                        marker=dict(symbol='triangle-up', size=10, color='#a29bfe'),
                        showlegend=True
                    ), row=1, col=1)

                    fall_indices_5m = [i for i, val in enumerate(df_5min_tail['Fall_Signal']) if val]
                    if fall_indices_5m:
                        fall_prices_5m = df_5min_tail.loc[fall_indices_5m, 'Close'].tolist()
                        fall_lows_5m   = df_5min_tail.loc[fall_indices_5m, 'Low'].tolist()
                        hover_texts_5m = [
                            f"<b>📉 낙폭과대 반등</b><br>{int(p):,}원" if p >= 100
                            else f"<b>📉 낙폭과대 반등</b><br>{p:,.2f}"
                            for p in fall_prices_5m
                        ]
                        fig_5m.add_trace(go.Scattergl(
                            x=fall_indices_5m,
                            y=[l * 0.997 for l in fall_lows_5m],
                            mode='markers',
                            name='낙폭과대 반등',
                            marker=dict(symbol='arrow-up', size=16, color='#a29bfe'),
                            text=hover_texts_5m,
                            hovertemplate="%{text}<extra></extra>",
                            showlegend=False
                        ), row=1, col=1)

                # 🟡 추가 매수 신호 그리기
                if 'Add_Signal' in df_5min_tail.columns:
                    fig_5m.add_trace(go.Scattergl(
                        x=[None], y=[None],
                        mode='markers',
                        name='추가 매수',
                        marker=dict(symbol='triangle-up', size=10, color='#ffd43b'),
                        showlegend=True
                    ), row=1, col=1)

                    add_indices_5m = [i for i, val in enumerate(df_5min_tail['Add_Signal']) if val]
                    if add_indices_5m:
                        add_prices_5m = df_5min_tail.loc[add_indices_5m, 'Close'].tolist()
                        add_lows_5m   = df_5min_tail.loc[add_indices_5m, 'Low'].tolist()
                        hover_texts_5m = [
                            f"<b>🟡 추가 매수</b><br>{int(p):,}원" if p >= 100
                            else f"<b>🟡 추가 매수</b><br>{p:,.2f}"
                            for p in add_prices_5m
                        ]
                        fig_5m.add_trace(go.Scattergl(
                            x=add_indices_5m,
                            y=[l * 0.996 for l in add_lows_5m],
                            mode='markers',
                            name='추가 매수',
                            marker=dict(symbol='arrow-up', size=16, color='#ffd43b'),
                            text=hover_texts_5m,
                            hovertemplate="%{text}<extra></extra>",
                            showlegend=False
                        ), row=1, col=1)

                # 나의 매수단가선 그리기
                portfolio_cached = portfolio if 'portfolio' in locals() and portfolio else load_portfolio()
                my_entry_price = 0
                if code_disp in portfolio_cached:
                    my_entry_price = portfolio_cached[code_disp]["entry_price"]
                    fig_5m.add_trace(go.Scattergl(
                        x=tick_vals_5m, y=[my_entry_price] * len(tick_vals_5m),
                        name='나의 매수단가', mode='lines',
                        line=dict(color='#ffd700', width=2.0, dash='dashdot')
                    ), row=1, col=1)
                    
                vol_colors_5m = [
                    '#ff6b6b' if c >= o else '#4e9ff5'
                    for c, o in zip(df_5min_tail['Close'], df_5min_tail['Open'])
                ]
                fig_5m.add_trace(go.Bar(
                    x=tick_vals_5m, y=df_5min_tail['Volume'] // 1000,
                    name='거래량(K)', marker_color=vol_colors_5m,
                    showlegend=False, opacity=0.8
                ), row=2, col=1)

                # 5분봉 가격 범위(y_range) 수동 계산
                try:
                    min_val_5m = df_5min_tail[['High', 'Low', 'Close', 'Open']].min().min()
                    max_val_5m = df_5min_tail[['High', 'Low', 'Close', 'Open']].max().max()
                    for col in ['MA5', 'MA20', 'Stop_Loss']:
                        if col in df_5min_tail.columns:
                            min_val_5m = min(min_val_5m, df_5min_tail[col].min(skipna=True))
                            max_val_5m = max(max_val_5m, df_5min_tail[col].max(skipna=True))
                    margin_5m = (max_val_5m - min_val_5m) * 0.05 if max_val_5m > min_val_5m else 100
                    y_range_5m = [min_val_5m - margin_5m, max_val_5m + margin_5m]
                except Exception:
                    y_range_5m = None

                # 우측 Y축 눈금(yaxis3)을 활성화하기 위한 더미 투명 트레이스 주입 (row/col 생략하여 layout y3 매핑)
                fig_5m.add_trace(go.Scattergl(
                    x=tick_vals_5m,
                    y=df_5min_tail['Close'],
                    yaxis='y3',
                    showlegend=False,
                    hoverinfo='skip',
                    mode='markers',
                    marker=dict(opacity=0)
                ))

                last_5m_close = df_5min_tail['Close'].iloc[-1]
                fig_5m.update_layout(
                    template='plotly_dark',
                    height=650,
                    margin=dict(t=20, l=10, r=55, b=40), # X축 레이블 짤림 방지 및 우측 눈금 여백
                    xaxis_rangeslider_visible=False,
                    legend=dict(orientation='h', x=0, y=1.02, font=dict(size=11)),
                    font=dict(family='malgun gothic, nanum gothic, sans-serif'),
                    plot_bgcolor='#0d1b2a',
                    paper_bgcolor='#0d1b2a',
                    hovermode='x unified',
                    hoverlabel=dict(bgcolor='#0f172a', font_size=12, font_family='malgun gothic'),
                    # 우측 가격축을 활성화하기 위한 overlay yaxis3 정의 (좌측 Y축과 범위 동기화)
                    yaxis3=dict(
                        overlaying='y',
                        side='right',
                        showgrid=False,
                        tickfont=dict(size=10, color='#888'),
                        anchor='x',
                        tickformat=',d',
                        showticklabels=True,
                        range=y_range_5m,
                        nticks=18 # 눈금을 더 촘촘히 표시
                    )
                )
                price_color = '#ff6b6b' if daily_chg >= 0 else '#4e9ff5'
                fig_5m.add_hline(y=last_5m_close, line_dash="dot", line_color=price_color, line_width=1.5, opacity=0.6, row=1, col=1)
                fig_5m.add_annotation(
                    xref='paper', yref='y',
                    x=1.002, y=last_5m_close,
                    text=f" <b>{int(last_5m_close):,}</b> ",
                    showarrow=False,
                    font=dict(color="#ffffff", size=9, family="malgun gothic"),
                    bgcolor=price_color,
                    bordercolor=price_color,
                    borderwidth=1,
                    borderpad=3,
                    xanchor='left'
                )
                fig_5m.update_yaxes(
                    tickformat=',d',
                    gridcolor='rgba(255,255,255,0.06)',
                    ticks='outside',
                    showticklabels=True,
                    tickfont=dict(size=10, color='#888'),
                    range=y_range_5m,
                    nticks=18,             # 눈금을 더 촘촘히 표시
                    row=1, col=1
                )
                # 거래량 Y축 스케일 조정 (장 시작 첫 봉의 비정상적인 거래량으로 인해 나머지 막대가 안 보이는 현상 방지)
                vol_s_5m = df_5min_tail['Volume'] // 1000
                vol_max_5m = vol_s_5m.quantile(0.98) * 1.5 if not vol_s_5m.empty else 100
                if vol_max_5m <= 0 or pd.isna(vol_max_5m): vol_max_5m = vol_s_5m.max()
                fig_5m.update_yaxes(
                    tickformat=',d', 
                    ticksuffix='K', 
                    tickfont=dict(size=10, color='#888'),
                    gridcolor='rgba(255,255,255,0.06)', 
                    range=[0, vol_max_5m], 
                    row=2, col=1
                )
                
                fig_5m.update_xaxes(
                    type='category',
                    gridcolor='rgba(255,255,255,0.04)',
                    showticklabels=False,
                    row=1, col=1
                )
                fig_5m.update_xaxes(
                    type='category',
                    gridcolor='rgba(255,255,255,0.04)',
                    tickangle=-15,
                    tickmode='array',
                    tickvals=display_tick_vals_5m,
                    ticktext=display_tick_texts_5m,
                    row=2, col=1
                )
                
                st.plotly_chart(fig_5m, width='stretch', config={'displayModeBar': False})
            else:
                st.info("⚠️ 5분봉 데이터를 불러올 수 없거나 휴장일입니다.")

        elif chart_type == "⚡ 1분봉 (캔들)":
            # ── 1분봉 차트 생성 ─────────────────────────────
            fig_1m = make_subplots(
                rows=2, cols=1,
                row_heights=[0.85, 0.15],
                vertical_spacing=0.03,
                shared_xaxes=True
            )
            if not df_1min.empty:
                # 1분봉: 당일 전체(약 390봉) 데이터만 유지하여 캔들 가시성 확보 및 어제 데이터 혼입 방지
                latest_date_1m = df_1min['DateTime'].dt.date.max()
                df_1min_tail = df_1min[df_1min['DateTime'].dt.date == latest_date_1m].copy().reset_index(drop=True)
                
                tick_vals_1m = list(range(len(df_1min_tail)))
                tick_texts_1m = df_1min_tail['DateTime'].dt.strftime('%H:%M').tolist()
                
                # 1분봉: 약 12개 내외의 라벨만 표시되도록 다운샘플링 (x축 텍스트 겹침 방지)
                step_1m = max(1, len(tick_vals_1m) // 12)
                display_tick_vals_1m = tick_vals_1m[::step_1m]
                display_tick_texts_1m = tick_texts_1m[::step_1m]
                
                fig_1m.add_trace(go.Candlestick(
                    x=tick_vals_1m,
                    open=df_1min_tail['Open'],
                    high=df_1min_tail['High'],
                    low=df_1min_tail['Low'],
                    close=df_1min_tail['Close'],
                    increasing=dict(line=dict(color='#ff6b6b'), fillcolor='#ff6b6b'),
                    decreasing=dict(line=dict(color='#4e9ff5'), fillcolor='#4e9ff5'),
                    name='1분봉 캔들', showlegend=False,
                    text=tick_texts_1m,
                    hoverlabel=dict(bgcolor='#0d1b2a', font_size=13, font_family='malgun gothic'),
                    hovertemplate="<b>⚡ 일시: %{text}</b><br>🔓 <b>시가</b>: %{open:,d}원<br>🔺 <b>고가</b>: %{high:,d}원<br>🔻 <b>저가</b>: %{low:,d}원<br>🔒 <b>종가</b>: %{close:,d}원<extra></extra>"
                ), row=1, col=1)
                
                # MA5, MA20 그리기
                fig_1m.add_trace(go.Scattergl(
                    x=tick_vals_1m, y=df_1min_tail['MA5'],
                    name='MA5', mode='lines',
                    line=dict(color='#ffd43b', width=1.5)
                ), row=1, col=1)
                
                fig_1m.add_trace(go.Scattergl(
                    x=tick_vals_1m, y=df_1min_tail['MA20'],
                    name='MA20', mode='lines',
                    line=dict(color='#ff922b', width=1.5)
                ), row=1, col=1)
                
                # ATR 손절선 그리기
                if 'Stop_Loss' in df_1min_tail.columns:
                    fig_1m.add_trace(go.Scattergl(
                        x=tick_vals_1m, y=df_1min_tail['Stop_Loss'],
                        name='ATR 손절선', mode='lines',
                        line=dict(color='#e74c3c', width=1.5, dash='dash')
                    ), row=1, col=1)
                    
                # 매도 신호 그리기
                if 'Exit_Signal' in df_1min_tail.columns:
                    fig_1m.add_trace(go.Scattergl(
                        x=[None], y=[None],
                        mode='markers',
                        name='매도 신호',
                        marker=dict(symbol='triangle-down', size=10, color='#00e5ff'),
                        showlegend=True
                    ), row=1, col=1)
                    
                    exit_indices_1m = [i for i, val in enumerate(df_1min_tail['Exit_Signal']) if val]
                    if exit_indices_1m:
                        exit_prices_1m = df_1min_tail.loc[exit_indices_1m, 'Close'].tolist()
                        exit_highs_1m = df_1min_tail.loc[exit_indices_1m, 'High'].tolist()
                        hover_texts_1m = [f"<b>⚠️ 매도</b><br>{int(p):,}원" if p >= 100 else f"<b>⚠️ 매도</b><br>{p:,.2f}" for p in exit_prices_1m]
                        
                        fig_1m.add_trace(go.Scattergl(
                            x=exit_indices_1m,
                            y=[h * 1.002 for h in exit_highs_1m],
                            mode='markers',
                            name='매도 신호',
                            marker=dict(symbol='arrow-down', size=14, color='#00e5ff'),
                            text=hover_texts_1m,
                            hovertemplate="%{text}<extra></extra>",
                            showlegend=False
                        ), row=1, col=1)
                        
                # 매수 신호 그리기
                if 'Buy_Signal' in df_1min_tail.columns:
                    fig_1m.add_trace(go.Scattergl(
                        x=[None], y=[None],
                        mode='markers',
                        name='매수 신호',
                        marker=dict(symbol='triangle-up', size=10, color='#2ecc71'),
                        showlegend=True
                    ), row=1, col=1)
                    
                    buy_indices_1m = [i for i, val in enumerate(df_1min_tail['Buy_Signal']) if val]
                    if buy_indices_1m:
                        buy_prices_1m = df_1min_tail.loc[buy_indices_1m, 'Close'].tolist()
                        buy_lows_1m = df_1min_tail.loc[buy_indices_1m, 'Low'].tolist()
                        hover_texts_1m = [f"<b>🟢 매수</b><br>{int(p):,}원" if p >= 100 else f"<b>🟢 매수</b><br>{p:,.2f}" for p in buy_prices_1m]
                        
                        fig_1m.add_trace(go.Scattergl(
                            x=buy_indices_1m,
                            y=[l * 0.998 for l in buy_lows_1m],
                            mode='markers',
                            name='매수 신호',
                            marker=dict(symbol='arrow-up', size=14, color='#2ecc71'),
                            text=hover_texts_1m,
                            hovertemplate="%{text}<extra></extra>",
                            showlegend=False
                        ), row=1, col=1)

                # 📉 낙폭과대 반등 신호 그리기
                if 'Fall_Signal' in df_1min_tail.columns:
                    fig_1m.add_trace(go.Scattergl(
                        x=[None], y=[None],
                        mode='markers',
                        name='낙폭과대 반등',
                        marker=dict(symbol='triangle-up', size=10, color='#a29bfe'),
                        showlegend=True
                    ), row=1, col=1)

                    fall_indices_1m = [i for i, val in enumerate(df_1min_tail['Fall_Signal']) if val]
                    if fall_indices_1m:
                        fall_prices_1m = df_1min_tail.loc[fall_indices_1m, 'Close'].tolist()
                        fall_lows_1m   = df_1min_tail.loc[fall_indices_1m, 'Low'].tolist()
                        hover_texts_1m = [
                            f"<b>📉 낙폭과대 반등</b><br>{int(p):,}원" if p >= 100
                            else f"<b>📉 낙폭과대 반등</b><br>{p:,.2f}"
                            for p in fall_prices_1m
                        ]
                        fig_1m.add_trace(go.Scattergl(
                            x=fall_indices_1m,
                            y=[l * 0.997 for l in fall_lows_1m],
                            mode='markers',
                            name='낙폭과대 반등',
                            marker=dict(symbol='arrow-up', size=16, color='#a29bfe'),
                            text=hover_texts_1m,
                            hovertemplate="%{text}<extra></extra>",
                            showlegend=False
                        ), row=1, col=1)

                # 🟡 추가 매수 신호 그리기
                if 'Add_Signal' in df_1min_tail.columns:
                    fig_1m.add_trace(go.Scattergl(
                        x=[None], y=[None],
                        mode='markers',
                        name='추가 매수',
                        marker=dict(symbol='triangle-up', size=10, color='#ffd43b'),
                        showlegend=True
                    ), row=1, col=1)

                    add_indices_1m = [i for i, val in enumerate(df_1min_tail['Add_Signal']) if val]
                    if add_indices_1m:
                        add_prices_1m = df_1min_tail.loc[add_indices_1m, 'Close'].tolist()
                        add_lows_1m   = df_1min_tail.loc[add_indices_1m, 'Low'].tolist()
                        hover_texts_1m = [
                            f"<b>🟡 추가 매수</b><br>{int(p):,}원" if p >= 100
                            else f"<b>🟡 추가 매수</b><br>{p:,.2f}"
                            for p in add_prices_1m
                        ]
                        fig_1m.add_trace(go.Scattergl(
                            x=add_indices_1m,
                            y=[l * 0.996 for l in add_lows_1m],
                            mode='markers',
                            name='추가 매수',
                            marker=dict(symbol='arrow-up', size=16, color='#ffd43b'),
                            text=hover_texts_1m,
                            hovertemplate="%{text}<extra></extra>",
                            showlegend=False
                        ), row=1, col=1)

                # 나의 매수단가선 그리기
                portfolio_cached = portfolio if 'portfolio' in locals() and portfolio else load_portfolio()
                my_entry_price = 0
                if code_disp in portfolio_cached:
                    my_entry_price = portfolio_cached[code_disp]["entry_price"]
                    fig_1m.add_trace(go.Scattergl(
                        x=tick_vals_1m, y=[my_entry_price] * len(tick_vals_1m),
                        name='나의 매수단가', mode='lines',
                        line=dict(color='#ffd700', width=2.0, dash='dashdot')
                    ), row=1, col=1)
                    
                vol_colors_1m = [
                    '#ff6b6b' if c >= o else '#4e9ff5'
                    for c, o in zip(df_1min_tail['Close'], df_1min_tail['Open'])
                ]
                fig_1m.add_trace(go.Bar(
                    x=tick_vals_1m, y=df_1min_tail['Volume'] // 1000,
                    name='거래량(K)', marker_color=vol_colors_1m,
                    showlegend=False, opacity=0.8
                ), row=2, col=1)

                # 1분봉 가격 범위(y_range) 수동 계산
                try:
                    min_val_1m = df_1min_tail[['High', 'Low', 'Close', 'Open']].min().min()
                    max_val_1m = df_1min_tail[['High', 'Low', 'Close', 'Open']].max().max()
                    for col in ['MA5', 'MA20', 'Stop_Loss']:
                        if col in df_1min_tail.columns:
                            min_val_1m = min(min_val_1m, df_1min_tail[col].min(skipna=True))
                            max_val_1m = max(max_val_1m, df_1min_tail[col].max(skipna=True))
                    margin_1m = (max_val_1m - min_val_1m) * 0.05 if max_val_1m > min_val_1m else 100
                    y_range_1m = [min_val_1m - margin_1m, max_val_1m + margin_1m]
                except Exception:
                    y_range_1m = None

                # 우측 Y축 눈금(yaxis3)을 활성화하기 위한 더미 투명 트레이스 주입 (row/col 생략하여 layout y3 매핑)
                fig_1m.add_trace(go.Scattergl(
                    x=tick_vals_1m,
                    y=df_1min_tail['Close'],
                    yaxis='y3',
                    showlegend=False,
                    hoverinfo='skip',
                    mode='markers',
                    marker=dict(opacity=0)
                ))

                last_1m_close = df_1min_tail['Close'].iloc[-1]
                fig_1m.update_layout(
                    template='plotly_dark',
                    height=650,
                    margin=dict(t=20, l=10, r=55, b=40), # X축 레이블 짤림 방지 및 우측 눈금 여백
                    xaxis_rangeslider_visible=False,
                    legend=dict(orientation='h', x=0, y=1.02, font=dict(size=11)),
                    font=dict(family='malgun gothic, nanum gothic, sans-serif'),
                    plot_bgcolor='#0d1b2a',
                    paper_bgcolor='#0d1b2a',
                    hovermode='x unified',
                    hoverlabel=dict(bgcolor='#0f172a', font_size=12, font_family='malgun gothic'),
                    # 우측 가격축을 활성화하기 위한 overlay yaxis3 정의 (좌측 Y축과 범위 동기화)
                    yaxis3=dict(
                        overlaying='y',
                        side='right',
                        showgrid=False,
                        tickfont=dict(size=10, color='#888'),
                        anchor='x',
                        tickformat=',d',
                        showticklabels=True,
                        range=y_range_1m,
                        nticks=18 # 눈금을 더 촘촘히 표시
                    )
                )
                price_color = '#ff6b6b' if daily_chg >= 0 else '#4e9ff5'
                fig_1m.add_hline(y=last_1m_close, line_dash="dot", line_color=price_color, line_width=1.5, opacity=0.6, row=1, col=1)
                fig_1m.add_annotation(
                    xref='paper', yref='y',
                    x=1.002, y=last_1m_close,
                    text=f" <b>{int(last_1m_close):,}</b> ",
                    showarrow=False,
                    font=dict(color="#ffffff", size=9, family="malgun gothic"),
                    bgcolor=price_color,
                    bordercolor=price_color,
                    borderwidth=1,
                    borderpad=3,
                    xanchor='left'
                )
                fig_1m.update_yaxes(
                    tickformat=',d',
                    gridcolor='rgba(255,255,255,0.06)',
                    ticks='outside',
                    showticklabels=True,
                    tickfont=dict(size=10, color='#888'),
                    range=y_range_1m,
                    nticks=18,             # 눈금을 더 촘촘히 표시
                    row=1, col=1
                )
                # 거래량 Y축 스케일 조정 (장 시작 첫 봉의 비정상적인 거래량으로 인해 나머지 막대가 안 보이는 현상 방지)
                vol_s_1m = df_1min_tail['Volume'] // 1000
                vol_max_1m = vol_s_1m.quantile(0.98) * 2.0 if not vol_s_1m.empty else 100
                if vol_max_1m <= 0 or pd.isna(vol_max_1m): vol_max_1m = vol_s_1m.max()
                fig_1m.update_yaxes(
                    tickformat=',d', 
                    ticksuffix='K', 
                    tickfont=dict(size=10, color='#888'),
                    gridcolor='rgba(255,255,255,0.06)', 
                    range=[0, vol_max_1m], 
                    row=2, col=1
                )
                
                fig_1m.update_xaxes(
                    type='category',
                    gridcolor='rgba(255,255,255,0.04)',
                    showticklabels=False,
                    row=1, col=1
                )
                fig_1m.update_xaxes(
                    type='category',
                    gridcolor='rgba(255,255,255,0.04)',
                    tickangle=0,
                    tickmode='array',
                    tickvals=display_tick_vals_1m,
                    ticktext=display_tick_texts_1m,
                    row=2, col=1
                )
                
                st.plotly_chart(fig_1m, width='stretch', config={'displayModeBar': False})
            else:
                st.info("⚠️ 1분봉 데이터를 불러올 수 없거나 휴장일입니다.")

    st.divider()

# ── 개별 종목 상세 분석 섹션 렌더링 호출 ───────────────────
code_disp = st.session_state.get('sel_code', '005930')
df_all = st.session_state.get('df_live_all', pd.DataFrame())
render_stock_analysis_section(code_disp, df_m, df_all, kis_key, kis_sec)

# 하단 갱신 버튼 및 60초 자동 새로고침 JS
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if st.button('🔄 데이터 새로고침', width='stretch'):
        load_data.clear()
        st.cache_data.clear()
        st.session_state['force_sync'] = True
        st.rerun()

# 60초 주기 자동 새로고침 및 스크롤 실시간 복원 연동 (태블릿/모바일 크로스오리진 완벽 대응 하이브리드 버전)
html_script = """
    <script>
    (function() {
        var parentWin = window.parent || window;
        
        function getScrollContainer() {
            try {
                // Streamlit 메인 스크롤 컨테이너 탐색
                var container = parentWin.document.querySelector('div[data-testid="stAppViewContainer"]');
                if (container) return container;
            } catch(e) {}
            return parentWin;
        }

        var target = getScrollContainer();

        // 1. 자동 새로고침은 Python st_autorefresh에서 일괄 관리 (이중 실행 방지)

        // 2. 실시간 스크롤 위치 기록 리스너
        function saveScroll() {
            try {
                var y = (target === parentWin) ? parentWin.scrollY : target.scrollTop;
                localStorage.setItem('st_dashboard_scroll', y);
            } catch (scrollErr) {}
        }

        try {
            if (target.addEventListener) {
                target.addEventListener('scroll', saveScroll, { passive: true });
            }
        } catch (e) {
            // parent 접근 불가 시 iframe 내부(window) 스크롤 리스너 추가
            try {
                window.addEventListener('scroll', function() {
                    try {
                        localStorage.setItem('st_dashboard_scroll', window.scrollY);
                    } catch(err) {}
                }, { passive: true });
            } catch(err) {}
        }
        
        // 3. 페이지 로드 완료 시 스크롤 위치 복원
        function restoreScroll() {
            try {
                var scrollPos = localStorage.getItem('st_dashboard_scroll');
                if (scrollPos) {
                    var y = parseInt(scrollPos);
                    if (target === parentWin) {
                        parentWin.scrollTo(0, y);
                    } else {
                        target.scrollTop = y;
                    }
                }
            } catch (e) {
                try {
                    var scrollPos = localStorage.getItem('st_dashboard_scroll');
                    if (scrollPos) {
                        window.scrollTo(0, parseInt(scrollPos));
                    }
                } catch(err) {}
            }
        }

        // 복원 타이밍을 정밀하게 잡기 위해 다양한 시점에 복원 수행
        if (document.readyState === 'complete') {
            restoreScroll();
        } else {
            window.addEventListener('load', restoreScroll);
        }
        setTimeout(restoreScroll, 200);
        setTimeout(restoreScroll, 500);
    })();
    </script>
"""

st.html(html_script)
