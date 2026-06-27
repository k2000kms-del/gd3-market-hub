# -*- coding: utf-8 -*-
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import FinanceDataReader as fdr
import requests
import time
import os
from datetime import datetime

# ── Supabase 클라이언트 초기화 ────────────────────────────────
supabase = None
if "SUPABASE_URL" in st.secrets and "SUPABASE_ANON_KEY" in st.secrets:
    try:
        from supabase import create_client
        supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])
    except Exception as e:
        print(f"DEBUG: Supabase initialization failed: {e}")

from datetime import timedelta

@st.cache_data(ttl=1200) # 20분 캐시로 API 비용 및 지연 최소화
def get_kospi_ma20():
    """실시간 KOSPI 지수와 20일 이동평균선(MA20) 계산"""
    try:
        # 최근 60일 코스피 지수 데이터 수집
        df_ks = fdr.DataReader('KS11', (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d'))
        if not df_ks.empty:
            df_ks['MA20'] = df_ks['Close'].rolling(20).mean()
            current_close = float(df_ks['Close'].iloc[-1])
            ma20 = float(df_ks['MA20'].iloc[-1])
            return current_close, ma20, True
    except Exception as e:
        print(f"DEBUG: Failed to get KOSPI MA20: {e}")
    return 0.0, 0.0, False

def draw_quant_radar_chart(q_row):
    """퀀트 5대 지표 점수 레이더 차트 생성"""
    if q_row.empty:
        return None
    
    categories = ['모멘텀', '수급', '거래량', '이평선', '캔들패턴']
    values = [
        float(q_row.iloc[0].get('Score_Momentum', 0)),
        float(q_row.iloc[0].get('Score_Supply', 0)),
        float(q_row.iloc[0].get('Score_Volume', 0)),
        float(q_row.iloc[0].get('Score_MA', 0)),
        float(q_row.iloc[0].get('Score_Candle', 0))
    ]
    
    # 폐곡선을 만들기 위해 첫 번째 지표 값을 끝에 추가
    categories_closed = categories + [categories[0]]
    values_closed = values + [values[0]]
    
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values_closed,
        theta=categories_closed,
        fill='toself',
        fillcolor='rgba(0, 229, 255, 0.15)',
        line=dict(color='#00e5ff', width=2),
        marker=dict(color='#00e5ff', size=6),
        hoverinfo='theta+r'
    ))
    
    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, 100],
                tickfont=dict(size=9, color="#888888"),
                gridcolor="rgba(255, 255, 255, 0.08)",
                linecolor="rgba(255, 255, 255, 0.1)"
            ),
            angularaxis=dict(
                tickfont=dict(size=11, color="#ffffff"),
                gridcolor="rgba(255, 255, 255, 0.08)"
            ),
            bgcolor='rgba(0,0,0,0)'
        ),
        showlegend=False,
        height=280,
        margin=dict(t=30, b=20, l=40, r=40),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)'
    )
    return fig


@st.cache_data(ttl=1200)
def get_gemini_commentary(code, name, t_score, t_score_adj, s_score, change, market_cond, cash_ratio, stock_ratio, api_key):
    """종목의 퀀트 지표 및 자산배분 비중을 기반으로 Gemini AI 주식 리서치 코멘터리 생성 (다중 모델 자동 폴백 지원)"""
    if not api_key:
        raise RuntimeWarning("🔑 Gemini API Key가 설정되지 않아 AI 코멘터리를 출력할 수 없습니다. 좌측 사이드바에 키를 등록해 주세요.")
    
    headers = {"Content-Type": "application/json"}
    
    system_instruction = (
        "너는 주식 분석 대시보드의 전문 퀀트 애널리스트야. "
        "주어진 종목의 퀀트 매수 점수, 매도 점수, 그리고 현재 시장 판단 국면(매크로 환경)을 종합적으로 분석하여, "
        "해당 종목에 대한 투자 리스크 및 매매 방향성을 팩트 위주로 조언해줘. "
        "자산배분 비중 수치를 불필요하게 앵무새처럼 나열하지 말고, 매수/매도 강도와 시장 상황이 종목에 미치는 핵심적인 영향에 집중해. "
        "출력은 2~3문장 이내의 짧고 굵은 존댓말(해요체)로 제한하고, 지나치게 장황한 수식어는 배제해."
    )
    
    prompt = (
        f"종목명: {name} ({code})\n"
        f"당일 등락률: {change:+.2f}%\n"
        f"매수 퀀트 점수: {t_score_adj}점 (원점수: {t_score}점)\n"
        f"매도 퀀트 점수: {s_score}점\n"
        f"현재 시장 판단 국면: {market_cond}\n"
        "상기 데이터를 바탕으로 매수/매도 퀀트 점수와 매크로 시장 환경을 중점적으로 고려하여 2문장 내외의 요약 코멘터리를 작성해줘."
    )
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": system_instruction}]}
    }
    
    # 2026-06 공식 문서(ai.google.dev/gemini-api/docs/models) 기준 검증된 모델 목록
    # gemini-3.5-flash = gemini-flash-latest 의 실체 (Stable GA)
    models_to_try = [
        "gemini-3.5-flash",           # ★ Stable GA — 최우선 (최신 안정 모델)
        "gemini-2.5-flash",           # Stable — 이전 세대 가성비 폴백
        "gemini-2.5-pro",             # Stable — 복잡 추론 고성능 폴백
        "gemini-2.5-flash-lite",      # Stable — 초경량 고속 폴백
        "gemini-flash-latest",        # latest alias — 최후 안전망
    ]
    
    last_err = None
    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        for attempt in range(2):
            try:
                r = requests.post(url, json=payload, headers=headers, timeout=15)
                if r.status_code == 200:
                    res_json = r.json()
                    candidates = res_json.get('candidates', [])
                    if candidates:
                        content = candidates[0].get('content', {})
                        parts = content.get('parts', [])
                        if parts:
                            return parts[0].get('text', '').strip()
                    last_err = "API 응답 본문에 텍스트 데이터가 누락되었습니다."
                else:
                    last_err = f"API 응답 코드: {r.status_code} ({r.text[:100]})"
                    # 할당량 초과(429), 서버 정체(503), 모델 없음(404) 시 신속한 전환을 위해 즉시 다음 모델로 폴백
                    if r.status_code in [404, 429, 503]:
                        break
            except Exception as e:
                last_err = str(e)
            time.sleep(0.5)
            
    # 에러 메시지 한글 정제
    friendly_err = "현재 API 서버와의 통신이 일시적으로 지연되고 있습니다. 잠시 후 다시 시도해 주세요."
    if last_err:
        if "503" in last_err or "high demand" in last_err:
            friendly_err = "Gemini API 서버에 일시적으로 접속자가 몰려 응답이 지연되고 있습니다. 잠시 후 새로고침해 주세요."
        elif "429" in last_err or "Quota" in last_err:
            friendly_err = "Gemini API 호출 속도 제한을 초과했습니다. 잠시 후 다시 시도해 주세요."
        elif "400" in last_err or "API key" in last_err:
            friendly_err = "입력하신 Gemini API Key가 올바르지 않습니다. 사이드바 설정을 다시 확인해 주세요."
            
    raise RuntimeWarning(f"⚠️ {friendly_err}")
            

def clean_market_condition_korean(market_cond_str):
    """'하락위기 (1d:-9.0% 3d:-10.2% 5d:-9.2%) | ⚡ 극단변동성(σ=4.1%) | 장중충격(범위 10.7%)'와 같이 
    복잡하고 난해한 퀀트 수치 데이터를 자연스럽고 직관적인 한국어 해설 문장으로 정제합니다.
    """
    import re
    if not market_cond_str or market_cond_str == 'N/A' or market_cond_str == 'None':
        return "시장 지표 데이터가 누락된 일반"
        
    # 특수 수치 패턴(1d, σ, 범위)이 전혀 존재하지 않는 일반적인 국면 텍스트인 경우 그대로 반환
    if "1d" not in market_cond_str and "σ" not in market_cond_str and "범위" not in market_cond_str:
        return market_cond_str.strip()
        
    descriptions = []
    
    # 1. 하락위기 파싱
    down_match = re.search(r"하락위기\s*\((.*?)\)", market_cond_str)
    if down_match:
        items = down_match.group(1).split()
        rates = {}
        for item in items:
            parts = item.split(':')
            if len(parts) == 2:
                val_str = re.sub(r"[^\d.-]", "", parts[1])
                try:
                    rates[parts[0]] = abs(float(val_str))
                except ValueError:
                    pass
        if rates:
            max_period = max(rates, key=rates.get)
            max_val = rates[max_period]
            period_num = re.sub(r"[^\d]", "", max_period)
            if max_val >= 3.0:
                descriptions.append(f"최근 {period_num}일간 최대 {max_val:.1f}% 수준의 단기 급락이 누적되고")
            else:
                descriptions.append(f"최근 {period_num}일간 약 {max_val:.1f}% 수준의 완만한 단기 조정이 진행되고")
        else:
            descriptions.append("단기 가격 조정 압력이 관찰되고")
    else:
        if "하락위기" in market_cond_str:
            descriptions.append("단기 하락 리스크가 다소 잔존하고")

    # 2. 극단변동성 파싱
    vol_match = re.search(r"극단변동성\s*\(σ\s*=\s*([\d.]+)%\)", market_cond_str)
    if vol_match:
        sig_val = float(vol_match.group(1))
        if sig_val >= 3.0:
            descriptions.append(f"일간 표준편차가 {sig_val:.1f}%로 치솟아 극단적인 변동성이 나타나며")
        else:
            descriptions.append(f"일간 변동성(표준편차 {sig_val:.1f}%)이 비교적 차분하게 관리되며")
    elif "극단변동성" in market_cond_str:
        descriptions.append("일시적인 가격 변동성이 감지되며")

    # 3. 장중충격 파싱
    shock_match = re.search(r"장중충격\s*\(범위\s*([\d.]+)%\)", market_cond_str)
    if shock_match:
        range_val = float(shock_match.group(1))
        if range_val >= 8.0:
            descriptions.append(f"장중 가격 등락 범위가 {range_val:.1f}%에 달해 심한 요동을 치는")
        else:
            descriptions.append(f"장중 등락 범위가 {range_val:.1f}% 수준으로 제한적인 주가 흔들림을 보이는")
    elif "장중충격" in market_cond_str:
        descriptions.append("일부 장중 충격 압력이 남아있는")
        
    if not descriptions:
        return market_cond_str.replace(" | ", ", ").strip()
        
    return ", ".join(descriptions)


def get_local_fallback_commentary(name, t_score_adj, s_score, market_cond):
    """Gemini API 호출 제한 시 동작하는 퀀트 룰 기반 로컬 대체 리서치 조언"""
    if t_score_adj >= 85.0:
        buy_signal = "매수 보정 점수가 최상위권으로 단기 기술적 상승 추세가 강력하게 지지되고 있습니다."
    elif t_score_adj >= 65.0:
        buy_signal = "매수세가 하방 경직성을 확보하며 점진적으로 유입되는 긍정적 국면입니다."
    elif t_score_adj >= 45.0:
        buy_signal = "매수 강도가 평이한 수준이며, 추가 거래량 실린 돌파 흐름을 확인해야 합니다."
    else:
        buy_signal = "매수 모멘텀이 상대적으로 정체되어 있어 공격적인 진입보다는 관망이 유리합니다."

    if s_score >= 70.0:
        sell_signal = "다만 매도 리스크가 매우 높아 비중 조절 및 분할 차익실현 등의 리스크 관리가 긴요합니다."
    elif s_score >= 50.0:
        sell_signal = "매도 리스크가 다소 상존하고 있으므로 직전 지지선의 이탈 여부를 주의 깊게 관찰해야 합니다."
    else:
        sell_signal = "매도 압력이 현저히 낮아 현재의 견조한 추세를 안정적으로 지속할 가능성이 큽니다."

    return f"{name}은(는) 현재 {market_cond} 국면 속에서 {buy_signal} {sell_signal}"



@st.cache_data(ttl=30)  # 30초 캐시 (실시간이지만 너무 잦은 호출 방지)
def fetch_naver_realtime_indices():
    """네이버 금융 API로 코스피/코스닥 실시간 지수 조회"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(
            "https://polling.finance.naver.com/api/realtime/domestic/index/KOSPI,KOSDAQ",
            headers=headers, timeout=3
        )
        if r.status_code == 200:
            datas = r.json().get("datas", [])
            res = {}
            for item in datas:
                code = item.get("itemCode")
                price = float(str(item.get("closePrice")).replace(',', ''))
                chg = float(item.get("fluctuationsRatio", 0))
                status = item.get("marketStatus", "OPEN")
                res[code] = {"price": price, "chg": chg, "status": status}
            return res
    except Exception as e:
        print(f"DEBUG: fetch_naver_realtime_indices failed: {e}")
    return {}

@st.cache_data(ttl=60)
def fetch_stock_realtime_investors(code_list):
    """네이버 금융 API로 개별 종목의 실시간 외국인/기관 수급(가집계) 조회"""
    res = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    for code in code_list:
        try:
            # trend API를 활용하여 당일 최근 수급(실시간 가집계 포함) 획득
            url = f"https://m.stock.naver.com/api/stock/{code}/trend?pageSize=1"
            r = requests.get(url, headers=headers, timeout=1.5)
            if r.status_code == 200:
                data = r.json()
                if data and len(data) > 0:
                    item = data[0]
                    fgn = str(item.get("foreignerPureBuyQuant", "0")).replace(',', '').replace('+', '')
                    org = str(item.get("organPureBuyQuant", "0")).replace(',', '').replace('+', '')
                    res[code] = {
                        "foreign": int(fgn) if fgn.replace('-', '').isdigit() else 0,
                        "institutional": int(org) if org.replace('-', '').isdigit() else 0
                    }
        except Exception as e:
            print(f"DEBUG: fetch_stock_realtime_investors {code} failed: {e}")
    return res


@st.cache_data(ttl=30)  # 30초 캐시
def fetch_naver_realtime_supply():
    """네이버 금융 API로 코스피/코스닥 실시간 투자자 수급 조회"""
    res = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    for mkt_name, mkt_code in [("코스피", "KOSPI"), ("코스닥", "KOSDAQ")]:
        try:
            r = requests.get(f"https://m.stock.naver.com/api/index/{mkt_code}/trend", headers=headers, timeout=3)
            if r.status_code == 200:
                d = r.json()
                res[mkt_name] = {
                    "개인": d.get("personalValue", "0"),
                    "외국인": d.get("foreignValue", "0"),
                    "기관": d.get("institutionalValue", "0")
                }
        except Exception as e:
            print(f"DEBUG: fetch_naver_realtime_supply {mkt_name} failed: {e}")
    return res


import json

def load_portfolio():
    """로컬 my_portfolio.json 파일에서 보유 종목 데이터 로드"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    port_path = os.path.join(base_dir, 'data', 'my_portfolio.json')
    if os.path.exists(port_path):
        try:
            with open(port_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"DEBUG: load_portfolio failed: {e}")
    return {}

def save_portfolio(portfolio):
    """로컬 my_portfolio.json 파일에 보유 종목 데이터 저장"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    port_dir = os.path.join(base_dir, 'data')
    os.makedirs(port_dir, exist_ok=True)
    port_path = os.path.join(port_dir, 'my_portfolio.json')
    try:
        with open(port_path, 'w', encoding='utf-8') as f:
            json.dump(portfolio, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"DEBUG: save_portfolio failed: {e}")

def on_portfolio_go():
    """보유 종목 바로가기 선택 시 무한 Rerun 루프를 방지하면서 종목 이동 처리"""
    if 'port_go_select' in st.session_state:
        selected_go = st.session_state.port_go_select
        if selected_go != "선택 안 함":
            try:
                code_to_go = selected_go.split("(")[-1].replace(")", "").strip()
                port = load_portfolio()
                if code_to_go in port:
                    st.session_state.sel_code = code_to_go
                    st.session_state.sel_name = port[code_to_go]['name']
                    st.query_params['sel_code'] = code_to_go
                    st.query_params['sel_name'] = port[code_to_go]['name']
            except Exception as err:
                print(f"DEBUG: on_portfolio_go failed: {err}")
            # 무한 Rerun 방지를 위해 즉시 selectbox 값을 초기값으로 리셋
            st.session_state.port_go_select = "선택 안 함"

st.set_page_config(
    page_title='GD 3.0 Market Hub',
    page_icon='📊',
    layout='wide',
    initial_sidebar_state='collapsed'
)

# ── GitHub 레포지토리 raw URL (data/ 폴더) ────────────────────────
GITHUB_RAW_BASE = 'https://raw.githubusercontent.com/k2000kms-del/gd3-market-hub/main/data'
DATA_FILES = [
    'df_high_density.csv',
    'df_quant_final.csv',
    'df_full_market.csv',
    'df_market_summary.csv',
    'df_supply_intraday.csv',
]

@st.cache_data(ttl=300)  # 5분 캐시 (일봉 데이터는 자주 바뀌지 않음)
def get_stock_history(code: str):
    """종목 일봉 데이터 조회 (90일)"""
    try:
        # 20일 샹들리에 출구(Chandelier Exit) 계산에 충분한 데이터를 패딩하기 위해 180일 전부터 가져옴 (영업일 기준 약 120일)
        start = (pd.Timestamp.now() - pd.Timedelta(days=180)).strftime('%Y-%m-%d')
        df = fdr.DataReader(code, start)
        return df if not df.empty else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def get_minute_history(code: str, count: int = 300):
    """네이버 실시간 1분봉 데이터 조회"""
    try:
        url = f"https://api.finance.naver.com/siseJson.naver?symbol={code}&requestType=1&timeframe=minute&count={count}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            text = res.text.strip()
            # JSON 호환을 위해 포맷 치환
            text = text.replace("'", '"').replace("null", "None").replace("NaN", "None")
            import ast
            raw_data = ast.literal_eval(text)
            
            if len(raw_data) > 1:
                columns = raw_data[0]
                rows = raw_data[1:]
                
                df = pd.DataFrame(rows, columns=columns)
                df.rename(columns={'날짜': 'Time', '종가': 'Close', '거래량': 'Volume'}, inplace=True)
                
                df = df.dropna(subset=['Time', 'Close'])
                df['Close'] = pd.to_numeric(df['Close'], errors='coerce')
                df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce').fillna(0)
                
                # '202606261530' -> datetime 변환
                df['DateTime'] = pd.to_datetime(df['Time'], format='%Y%m%d%H%M', errors='coerce')
                df = df.dropna(subset=['DateTime'])
                df = df.sort_values('DateTime').reset_index(drop=True)
                return df
    except Exception as e:
        print(f"DEBUG: Failed to get minute history: {e}")
    return pd.DataFrame()


def resample_to_5min(df_1min):
    """1분봉 데이터를 5분 단위로 Resampling하여 5분봉 OHLCV 생성"""
    if df_1min.empty:
        return pd.DataFrame()
    try:
        df = df_1min.copy()
        df.set_index('DateTime', inplace=True)
        
        # 5분 단위 resample (1분봉 종가 흐름으로 OHLC 구성)
        ohlc = df['Close'].resample('5min', closed='left', label='left').ohlc()
        volume = df['Volume'].resample('5min', closed='left', label='left').sum()
        
        resampled = pd.concat([ohlc, volume], axis=1)
        resampled.reset_index(inplace=True)
        
        resampled.rename(columns={
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume'
        }, inplace=True)
        
        resampled = resampled.dropna(subset=['Close'])
        return resampled
    except Exception as e:
        print(f"DEBUG: Resampling failed: {e}")
    return pd.DataFrame()



@st.cache_data(ttl=60)  # 60초 캐시 — rerun마다 전체 시장 다운로드 방지 (핵심 병목)
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


@st.cache_data(ttl=60)  # 60초 캐시 — 지수/환율 FDR 호출
def fetch_live_indices():
    """코스피/코스닥/환율/나스닥 최근 데이터 조회.
    1순위: FDR (로컬 환경)
    2순위: 네이버 실시간 API (Streamlit Cloud — KRX 차단 환경)
    """
    start_date = (pd.Timestamp.now() - pd.Timedelta(days=7)).strftime('%Y-%m-%d')
    result = {}

    # 1순위: FDR 시도
    fdr_ok = False
    try:
        ks = fdr.DataReader('KS11', start_date)
        if not ks.empty:
            result['KS11'] = ks
            result['KQ11'] = fdr.DataReader('KQ11', start_date)
            result['USD/KRW'] = fdr.DataReader('USD/KRW', start_date)
            try:
                result['NQ=F'] = fdr.DataReader('NQ=F', start_date)
            except Exception:
                result['NQ=F'] = pd.DataFrame()
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


@st.cache_data(ttl=60)  # 1분 캐시 — 로컬 우선 로드 및 원격 폴백 지원
def load_data():
    """
    로컬 파일과 원격(GitHub Raw) 파일의 Last-Modified 시간을 체크하여
    원격 파일이 로컬 파일보다 더 최신이거나 로컬 파일이 없는 경우 자동으로 원격에서 최신 데이터를 다운로드하여 덮어씁니다.
    """
    import os
    import urllib.request
    from datetime import datetime, timezone, timedelta
    from email.utils import parsedate_to_datetime
    
    dfs = {}
    update_times = {}
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    for fname in DATA_FILES:
        local_path = os.path.join(base_dir, 'data', fname)
        url = f'{GITHUB_RAW_BASE}/{fname}'
        
        # ── (1) 원격 파일 최종 수정 시각 확인 (HTTP HEAD) ──
        remote_mtime = None
        try:
            req = urllib.request.Request(url, method='HEAD')
            with urllib.request.urlopen(req, timeout=5) as resp:
                last_mod = resp.info().get('Last-Modified')
                if last_mod:
                    dt = parsedate_to_datetime(last_mod)
                    remote_mtime = dt.astimezone(timezone(timedelta(hours=9))) # KST
        except Exception as e:
            print(f"DEBUG: 원격 {fname} 헤더 조회 실패: {e}")
            
        # ── (2) 로컬 파일 수정 시각 확인 ──
        local_mtime = None
        if os.path.exists(local_path):
            try:
                mtime_ts = os.path.getmtime(local_path)
                local_mtime = datetime.fromtimestamp(mtime_ts).astimezone(timezone(timedelta(hours=9)))
            except Exception:
                pass
                
        # ── (3) 자동 동기화 여부 판단: 원격이 더 최신이거나 로컬 파일이 없으면 다운로드 ──
        should_download = False
        if not os.path.exists(local_path):
            should_download = True
        elif remote_mtime and local_mtime:
            # 원격 수정 시간이 로컬 수정 시간보다 10초 이상 최신일 때
            if remote_mtime > local_mtime + timedelta(seconds=10):
                should_download = True
            # 또는 로컬 데이터가 현재 시간보다 30분 이상 낡았고 원격 데이터가 더 최신일 때
            elif datetime.now(timezone(timedelta(hours=9))) - local_mtime > timedelta(minutes=30):
                if remote_mtime > local_mtime:
                    should_download = True
                    
        # ── (4) 동기화 실행 (원격 -> 로컬 다운로드) ──
        if should_download:
            try:
                print(f"DEBUG: {fname} 최신 데이터 원격 자동 동기화 실행 중...")
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                urllib.request.urlretrieve(url, local_path)
                # 다운로드 직후 로컬 시간 갱신
                mtime_ts = os.path.getmtime(local_path)
                local_mtime = datetime.fromtimestamp(mtime_ts).astimezone(timezone(timedelta(hours=9)))
            except Exception as download_err:
                print(f"DEBUG: {fname} 자동 동기화 실패 (기존 로컬 데이터로 Fallback): {download_err}")
                
        # ── (5) 최종 데이터 로드 ──
        loaded = False
        final_mtime_str = None
        
        # 로컬 우선 로드
        if os.path.exists(local_path):
            for enc in ['utf-8-sig', 'utf-8', 'cp949', 'euc-kr']:
                try:
                    dfs[fname] = pd.read_csv(local_path, encoding=enc)
                    loaded = True
                    mtime_ts = os.path.getmtime(local_path)
                    final_mtime_str = datetime.fromtimestamp(mtime_ts).strftime('%Y-%m-%d %H:%M:%S')
                    break
                except Exception:
                    continue
                    
        # 원격 Fallback 로드 (임시 메모리 적재)
        if not loaded:
            try:
                for enc in ['utf-8-sig', 'utf-8', 'cp949', 'euc-kr']:
                    try:
                        dfs[fname] = pd.read_csv(url, encoding=enc)
                        loaded = True
                        break
                    except Exception:
                        continue
                if loaded and remote_mtime:
                    final_mtime_str = remote_mtime.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                pass
                
        if not loaded:
            dfs[fname] = pd.DataFrame()
            final_mtime_str = "데이터 없음"
            
        update_times[fname] = final_mtime_str
        
    return dfs, update_times

# ── 데이터 로드 ────────────────────────────────────────────────
with st.spinner('📡 데이터 불러오는 중...'):
    data, update_times = load_data()

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
            df_q['Total_Score_Adj'] = df_q['Total_Score'].apply(lambda x: round(min(100.0, max(0.0, ((x - mean_score) / std_score * 25.0) + 50.0)), 1))
        else:
            df_q['Total_Score_Adj'] = df_q['Total_Score']
    except Exception as z_err:
        df_q['Total_Score_Adj'] = df_q['Total_Score']

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

# ── 실시간 시세 반영 (FDR → GitHub CSV 폴백) ─────────────────
if df_m is not None and not df_m.empty:
    with st.spinner("🔄 실시간 시세 및 지수 반영 중..."):
        try:
            # 1. 전체 시세 조회 (FDR 실패 시 GitHub CSV 자동 폴백)
            df_live = fetch_live_stock_listing()

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
                # ── 수급 값 포매팅 헬퍼 함수 (루프 외부에 1회만 정의) ──
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



# ── 사이드바 정렬 옵션 ──
# ── 사이드바 정렬 옵션 ──
st.sidebar.title("🎛️ 대시보드 설정")
st.sidebar.markdown("### 🎯 Quant Buy TOP 10")
q_sort_by = st.sidebar.radio(
    "정렬 기준 선택",
    ["Quant 점수 순", "거래대금 순"],
    index=0,
    help="Quant Buy TOP 10 종목을 정렬하는 기준을 선택합니다."
)

# ── 실시간 관심 종목 리스트 생성 (사이드바 드롭다운용) ──
top_stocks = []
try:
    if not df_hd.empty:
        exclude_keywords = ['etf', 'etn', '선물', '인버스', '레버리지', '커버드콜', '스팩', 'kodex', 'tiger', 'kbstar', 'ace', 'sol', 'hanaro', 'kosef']
        df_hd_filtered = df_hd[~df_hd['Name'].fillna('').astype(str).str.lower().apply(lambda x: any(kw in x for kw in exclude_keywords))]
        top_stocks.extend(df_hd_filtered.sort_values('Total_Combined_Net', ascending=False).head(10)[['Code', 'Name']].values.tolist())

    if not df_q.empty:
        exclude_keywords = ['etf', 'etn', '선물', '인버스', '레버리지', '커버드콜', '스팩', 'kodex', 'tiger', 'kbstar', 'ace', 'sol', 'hanaro', 'kosef']
        df_q_filtered = df_q[~df_q['Name'].fillna('').astype(str).str.lower().apply(lambda x: any(kw in x for kw in exclude_keywords))]
        if q_sort_by == "거래대금 순" and 'Amount' in df_q_filtered.columns:
            df_q_sub = df_q_filtered.sort_values('Amount', ascending=False).head(10)
        else:
            df_q_sub = df_q_filtered.sort_values('Total_Score_Adj', ascending=False).head(10)
        top_stocks.extend(df_q_sub[['Code', 'Name']].values.tolist())

    if not df_m.empty:
        exclude_keywords = ['etf', 'etn', '선물', '인버스', '레버리지', '커버드콜', '스팩', 'kodex', 'tiger', 'kbstar', 'ace', 'sol', 'hanaro', 'kosef']
        df_m_filtered = df_m[~df_m['Name'].fillna('').astype(str).str.lower().apply(lambda x: any(kw in x for kw in exclude_keywords))]
        top_stocks.extend(df_m_filtered.sort_values('Amount', ascending=False).head(10)[['Code', 'Name']].values.tolist())
except Exception as list_err:
    print(f"DEBUG: Failed to extract top stocks: {list_err}")

unique_stocks = []
seen_codes = set()
for item in top_stocks:
    code = str(item[0]).strip().zfill(6)
    name = str(item[1]).strip()
    if code not in seen_codes:
        seen_codes.add(code)
        unique_stocks.append((code, name))

unique_stocks = sorted(unique_stocks, key=lambda x: x[1])

options_list = ["선택 안 함 (검색 사용)"]
code_to_name_map = {}
for code, name in unique_stocks:
    label = f"{name} ({code})"
    options_list.append(label)
    code_to_name_map[label] = (code, name)

# 좌측 관심 종목 바로가기 기능 제거됨
options_list = ["선택 안 함 (검색 사용)"]
code_to_name_map = {}
default_idx = 0
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
            if st.sidebar.button(_btn_label, key=f"sb_{_r['Code']}", use_container_width=True):
                st.session_state.sel_code = str(_r['Code']).zfill(6)
                st.session_state.sel_name = str(_r['Name'])
                st.query_params['sel_code'] = str(_r['Code']).zfill(6)
                st.query_params['sel_name'] = str(_r['Name'])
                st.rerun()

portfolio_sidebar_container = st.sidebar.container()


# ── 사이드바 맨 아래: Gemini AI 헬프 센터 ───────────────────
st.sidebar.markdown('---')
st.sidebar.markdown('### 🤖 Gemini AI 헬프 센터')
st.sidebar.caption('대시보드 동작에 문제가 있거나 질문이 있는 경우, 구글 Gemini AI에게 물어보세요.')

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

# 2. 대시보드 상태 로그 첨부 여부
attach_status = st.sidebar.checkbox("대시보드 상태 데이터 첨부", value=True, help="체크하면 대시보드 파일 크기, 시간대, 데이터 로드 상태 등의 디버깅 힌트가 질문과 함께 전송됩니다.")

# 3. 질문 입력창
gemini_prompt = st.sidebar.text_area(
    "질문 입력",
    placeholder="예: 5번 패널 수급 데이터가 왜 안 보이지? 어떻게 고칠 수 있어?",
    label_visibility="collapsed"
)

if st.sidebar.button("Gemini에게 질문하기", use_container_width=True):
    if not gemini_api_key:
        st.sidebar.error("🔑 API Key를 먼저 입력해 주세요.")
    elif not gemini_prompt.strip():
        st.sidebar.warning("✏️ 질문을 입력해 주세요.")
    else:
        with st.sidebar.spinner("🤖 Gemini가 대답을 생성하는 중..."):
            diag_info = ""
            if attach_status:
                import os
                diag_info = "=== 대시보드 진단 데이터 ===\n"
                diag_info += f"현재 KST 시간: {datetime.now(_KST).strftime('%Y-%m-%d %H:%M:%S')}\n"

# 파일 정보 검사
                base_dir = os.path.dirname(os.path.abspath(__file__))
                for f in DATA_FILES:
                    fpath = os.path.join(base_dir, 'data', f)
                    exists = os.path.exists(fpath)
                    sz = os.path.getsize(fpath) if exists else 0
                    mtime = datetime.fromtimestamp(os.path.getmtime(fpath)).strftime('%Y-%m-%d %H:%M') if exists else "N/A"
                    diag_info += f"- {f}: 존재={exists}, 크기={sz}bytes, 최종수정={mtime}\n"

# Supabase 및 세션 상태
                diag_info += f"- Supabase 연동 상태: {'활성화(Client Ready)' if supabase is not None else '비활성화(Secrets 누락)'}\n"
                accum_df_len = len(st.session_state.df_intraday_accum) if 'df_intraday_accum' in st.session_state else 0
                diag_info += f"- 세션 수급 데이터 개수: {accum_df_len}행\n"
                diag_info += "===========================\n\n"

# 헬프 센터 다중 모델 순차 폴백 호출
            models_to_try = [
                "gemini-3.5-flash",
                "gemini-2.5-flash",
                "gemini-2.5-pro",
                "gemini-2.5-flash-lite",
                "gemini-flash-latest"
            ]

            headers = {"Content-Type": "application/json"}
            system_instruction = (
                "너는 주식 분석 대시보드 'GD 3.0 Market Hub'의 모니터링 및 기술 지원을 담당하는 AI 챗봇이야. "
                "사용자가 대시보드 오류나 데이터 미출력 원인을 물으면, 첨부된 '대시보드 진단 데이터'를 면밀히 분석해서 원인을 찾아내고 구체적인 해결 가이드를 한국어로 제시해줘야 해. "
                "코드는 파이썬, Streamlit으로 구현되어 있고 백그라운드 수집기는 GitHub Actions로 구동되며 데이터베이스는 Supabase를 사용해."
            )
            full_prompt = f"{diag_info}질문: {gemini_prompt}"
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
                        st.sidebar.success("🤖 Gemini 답변:")
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


# ── 사이드바 맨 아래: 모바일 자가 복구 도구 ─────────────────
st.sidebar.markdown('---')
st.sidebar.markdown('### 🛠️ 모바일 자가 복구 도구')
st.sidebar.caption('외부 모바일 환경에서 데이터 누락이나 오류 발생 시 직접 안전하게 조치하는 기능입니다.')

# 1. 실시간 데이터 즉시 동기화 버튼
if st.sidebar.button("⚡ 실시간 데이터 즉시 동기화", use_container_width=True, help="클릭 시 즉시 네이버 금융 API에서 최신 수급 데이터를 긁어와 Supabase DB에 강제 적재하고 차트를 새로고침합니다."):
    with st.sidebar.spinner("⚡ 수급 데이터 수집 및 DB 적재 중..."):
        try:
            from datetime import timezone, timedelta
            _KST = timezone(timedelta(hours=9))
            _now_kst = datetime.now(_KST)
            now_time = _now_kst.strftime('%H:%M')
            today_date_str = _now_kst.strftime('%Y%m%d')

# 실시간 수급 크롤링
            nv_supply = fetch_naver_realtime_supply()
            if not nv_supply:
                st.sidebar.error("❌ 네이버 실시간 수급 API 조회 실패")
            else:
                success_count = 0
                for mkt_name in ['코스피', '코스닥']:
                    if mkt_name in nv_supply:
                        m_sup = nv_supply[mkt_name]
                        def clean_sup(val_str):
                            try:
                                return int(str(val_str).replace(',', '').replace('+', '').strip())
                            except:
                                return 0
                        f_val = clean_sup(m_sup.get('외국인', 0))
                        p_val = clean_sup(m_sup.get('개인', 0))
                        i_val = clean_sup(m_sup.get('기관', 0))

# Supabase에 강제 upsert (중복 시 무시하도록 예외 처리)
                        if supabase:
                            try:
                                supabase.table("supply_intraday").upsert({
                                    "date": today_date_str,
                                    "time": now_time,
                                    "market": mkt_name,
                                    "foreign_net": int(f_val),
                                    "individual_net": int(p_val),
                                    "institutional_net": int(i_val)
                                }).execute()
                            except Exception:
# 이미 동일한 시간(분)의 데이터가 적재되어 있다면 에러 무시
                                pass
                            success_count += 1

# Supabase에서 당일 전체 데이터 다시 로드해 세션 갱신
                if supabase:
                    res = supabase.table("supply_intraday").select("*").eq("date", today_date_str).execute()
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
                        st.session_state.df_intraday_accum = pd.DataFrame(records)

                st.sidebar.success(f"✅ {now_time} 시점 수급 데이터 강제 동기화 성공!")
                st.rerun()
        except Exception as sync_err:
            st.sidebar.error(f"❌ 동기화 실패: {sync_err}")

# KIS API Key 정보 (st.secrets 및 os.environ 다각적 별칭 탐색)
kis_key = st.secrets.get("KIS_APP_KEY", st.secrets.get("KIS_KEY", os.environ.get("KIS_APP_KEY", os.environ.get("KIS_KEY", ""))))
kis_sec = st.secrets.get("KIS_APP_SECRET", st.secrets.get("KIS_SECRET", os.environ.get("KIS_APP_SECRET", os.environ.get("KIS_SECRET", ""))))

if st.sidebar.button("🔄 실시간 퀀트 데이터 즉시 갱신", use_container_width=True, help="로컬 엔진을 돌려 전체 시장의 실시간 가격과 수급을 분석하고 퀀트 점수(2번 패널)를 강제 갱신합니다."):
    with st.sidebar.spinner("🎯 퀀트 연산 및 데이터 수집 중 (약 30~50초 소요)..."):
        try:
            import subprocess
            import os

# 환경변수 주입
            env = os.environ.copy()
            env["KIS_APP_KEY"] = kis_key
            env["KIS_KEY"] = kis_key
            env["KIS_APP_SECRET"] = kis_sec
            env["KIS_SECRET"] = kis_sec
            if "SUPABASE_URL" in st.secrets:
                env["SUPABASE_URL"] = st.secrets["SUPABASE_URL"]
            if "SUPABASE_ANON_KEY" in st.secrets:
                env["SUPABASE_ANON_KEY"] = st.secrets["SUPABASE_ANON_KEY"]

# 윈도우 터미널 인코딩(CP949) 환경에서 이모지 출력 시의 UnicodeEncodeError 방지
            env["PYTHONIOENCODING"] = "utf-8"

            base_dir = os.path.dirname(os.path.abspath(__file__))
            script_path = os.path.join(base_dir, 'data_collector.py')

            import sys
            python_exe = sys.executable

            res = subprocess.run([python_exe, script_path], env=env, capture_output=True, encoding='utf-8')
            if res.returncode == 0:
                if not kis_key or not kis_sec:
                    st.sidebar.warning("✅ 갱신 완료 (KIS 인증키가 없어 일부 데이터는 제외됨)")
                else:
                    st.sidebar.success("✅ 퀀트 데이터 실시간 갱신 성공!")
                st.cache_data.clear()
                st.rerun()
            else:
                err_msg = res.stderr if res.stderr else res.stdout
                if not err_msg:
                    err_msg = "알 수 없는 오류가 발생했습니다."
                st.sidebar.error(f"❌ 갱신 실패 (코드 {res.returncode}): {err_msg[:200]}")
        except Exception as e:
            st.sidebar.error(f"❌ 퀀트 연산 중 오류 발생: {e}")

# 2. GitHub Actions 원격 재기동 버튼
st.sidebar.markdown('<br>', unsafe_allow_html=True)
gh_token = st.secrets.get("GITHUB_TOKEN", "")

# secrets에 토큰이 정의되어 있지 않은 경우에만 입력 필드 노출
if not gh_token:
    gh_token = st.sidebar.text_input(
        "GitHub Token (PAT) 입력",
        type="password",
        placeholder="github_pat_...",
        help="GitHub Actions를 강제 가동하려면 Personal Access Token(repo 권한 필요)이 필요합니다."
    )

if st.sidebar.button("🔄 깃허브 수집기 원격 재가동", use_container_width=True, help="깃허브 API를 호출하여 백그라운드 Actions 데이터 수집기(collect_data.yml)를 강제로 즉시 가동시킵니다."):
    if not gh_token:
        st.sidebar.error("🔑 GitHub Token을 먼저 입력해 주세요.")
    else:
        with st.sidebar.spinner("🔄 GitHub Actions 실행 신호 전송 중..."):
            try:
                owner = "k2000kms-del"
                repo = "gd3-market-hub"
                workflow_id = "collect_data.yml"

                url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches"
                headers = {
                    "Authorization": f"Bearer {gh_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28"
                }
                payload = {"ref": "main"}

                r = requests.post(url, json=payload, headers=headers, timeout=20)
                if r.status_code == 204:
                    st.sidebar.success("✅ 깃허브 원격 수집기 가동 성공! (약 2~3분 소요)")
                else:
                    st.sidebar.error(f"❌ 깃허브 API 오류 (코드 {r.status_code}): {r.text[:200]}")
            except Exception as gh_err:
                st.sidebar.error(f"❌ 원격 제어 실패: {gh_err}")



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
        

    print(f"DEBUG: handle_chart_click raw_data: {event_data}")
        
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
    st.markdown(f"### 📊 실시간 시장 종합 대시보드 <span style='font-size: 0.85rem; color: #888; font-weight: normal; margin-left: 10px;'>(퀀트 업데이트: {quant_time})</span>", unsafe_allow_html=True)
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

# 첫 번째 행 (Row 1)과 두 번째 행 (Row 2) 정의
row1_col1, row1_col2, row1_col3 = st.columns(3)
row2_col1, row2_col2, row2_col3 = st.columns(3)

# ── [Panel 1] 실시간 수급 (Treemap) ─────────────────────────
with row1_col1:
    st.markdown("##### 📊 실시간 수급 (외/기/프)")
    if not df_hd.empty and 'Total_Combined_Net' in df_hd.columns:
        df_hd_clean = df_hd.copy()
        
        # ── 1번 패널 이중 안전장치: ETF, ETN, 커버드콜, 선물, 인버스, 레버리지, 스팩 등 파생 및 펀드 상품 필터링 제외 ──
        exclude_keywords = [
            'etf', 'etn', '선물', '인버스', '레버리지', '커버드콜', '스팩', 
            'kodex', 'tiger', 'kbstar', 'ace', 'sol', 'hanaro', 'kosef', 
            'plus', 'rise', 'woori', 'arirang', '곱버스'
        ]
        
        df_hd_clean['Name_lower'] = df_hd_clean['Name'].fillna('').astype(str).str.lower()
        df_hd_clean['Sector_lower'] = df_hd_clean['Sector'].fillna('').astype(str).str.lower() if 'Sector' in df_hd_clean.columns else ''
        
        is_fund = df_hd_clean['Name_lower'].apply(lambda x: any(kw in x for kw in exclude_keywords))
        if 'Sector' in df_hd_clean.columns:
            is_fund = is_fund | df_hd_clean['Sector_lower'].apply(lambda x: 'etf' in str(x) or '수익증권' in str(x))
            
        df_hd_clean = df_hd_clean[~is_fund].drop(columns=['Name_lower', 'Sector_lower'], errors='ignore')
        
        df1 = df_hd_clean.sort_values('Total_Combined_Net', ascending=False).head(10).copy()
        df1['Code'] = df1['Code'].astype(str).str.zfill(6)
        
        # 실시간 외국인/기관 수급 조회
        realtime_sup = fetch_stock_realtime_investors(df1['Code'].tolist())
        
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
        # x축을 중앙 0 기준 대칭으로 설정 (순매도는 왼쪽, 순매수는 오른쪽)
        fig_p1.update_xaxes(range=[-abs_max * 1.35, abs_max * 1.35])
        
        ev_p1 = st.plotly_chart(
            fig_p1,
            use_container_width=True,
            on_select='rerun',
            selection_mode=['points'],
            key=f"p1_chart_{st.session_state.chart_key_index}",
            config={'displayModeBar': False}
        )
        handle_chart_click(ev_p1)
# ── [Panel 2] Quant Buy TOP 10 (Horizontal Bar) ─────────────
with row1_col2:
    st.markdown(f"##### 🎯 Quant Buy TOP 10 ({q_sort_by})")
    fig_p2 = go.Figure()
    x_val = pd.Series(dtype=float)  # NameError 방지: df_q 비어있을 때 기본값
    if not df_q.empty and 'Total_Score' in df_q.columns:
        df2 = df_q.copy()
        
        # ── 대시보드 화면 이중 안전장치: ETF, ETN, 커버드콜, 선물, 인버스, 레버리지, 스팩 등 파생 및 펀드 상품 필터링 제외 ──
        exclude_keywords = [
            'etf', 'etn', '선물', '인버스', '레버리지', '커버드콜', '스팩', 
            'kodex', 'tiger', 'kbstar', 'ace', 'sol', 'hanaro', 'kosef', 
            'plus', 'rise', 'woori', 'arirang', '곱버스'
        ]
        
        df2['Name_lower'] = df2['Name'].fillna('').astype(str).str.lower()
        df2['Sector_lower'] = df2['Sector'].fillna('').astype(str).str.lower() if 'Sector' in df2.columns else ''
        
        is_fund = df2['Name_lower'].apply(lambda x: any(kw in x for kw in exclude_keywords))
        if 'Sector' in df2.columns:
            is_fund = is_fund | df2['Sector_lower'].apply(lambda x: 'etf' in str(x) or '수익증권' in str(x))
            
        df2 = df2[~is_fund].drop(columns=['Name_lower', 'Sector_lower'], errors='ignore')
        
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
            text_labels = df2['Total_Score_Adj'].apply(lambda x: f" {x:.1f}")

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
        use_container_width=True, 
        on_select='rerun', 
        selection_mode=['points'], 
        key=f"p2_chart_{st.session_state.chart_key_index}", 
        config={'displayModeBar': False}
    )
    handle_chart_click(ev_p2)

# ── [Panel 3] 거래대금 리더 (Horizontal Bar) ─────────────────
with row1_col3:
    st.markdown("##### 🔥 거래대금 리더 (12)")
    fig_p3 = go.Figure()
    df3 = pd.DataFrame()  # NameError 방지: df_m 비어있을 때 기본값
    if not df_m.empty and 'Amount' in df_m.columns:
        df_m_clean3 = df_m.copy()
        
        # ── 3번 패널 이중 안전장치: ETF, ETN, 커버드콜, 선물, 인버스, 레버리지, 스팩 등 파생 및 펀드 상품 필터링 제외 ──
        exclude_keywords = [
            'etf', 'etn', '선물', '인버스', '레버리지', '커버드콜', '스팩', 
            'kodex', 'tiger', 'kbstar', 'ace', 'sol', 'hanaro', 'kosef', 
            'plus', 'rise', 'woori', 'arirang', '곱버스'
        ]
        
        df_m_clean3['Name_lower'] = df_m_clean3['Name'].fillna('').astype(str).str.lower()
        df_m_clean3['Sector_lower'] = df_m_clean3['Sector'].fillna('').astype(str).str.lower() if 'Sector' in df_m_clean3.columns else ''
        
        is_fund = df_m_clean3['Name_lower'].apply(lambda x: any(kw in x for kw in exclude_keywords))
        if 'Sector' in df_m_clean3.columns:
            is_fund = is_fund | df_m_clean3['Sector_lower'].apply(lambda x: 'etf' in str(x) or '수익증권' in str(x))
            
        df_m_clean3 = df_m_clean3[~is_fund].drop(columns=['Name_lower', 'Sector_lower'], errors='ignore')
        
        df3 = df_m_clean3.sort_values('Amount', ascending=True).tail(12).copy()
        df3['Amount_100M'] = df3['Amount'] / 100000000
        
        # 매수/매도 거래대금 추정 (CLV + 등락률 하이브리드 모델)
        buy_fractions = []
        for idx, row_i in df3.iterrows():
            close_val = float(row_i.get('Close', 0))
            high_val = float(row_i.get('High', 0))
            low_val = float(row_i.get('Low', 0))
            ratio_val = float(row_i.get('ChagesRatio', 0))
            
            clv = 0.0
            if high_val > low_val:
                clv = ((close_val - low_val) - (high_val - close_val)) / (high_val - low_val)
            
            # 하이브리드 가중치: CLV 30% + 등락률 20% + 기본 50%
            buy_frac = 0.5 + 0.3 * clv + 0.2 * (ratio_val / 30.0)
            buy_frac = max(0.1, min(0.9, buy_frac))
            buy_fractions.append(buy_frac)
            
        df3['Buy_Fraction'] = buy_fractions
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
        use_container_width=True, 
        on_select='rerun', 
        selection_mode=['points'], 
        key=f"p3_chart_{st.session_state.chart_key_index}", 
        config={'displayModeBar': False}
    )
    handle_chart_click(ev_p3)

# ── [Panel 4] 시장 요약 테이블 ──────────────────────────────
with row2_col1:
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
            columnwidth=[1.5, 1.5, 1.5, 0.8, 1.2, 1.2, 1.2],
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
        height=320,
        template='plotly_dark',
        margin=dict(t=10, b=10, l=10, r=10)
    )
    st.plotly_chart(fig_p4, use_container_width=True)

# ── [Panel 5] 코스피/코스닥 수급 (Line) ───────────────────────
with row2_col2:
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
        
        def to_num(s):
            return pd.to_numeric(s.astype(str).str.replace(',', ''), errors='coerce').fillna(0)

        col_cfg = [
            ('Foreign_Net',       '외국인', '#4e9ff5'),
            ('Individual_Net',    '개인',   '#ff6b6b'),
            ('Institutional_Net', '기관',   '#51cf66'),
        ]

        for col, name, color in col_cfg:
            if col in df_line.columns:
                fig_p5.add_trace(go.Scatter(
                    x=df_line['Datetime'], y=to_num(df_line[col]),
                    name=name, mode='lines+markers',
                    line=dict(color=color, width=2),
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
        height=265,  # Radio 높이 고려한 높이 보정
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
            showgrid=True
        )
    )
    st.plotly_chart(fig_p5, use_container_width=True)

# ── [Panel 6] 상승률 리더 (Horizontal Bar) ───────────────────
with row2_col3:
    st.markdown("##### 🚀 상승률 리더 (12)")
    fig_p6 = go.Figure()
    df6 = pd.DataFrame()  # NameError 방지: df_m 비어있을 때 기본값
    if not df_m.empty and 'ChagesRatio' in df_m.columns:
        df_m_clean6 = df_m.copy()
        
        # ── 6번 패널 이중 안전장치: ETF, ETN, 커버드콜, 선물, 인버스, 레버리지, 스팩 등 파생 및 펀드 상품 필터링 제외 ──
        exclude_keywords = [
            'etf', 'etn', '선물', '인버스', '레버리지', '커버드콜', '스팩', 
            'kodex', 'tiger', 'kbstar', 'ace', 'sol', 'hanaro', 'kosef', 
            'plus', 'rise', 'woori', 'arirang', '곱버스'
        ]
        
        df_m_clean6['Name_lower'] = df_m_clean6['Name'].fillna('').astype(str).str.lower()
        df_m_clean6['Sector_lower'] = df_m_clean6['Sector'].fillna('').astype(str).str.lower() if 'Sector' in df_m_clean6.columns else ''
        
        is_fund = df_m_clean6['Name_lower'].apply(lambda x: any(kw in x for kw in exclude_keywords))
        if 'Sector' in df_m_clean6.columns:
            is_fund = is_fund | df_m_clean6['Sector_lower'].apply(lambda x: 'etf' in str(x) or '수익증권' in str(x))
            
        df_m_clean6 = df_m_clean6[~is_fund].drop(columns=['Name_lower', 'Sector_lower'], errors='ignore')
        
        df6 = df_m_clean6.sort_values('ChagesRatio', ascending=True).tail(12).copy()
        
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
                '등락률: <b>%{x:+.2f}%</b><br>'
                '현재가: %{customdata[1]:,}원<br>'
                '거래량: %{customdata[2]:,}주'
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
        use_container_width=True, 
        on_select='rerun', 
        selection_mode=['points'], 
        key=f"p6_chart_{st.session_state.chart_key_index}", 
        config={'displayModeBar': False}
    )
    handle_chart_click(ev_p6)





# ── 종목 일봉 차트 (선택 시 표시) ─────────────────────────────
if st.session_state.sel_code:
    code_disp = st.session_state.sel_code
    
    # 확실하게 종목명을 역맵핑 보정
    if not df_m.empty:
        target_code = str(code_disp).strip().zfill(6)
        match = df_m[df_m['Code'].astype(str).str.split('.').str[0].str.zfill(6) == target_code]
        if not match.empty:
            st.session_state.sel_name = match.iloc[0]['Name']
            
    name_disp = st.session_state.sel_name or code_disp

    col_title, col_close = st.columns([12, 1.5])
    with col_title:
        st.markdown(f"### 📈 {name_disp} ({code_disp}) 일봉 차트")
    with col_close:
        if st.button('✕ 초기화', key='close_chart'):
            st.session_state.sel_code = "005930"
            st.session_state.sel_name = "삼성전자"
            st.query_params['sel_code'] = "005930"
            st.query_params['sel_name'] = "삼성전자"
            # 차트의 selection 상태를 완전히 리셋하기 위해 key 값 증가
            st.session_state.chart_key_index += 1
            st.rerun()

    with st.spinner(f'📡 {name_disp} 주가 데이터 조회 중...'):
        df_candle = get_stock_history(code_disp)
        df_1min = get_minute_history(code_disp, count=300)
        df_5min = resample_to_5min(df_1min)

    if df_candle.empty:
        st.warning('⚠️ 차트 데이터를 불러올 수 없습니다.')
    else:
        # MA 계산
        df_candle['MA5']  = df_candle['Close'].rolling(5).mean()
        df_candle['MA20'] = df_candle['Close'].rolling(20).mean()

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
            
            # 7. 최종 손절선 계산 (시각용 pure 2.5 ATR 트레일링 스톱선 - 오직 상승만 허용하여 널뛰기 방지)
            pure_raw_sl = df_candle['Adj_Highest_High'] - 2.5 * df_candle['ATR']

            stop_loss_series = []
            for i in range(len(df_candle)):
                curr_raw = pure_raw_sl.iloc[i]
                if pd.isna(curr_raw):
                    stop_loss_series.append(curr_raw)
                    continue
                if i == 0:
                    stop_loss_series.append(curr_raw)
                else:
                    prev_sl = stop_loss_series[-1]
                    close_val = df_candle['Close'].iloc[i]
                    if pd.isna(prev_sl):
                        stop_loss_series.append(curr_raw)
                    elif close_val > prev_sl:
                        # 보유 중: 손절선은 오직 위로만 이동 (내려가지 않음)
                        stop_loss_series.append(max(prev_sl, curr_raw))
                    else:
                        # 손절선 이탈 후: 원시값으로 하락 추종 허용 (재진입 준비)
                        stop_loss_series.append(curr_raw)

            df_candle['Stop_Loss'] = stop_loss_series

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

            # 8. 매수/매도 신호 판정 - 상태 머신 방식 (본전 보호 + 퀀트 필터 + 시가 갭손절 + 시간청산 결합)
            # 동적 판정선: 리스크 가속화 ATR 승수 적용
            dynamic_trigger_sl = df_candle['Adj_Highest_High'] - atr_multiplier * df_candle['ATR']
            exit_signal_list = []
            buy_signal_list = []
            in_position = True  # 처음은 보유 중 상태로 시작
            entry_price = df_candle['Close'].iloc[0] if len(df_candle) > 0 else 0.0
            max_price_since_entry = entry_price
            days_in_position = 0

            for i in range(len(df_candle)):
                close_val = df_candle['Close'].iloc[i]
                open_val = df_candle['Open'].iloc[i] if 'Open' in df_candle.columns else close_val
                trigger_sl = dynamic_trigger_sl.iloc[i]
                ma5_val = df_candle['MA5'].iloc[i]
                
                # 전일 기준 손절선 (시가 갭하락 판정용)
                prev_sl = dynamic_trigger_sl.iloc[i-1] if i > 0 else trigger_sl
                
                if pd.isna(trigger_sl) or pd.isna(ma5_val):
                    exit_signal_list.append(False)
                    buy_signal_list.append(False)
                    continue
                    
                if in_position:
                    buy_signal_list.append(False)
                    days_in_position += 1
                    
                    # 최고가 추적
                    max_price_since_entry = max(max_price_since_entry, close_val)
                    # 본전 보호 룰: 진입 후 최고가 고점이 진입가 대비 10% 이상 도달했다면, 
                    # 이후 손절선은 절대로 진입가 + 1% 마진선 이하로 떨어지지 않도록 철저히 잠금(익절 확보)
                    if max_price_since_entry >= entry_price * 1.10:
                        trigger_sl = max(trigger_sl, entry_price * 1.01)

                    # 1) 시가 갭하락 손절: 시가가 전일 기준 손절선을 하회하여 급락 출발 시, 즉시 청산 (블랙스완 방지)
                    if open_val < prev_sl:
                        exit_signal_list.append(True)
                        in_position = False
                        days_in_position = 0
                    # 2) 시간 청산: 5거래일 경과 후 수익률이 본전 대비 ±2% 내외로 정체 시 기회비용 확보를 위해 즉시 청산
                    elif days_in_position >= 5 and abs((close_val - entry_price) / entry_price) <= 0.02:
                        exit_signal_list.append(True)
                        in_position = False
                        days_in_position = 0
                    # 3) 일반 종가 손절선 이탈
                    elif close_val < trigger_sl:
                        exit_signal_list.append(True)
                        in_position = False
                        days_in_position = 0
                    else:
                        exit_signal_list.append(False)
                else:
                    exit_signal_list.append(False)
                    # 미보유 상태: MA5 상향 돌파 + 종목의 퀀트 보정 점수가 완화 기준(buy_threshold) 이상일 때만 매수 진입 (가짜 돌파 필터링)
                    if close_val > ma5_val and (t_score_adj >= buy_threshold):
                        buy_signal_list.append(True)
                        in_position = True
                        entry_price = close_val
                        max_price_since_entry = close_val
                        days_in_position = 0
                    else:
                        buy_signal_list.append(False)
            df_candle['Exit_Signal'] = exit_signal_list
            df_candle['Buy_Signal'] = buy_signal_list

        except Exception as atr_err:
            st.error(f"ATR 계산 오류: {atr_err}")

        df_candle = df_candle.tail(90)  # 최근 90 거래일만 표시

        # 당일 등락률 계산
        if len(df_candle) >= 2:
            prev_close = df_candle['Close'].iloc[-2]
            last_close = df_candle['Close'].iloc[-1]
            daily_chg = (last_close - prev_close) / prev_close * 100 if prev_close > 0 else 0
            chg_color = '#ff6b6b' if daily_chg >= 0 else '#4e9ff5'
            chg_str   = f'{daily_chg:+.2f}%'
        else:
            last_close = df_candle['Close'].iloc[-1]
            chg_str = ''
            chg_color = '#cccccc'

        # 지표 요약 (상단 메트릭 - 프리미엄 HTML 가로 스탯 바)
        ma5_val = f"{int(df_candle['MA5'].iloc[-1]):,}원" if pd.notna(df_candle['MA5'].iloc[-1]) else '-'
        ma20_val = f"{int(df_candle['MA20'].iloc[-1]):,}원" if pd.notna(df_candle['MA20'].iloc[-1]) else '-'
        high_52 = f"{int(df_candle['High'].max()):,}원"
        low_52 = f"{int(df_candle['Low'].min()):,}원"
        
        # 등락 부호 색상
        chg_color_html = "#ff6b6b" if daily_chg >= 0 else "#4e9ff5"
        
        stats_html = f"""
        <div style="display: flex; justify-content: space-around; align-items: center; background-color: #111920; padding: 12px; border-radius: 8px; margin-bottom: 20px; border: 1px solid rgba(78, 159, 245, 0.2); flex-wrap: wrap; gap: 10px;">
          <div style="text-align: center; min-width: 120px;">
            <span style="color: #888; font-size: 0.85rem; font-family: 'malgun gothic', sans-serif;">현재가</span><br>
            <strong style="font-size: 1.25rem; color: #ffffff; font-family: 'malgun gothic', sans-serif;">{int(last_close):,}원</strong>
            <span style="font-size: 0.9rem; color: {chg_color_html}; font-weight: bold;">{chg_str}</span>
          </div>
          <div style="width: 1px; height: 30px; background-color: rgba(255,255,255,0.1);"></div>
          <div style="text-align: center; min-width: 120px;">
            <span style="color: #888; font-size: 0.85rem; font-family: 'malgun gothic', sans-serif;">52주 최고</span><br>
            <strong style="font-size: 1.25rem; color: #ff6b6b; font-family: 'malgun gothic', sans-serif;">{high_52}</strong>
          </div>
          <div style="width: 1px; height: 30px; background-color: rgba(255,255,255,0.1);"></div>
          <div style="text-align: center; min-width: 120px;">
            <span style="color: #888; font-size: 0.85rem; font-family: 'malgun gothic', sans-serif;">52주 최저</span><br>
            <strong style="font-size: 1.25rem; color: #4e9ff5; font-family: 'malgun gothic', sans-serif;">{low_52}</strong>
          </div>
          <div style="width: 1px; height: 30px; background-color: rgba(255,255,255,0.1);"></div>
          <div style="text-align: center; min-width: 120px;">
            <span style="color: #888; font-size: 0.85rem; font-family: 'malgun gothic', sans-serif;">MA5</span><br>
            <strong style="font-size: 1.25rem; color: #ffd43b; font-family: 'malgun gothic', sans-serif;">{ma5_val}</strong>
          </div>
          <div style="width: 1px; height: 30px; background-color: rgba(255,255,255,0.1);"></div>
          <div style="text-align: center; min-width: 120px;">
            <span style="color: #888; font-size: 0.85rem; font-family: 'malgun gothic', sans-serif;">MA20</span><br>
            <strong style="font-size: 1.25rem; color: #ff922b; font-family: 'malgun gothic', sans-serif;">{ma20_val}</strong>
          </div>
        </div>
        """
        
        # ── 💡 퀀트 종합 매매 의견 카드 추가 ──────────────────────────────────
        q_row = df_q[df_q['Code'] == code_disp]
        if not q_row.empty:
            t_score = q_row.iloc[0].get('Total_Score', 0.0)
            t_score_adj = q_row.iloc[0].get('Total_Score_Adj', t_score)
            s_score = q_row.iloc[0].get('Sell_Score', 0.0)
            
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

            # 종합 등급 판정 (보정 매수 점수 t_score_adj 기준)
            if t_score_adj >= 80.0:
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
            raw_market_cond = q_row.iloc[0].get('Market_Condition', 'N/A')
            market_cond = clean_market_condition_korean(raw_market_cond)
            try:
                ai_comment = get_gemini_commentary(
                    code_disp, name_disp, t_score, t_score_adj, s_score, daily_chg, market_cond, rec_cash, rec_stock, gemini_api_key
                )
            except Exception as e:
                err_str = str(e)
                if "Key가 설정되지 않아" in err_str:
                    ai_comment = err_str
                else:
                    ai_comment = get_local_fallback_commentary(name_disp, t_score_adj, s_score, market_cond)
            
            opinion_html = f"""<div style="background-color: #111920; padding: 15px; border-radius: 8px; border: 1px solid rgba(78, 159, 245, 0.2); margin-bottom: 20px; color: #fff;">
<h4 style="margin: 0 0 10px 0; color: #ff922b; font-size: 16px; font-family: 'malgun gothic', sans-serif;">💡 퀀트 종합 매매 의견</h4>
<div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 12px;">
    <div>
        <span style="font-size: 14px; color: #aaa; font-family: 'malgun gothic', sans-serif;">보정 평가 등급:</span>
        <strong style="font-size: 18px; color: {grade_color}; margin-left: 8px; font-family: 'malgun gothic', sans-serif;">{quant_grade}</strong>
    </div>
    <div style="text-align: right; min-width: 140px;">
        <span style="font-size: 13px; color: #2ecc71; font-family: 'malgun gothic', sans-serif;">매수 보정 점수: <strong>{t_score_adj:.1f}점</strong> <span style="font-size: 11px; color: #888;">(원점수: {t_score:.1f}점)</span></span><br/>
        <span style="font-size: 13px; color: #e74c3c; font-family: 'malgun gothic', sans-serif;">매도 퀀트 점수: <strong>{s_score:.1f}점</strong></span>
    </div>
</div>

<div style="background-color: rgba(255, 255, 255, 0.03); padding: 10px; border-radius: 6px; border-left: 4px solid #ff922b; font-size: 13px; line-height: 1.5; color: #eee; font-family: 'malgun gothic', sans-serif;">
    <strong>🤖 AI 퀀트 리스크 조언:</strong><br/>
    {ai_comment}
</div>
</div>"""
            col_op, col_rd = st.columns([7, 3.5])
            with col_op:
                st.markdown(stats_html, unsafe_allow_html=True)
                st.markdown(opinion_html, unsafe_allow_html=True)
            with col_rd:
                # 💼 실시간 포트폴리오 관리 패널 구현
                portfolio = load_portfolio()
                
                portfolio_sidebar_container.markdown('---')
                portfolio_sidebar_container.markdown('### 💼 실전 포트폴리오 관리')
                st.markdown("##### 💼 나의 보유 종목")
                
                # 현재 조회 중인 종목 보유 여부
                is_held = code_disp in portfolio
                held_info = portfolio.get(code_disp, {"entry_price": 0.0, "qty": 0.0})
                
                # 평단가 및 수량 입력란 (streamlit input 사용)
                col_p1, col_p2 = portfolio_sidebar_container.columns(2)
                with col_p1:
                    input_price = portfolio_sidebar_container.number_input(
                        "매수 평단가 (원)", 
                        min_value=0.0, 
                        value=float(held_info["entry_price"]) if is_held else float(last_close), 
                        step=100.0,
                        key="port_input_price"
                    )
                with col_p2:
                    input_qty = portfolio_sidebar_container.number_input(
                        "보유 수량 (주)", 
                        min_value=0.0, 
                        value=float(held_info["qty"]) if is_held else 0.0, 
                        step=1.0,
                        key="port_input_qty"
                    )
                
                # 등록/수정/삭제 버튼
                col_btn1, col_btn2 = portfolio_sidebar_container.columns(2)
                with col_btn1:
                    if portfolio_sidebar_container.button("➕ 등록/수정", use_container_width=True, key="btn_port_save"):
                        if input_price > 0 and input_qty > 0:
                            portfolio[code_disp] = {
                                "name": name_disp,
                                "entry_price": input_price,
                                "qty": input_qty
                            }
                            save_portfolio(portfolio)
                            portfolio_sidebar_container.toast(f"💼 {name_disp} 포트폴리오 저장 완료!", icon="✅")
                            st.rerun()
                        else:
                            portfolio_sidebar_container.warning("가격과 수량을 입력해주세요.")
                with col_btn2:
                    if is_held:
                        if portfolio_sidebar_container.button("🗑️ 삭제", use_container_width=True, key="btn_port_del"):
                            del portfolio[code_disp]
                            save_portfolio(portfolio)
                            portfolio_sidebar_container.toast(f"🗑️ {name_disp} 포트폴리오 삭제 완료", icon="ℹ️")
                            st.rerun()
                    else:
                        portfolio_sidebar_container.button("🗑️ 삭제", use_container_width=True, disabled=True, key="btn_port_del_dis")
                
                # 포트폴리오 목록 및 바로가기
                if portfolio:

                    # 포트폴리오 테이블 렌더링
                    port_rows = []
                    for p_code, p_data in portfolio.items():
                        p_close = 0.0
                        if df_m is not None and not df_m.empty:
                            m_match = df_m[df_m['Code'] == p_code]
                            if not m_match.empty:
                                p_close = float(m_match.iloc[0]['Close'])
                        if p_close == 0.0:
                            p_close = p_data["entry_price"]
                            
                        p_return = ((p_close - p_data["entry_price"]) / p_data["entry_price"]) * 100.0
                        eval_diff = (p_close - p_data["entry_price"]) * p_data["qty"]
                        
                        rt_color = "#ff6b6b" if p_return > 0 else "#4e9ff5" if p_return < 0 else "#888888"
                        rt_sign = "+" if p_return > 0 else ""
                        
                        import urllib.parse
                        encoded_name = urllib.parse.quote(p_data["name"])
                        port_rows.append({
                            "종목명": f"<a href='/?sel_code={p_code}&sel_name={encoded_name}' target='_self' style='color: #ffffff; text-decoration: none; cursor: pointer;' onmouseover='this.style.color=\"#00e5ff\";' onmouseout='this.style.color=\"#ffffff\";'>{p_data['name']}</a>",
                            "매수가": f"{int(p_data['entry_price']):,}",
                            "수량": f"{int(p_data['qty']):,}",
                            "수익률": f"<span style='color:{rt_color}; font-weight:bold;'>{rt_sign}{p_return:.2f}%</span>",
                            "평가손익": f"<span style='color:{rt_color}; font-weight:bold;'>{rt_sign}{int(eval_diff):,}원</span>"
                        })
                    
                    # 스타일이 적용된 고급 다크 테마 HTML 테이블 생성
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
                        background-color: rgba(255, 255, 255, 0.03);
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
                                </tr>
                            </thead>
                            <tbody>
                    """
                    for row in port_rows:
                        table_html += f"""
                                <tr>
                                    <td style="font-weight: bold; color: #ffffff;">{row['종목명']}</td>
                                    <td>{row['매수가']}</td>
                                    <td>{row['수량']}</td>
                                    <td>{row['수익률']}</td>
                                    <td>{row['평가손익']}</td>
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

        # 캔들 차트 생성
        fig_c = make_subplots(
            rows=2, cols=1,
            row_heights=[0.72, 0.28],
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
            name='캔들', showlegend=False
        ), row=1, col=1)

        # MA5
        fig_c.add_trace(go.Scatter(
            x=date_str_list, y=df_candle['MA5'],
            name='MA5', mode='lines',
            line=dict(color='#ffd43b', width=1.5)
        ), row=1, col=1)

        # MA20
        fig_c.add_trace(go.Scatter(
            x=date_str_list, y=df_candle['MA20'],
            name='MA20', mode='lines',
            line=dict(color='#ff922b', width=1.5)
        ), row=1, col=1)

        # ATR 손절 가이드선 (2.5 ATR)
        if 'Stop_Loss' in df_candle.columns:
            fig_c.add_trace(go.Scatter(
                x=date_str_list, y=df_candle['Stop_Loss'],
                name='ATR 손절선', mode='lines',
                line=dict(color='#e74c3c', width=1.5, dash='dash')
            ), row=1, col=1)
            
            # 매도 신호 (이탈 시 Plotly Annotation으로 선 가림 마스킹 처리를 포함한 말풍선 화살표 띄움)
            if 'Exit_Signal' in df_candle.columns:
                exit_signals = df_candle[df_candle['Exit_Signal'] == True]
                if not exit_signals.empty:
                    # 범례(Legend) 표시용 더미 트레이스 (차트에는 나타나지 않음)
                    fig_c.add_trace(go.Scatter(
                        x=[None], y=[None],
                        mode='markers',
                        name='매도 신호',
                        marker=dict(symbol='triangle-down', size=10, color='#00e5ff'),
                        showlegend=True
                    ), row=1, col=1)
                    
                    # 각 신호 시점에 겹침 방지 말풍선 추가 (⚠️ 매도 + 금액 표시)
                    for idx, row_sig in exit_signals.iterrows():
                        close_val = row_sig['Close']
                        price_str = f"{int(close_val):,}원" if close_val >= 100 else f"{close_val:,.2f}"
                        idx_str = idx.strftime('%Y-%m-%d')
                        fig_c.add_annotation(
                            x=idx_str,
                            y=row_sig['High'],
                            text=f"<b>⚠️ 매도</b><br>{price_str}",
                            showarrow=True,
                            arrowhead=2,
                            arrowsize=1.0,
                            arrowwidth=2,
                            arrowcolor="#00e5ff",
                            ax=0,
                            ay=-45,  # 텍스트가 두 줄이 되었으므로 고정 오프셋을 -35에서 -45로 늘려 가독성 확보
                            font=dict(color="#00e5ff", size=10, family="malgun gothic"),
                            bgcolor="#0d1b2a",  # 차트 배경색(#0d1b2a)으로 글자 배경을 채워 뒤로 지나는 MA선과 캔들 꼬리를 완벽하게 마스킹함
                            bordercolor="#00e5ff",
                            borderwidth=1.5,
                            borderpad=4,
                            row=1, col=1
                        )
            
            # 매수 신호 (MA5 상향 돌파 시 Plotly Annotation으로 금액 표시를 포함한 화살표 띄움)
            if 'Buy_Signal' in df_candle.columns:
                buy_signals = df_candle[df_candle['Buy_Signal'] == True]
                if not buy_signals.empty:
                    # 범례(Legend) 표시용 더미 트레이스 (차트에는 나타나지 않음)
                    fig_c.add_trace(go.Scatter(
                        x=[None], y=[None],
                        mode='markers',
                        name='매수 신호',
                        marker=dict(symbol='triangle-up', size=10, color='#2ecc71'),
                        showlegend=True
                    ), row=1, col=1)
                    
                    # 각 신호 시점에 말풍선 추가 (🟢 매수 + 금액 표시)
                    for idx, row_sig in buy_signals.iterrows():
                        close_val = row_sig['Close']
                        price_str = f"{int(close_val):,}원" if close_val >= 100 else f"{close_val:,.2f}"
                        idx_str = idx.strftime('%Y-%m-%d')
                        fig_c.add_annotation(
                            x=idx_str,
                            y=row_sig['Low'],
                            text=f"<b>🟢 매수</b><br>{price_str}",
                            showarrow=True,
                            arrowhead=2,
                            arrowsize=1.0,
                            arrowwidth=2,
                            arrowcolor="#2ecc71",
                            ax=0,
                            ay=45,  # 캔들 하단에 위치하도록 양수 값 설정
                            font=dict(color="#2ecc71", size=10, family="malgun gothic"),
                            bgcolor="#0d1b2a",  # 차트 배경색으로 마스킹
                            bordercolor="#2ecc71",
                            borderwidth=1.5,
                            borderpad=4,
                            row=1, col=1
                        )

        # 나의 매수 단가선 (포트폴리오 등록 시 황금색 점선으로 표시)
        portfolio = load_portfolio()
        my_entry_price = 0
        if code_disp in portfolio:
            my_entry_price = portfolio[code_disp]["entry_price"]
            fig_c.add_trace(go.Scatter(
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
            margin = (max_val - min_val) * 0.05 if max_val > min_val else 1000
            y_range = [min_val - margin, max_val + margin]
        except Exception:
            y_range = None

        # 거래량 막대 (색상: 상승일=빨강, 하락일=파랑)
        vol_colors = [
            '#ff6b6b' if c >= o else '#4e9ff5'
            for c, o in zip(df_candle['Close'], df_candle['Open'])
        ]
        fig_c.add_trace(go.Bar(
            x=date_str_list, y=df_candle['Volume'],
            name='거래량', marker_color=vol_colors,
            showlegend=False, opacity=0.8
        ), row=2, col=1)

        # 우측 Y축 눈금(yaxis3)을 활성화하기 위한 더미 투명 트레이스 주입 (row/col 생략하여 layout y3 매핑)
        fig_c.add_trace(go.Scatter(
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
            height=480,
            margin=dict(t=20, l=10, r=55, b=10), # 우측 가격 눈금을 위한 여백
            xaxis_rangeslider_visible=False,
            legend=dict(orientation='h', x=0, y=1.02, font=dict(size=11)),
            font=dict(family='malgun gothic, nanum gothic, sans-serif'),
            plot_bgcolor='#0d1b2a',
            paper_bgcolor='#0d1b2a',
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
                nticks=18 # 눈금을 더 촘촘히 표시
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
            row=1, col=1
        )

        # 현재가 우측 Y축 라벨 박스 투사 (상승 시 빨강, 하락 시 파랑 HTS 형태)
        price_color = '#ff6b6b' if daily_chg >= 0 else '#4e9ff5'
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

        fig_c.update_yaxes(tickformat=',d', gridcolor='rgba(255,255,255,0.06)', row=2, col=1)
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
            row=2, col=1
        )

        # ── 5분봉 차트 생성 ─────────────────────────────
        fig_5m = make_subplots(
            rows=2, cols=1,
            row_heights=[0.72, 0.28],
            vertical_spacing=0.03,
            shared_xaxes=True
        )
        if not df_5min.empty:
            df_5min_tail = df_5min.tail(60).copy()
            time_str_list_5m = df_5min_tail['DateTime'].dt.strftime('%H:%M').tolist()
            
            fig_5m.add_trace(go.Candlestick(
                x=time_str_list_5m,
                open=df_5min_tail['Open'], high=df_5min_tail['High'],
                low=df_5min_tail['Low'], close=df_5min_tail['Close'],
                increasing=dict(line=dict(color='#ff6b6b'), fillcolor='#ff6b6b'),
                decreasing=dict(line=dict(color='#4e9ff5'), fillcolor='#4e9ff5'),
                name='5분봉 캔들', showlegend=False
            ), row=1, col=1)
            
            df_5min_tail['MA5'] = df_5min_tail['Close'].rolling(5).mean()
            df_5min_tail['MA20'] = df_5min_tail['Close'].rolling(20).mean()
            
            fig_5m.add_trace(go.Scatter(
                x=time_str_list_5m, y=df_5min_tail['MA5'],
                name='MA5', mode='lines',
                line=dict(color='#ffd43b', width=1.5)
            ), row=1, col=1)
            
            fig_5m.add_trace(go.Scatter(
                x=time_str_list_5m, y=df_5min_tail['MA20'],
                name='MA20', mode='lines',
                line=dict(color='#ff922b', width=1.5)
            ), row=1, col=1)
            
            vol_colors_5m = [
                '#ff6b6b' if c >= o else '#4e9ff5'
                for c, o in zip(df_5min_tail['Close'], df_5min_tail['Open'])
            ]
            fig_5m.add_trace(go.Bar(
                x=time_str_list_5m, y=df_5min_tail['Volume'],
                name='거래량', marker_color=vol_colors_5m,
                showlegend=False, opacity=0.8
            ), row=2, col=1)

            # 5분봉 가격 범위(y_range) 수동 계산
            try:
                min_val_5m = df_5min_tail[['High', 'Low', 'Close', 'Open']].min().min()
                max_val_5m = df_5min_tail[['High', 'Low', 'Close', 'Open']].max().max()
                margin_5m = (max_val_5m - min_val_5m) * 0.05 if max_val_5m > min_val_5m else 100
                y_range_5m = [min_val_5m - margin_5m, max_val_5m + margin_5m]
            except Exception:
                y_range_5m = None

            # 우측 Y축 눈금(yaxis3)을 활성화하기 위한 더미 투명 트레이스 주입 (row/col 생략하여 layout y3 매핑)
            fig_5m.add_trace(go.Scatter(
                x=time_str_list_5m,
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
                height=480,
                margin=dict(t=20, l=10, r=55, b=10), # 우측 눈금을 위한 여백
                xaxis_rangeslider_visible=False,
                legend=dict(orientation='h', x=0, y=1.02, font=dict(size=11)),
                font=dict(family='malgun gothic, nanum gothic, sans-serif'),
                plot_bgcolor='#0d1b2a',
                paper_bgcolor='#0d1b2a',
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
            fig_5m.update_yaxes(tickformat=',d', gridcolor='rgba(255,255,255,0.06)', row=2, col=1)
            fig_5m.update_xaxes(type='category', gridcolor='rgba(255,255,255,0.04)', showticklabels=False, row=1, col=1)
            fig_5m.update_xaxes(type='category', gridcolor='rgba(255,255,255,0.04)', tickangle=-30, row=2, col=1)

        # ── 1분봉 차트 생성 ─────────────────────────────
        fig_1m = make_subplots(
            rows=2, cols=1,
            row_heights=[0.72, 0.28],
            vertical_spacing=0.03,
            shared_xaxes=True
        )
        if not df_1min.empty:
            df_1min_tail = df_1min.tail(90).copy()
            time_str_list_1m = df_1min_tail['DateTime'].dt.strftime('%H:%M').tolist()
            
            fig_1m.add_trace(go.Scatter(
                x=time_str_list_1m, y=df_1min_tail['Close'],
                mode='lines', name='1분봉 종가',
                line=dict(color='#00e5ff', width=2),
                fill='toself', fillcolor='rgba(0, 229, 255, 0.05)'
            ), row=1, col=1)
            
            vol_colors_1m = []
            for i in range(len(df_1min_tail)):
                if i == 0:
                    vol_colors_1m.append('#ff6b6b')
                else:
                    vol_colors_1m.append('#ff6b6b' if df_1min_tail['Close'].iloc[i] >= df_1min_tail['Close'].iloc[i-1] else '#4e9ff5')
            fig_1m.add_trace(go.Bar(
                x=time_str_list_1m, y=df_1min_tail['Volume'],
                name='거래량', marker_color=vol_colors_1m,
                showlegend=False, opacity=0.8
            ), row=2, col=1)

            # 1분봉 가격 범위(y_range) 수동 계산
            try:
                min_val_1m = df_1min_tail['Close'].min()
                max_val_1m = df_1min_tail['Close'].max()
                margin_1m = (max_val_1m - min_val_1m) * 0.05 if max_val_1m > min_val_1m else 100
                y_range_1m = [min_val_1m - margin_1m, max_val_1m + margin_1m]
            except Exception:
                y_range_1m = None

            # 우측 Y축 눈금(yaxis3)을 활성화하기 위한 더미 투명 트레이스 주입 (row/col 생략하여 layout y3 매핑)
            fig_1m.add_trace(go.Scatter(
                x=time_str_list_1m,
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
                height=480,
                margin=dict(t=20, l=10, r=55, b=10), # 우측 눈금을 위한 여백
                xaxis_rangeslider_visible=False,
                legend=dict(orientation='h', x=0, y=1.02, font=dict(size=11)),
                font=dict(family='malgun gothic, nanum gothic, sans-serif'),
                plot_bgcolor='#0d1b2a',
                paper_bgcolor='#0d1b2a',
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
            fig_1m.update_yaxes(tickformat=',d', gridcolor='rgba(255,255,255,0.06)', row=2, col=1)
            fig_1m.update_xaxes(type='category', gridcolor='rgba(255,255,255,0.04)', showticklabels=False, row=1, col=1)
            fig_1m.update_xaxes(type='category', gridcolor='rgba(255,255,255,0.04)', tickangle=-30, row=2, col=1)

        # ── 탭 레이아웃 렌더링 ─────────────────────────────
        tab_day, tab_5m, tab_1m = st.tabs(["📅 일봉 차트", "⏱️ 5분봉 (캔들)", "⚡ 1분봉 (라인)"])
        with tab_day:
            st.plotly_chart(fig_c, use_container_width=True)
        with tab_5m:
            if not df_5min.empty:
                st.plotly_chart(fig_5m, use_container_width=True)
            else:
                st.info("⚠️ 5분봉 데이터를 불러올 수 없거나 휴장일입니다.")
        with tab_1m:
            if not df_1min.empty:
                st.plotly_chart(fig_1m, use_container_width=True)
            else:
                st.info("⚠️ 1분봉 데이터를 불러올 수 없거나 휴장일입니다.")

    st.divider()

# 하단 갱신 버튼 및 60초 자동 새로고침 JS
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if st.button('🔄 데이터 새로고침', use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# 60초 주기 자동 새로고침 및 스크롤 실시간 복원 연동 (HTML 컴포넌트)
html_script = """
    <script>
    (function() {
        var parentWin = window.parent || window;
        
        // 1. 60초 자동 새로고침
        setTimeout(function() {
            parentWin.postMessage({type: 'streamlit:rerun'}, '*');
        }, 60000);
        
        // 2. 실시간 스크롤 위치 기록 리스너
        try {
            parentWin.addEventListener('scroll', function() {
                try {
                    localStorage.setItem('st_dashboard_scroll', parentWin.scrollY);
                } catch (scrollErr) {}
            });
        } catch (e) {
            console.error("Scroll event listener binding failed:", e);
        }
        
        // 3. 페이지 로드 완료 시 스크롤 위치 복원
        try {
            var scrollPos = localStorage.getItem('st_dashboard_scroll');
            if (scrollPos) {
                parentWin.scrollTo(0, parseInt(scrollPos));
            }
        } catch (e) {
            console.error("Scroll restore failed:", e);
        }
    })();
    </script>
"""

st.html(html_script)
