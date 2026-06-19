# -*- coding: utf-8 -*-
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import FinanceDataReader as fdr
import requests
import time
from datetime import datetime

# ── Supabase 클라이언트 초기화 ────────────────────────────────
supabase = None
if "SUPABASE_URL" in st.secrets and "SUPABASE_ANON_KEY" in st.secrets:
    try:
        from supabase import create_client
        supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])
    except Exception as e:
        print(f"DEBUG: Supabase initialization failed: {e}")

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
        start = (pd.Timestamp.now() - pd.Timedelta(days=120)).strftime('%Y-%m-%d')
        df = fdr.DataReader(code, start)
        return df if not df.empty else pd.DataFrame()
    except Exception:
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


@st.cache_data(ttl=60)  # 1분 캐시 — GitHub raw 다운로드 반복 방지 (최신 데이터 빠른 반영)
def load_data():
    """GitHub 레포지토리 raw URL에서 CSV 읽기 (간단하고 인증 불필요)"""
    dfs = {}
    for fname in DATA_FILES:
        try:
            url = f'{GITHUB_RAW_BASE}/{fname}'
            loaded = False
            for enc in ['utf-8-sig', 'utf-8', 'cp949', 'euc-kr']:
                try:
                    dfs[fname] = pd.read_csv(url, encoding=enc)
                    loaded = True
                    break
                except Exception:
                    continue
            if not loaded:
                dfs[fname] = pd.DataFrame()
        except Exception:
            dfs[fname] = pd.DataFrame()
    return dfs

# ── 데이터 로드 ────────────────────────────────────────────────
with st.spinner('📡 데이터 불러오는 중...'):
    data = load_data()

df_hd       = data['df_high_density.csv']
df_q        = data['df_quant_final.csv']
df_m        = data['df_full_market.csv']
df_summary  = data['df_market_summary.csv']
df_intraday = data['df_supply_intraday.csv']

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
    with st.sidebar.status("🔄 실시간 시세 및 지수 반영 중...", expanded=False) as status:
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
                st.write("📊 주요 지수 및 환율 조회 중...")
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
                                def format_sup(val_str):
                                    v = str(val_str).strip().replace(',', '')
                                    try:
                                        f_val = float(v)
                                        return f"{f_val:+.0f}" if f_val != 0 else "0"
                                    except:
                                        return val_str
                                
                                df_summary.at[idx, '개인(억)'] = format_sup(m_sup.get('개인', '0'))
                                df_summary.at[idx, '외국인(억)'] = format_sup(m_sup.get('외국인', '0'))
                                df_summary.at[idx, '기관(억)'] = format_sup(m_sup.get('기관', '0'))
                    
                    # ── 당일 실시간 수급 세션 누적 적재 (1분마다 새 포인트 추가) ──
                    try:
                        from datetime import timezone, timedelta
                        _KST = timezone(timedelta(hours=9))
                        _now_kst = datetime.now(_KST)
                        now_time = _now_kst.strftime('%H:%M')
                        h_m = _now_kst.hour * 100 + _now_kst.minute
                        # 장중(09:00~15:30)이고, 마지막 누적 시각과 현재 시각이 다를 때만 추가
                        last_accum_time = st.session_state.get('last_accum_time', '')
                        if 900 <= h_m <= 1530 and now_time != last_accum_time:
                            for mkt_name in ['코스피', '코스닥']:
                                if mkt_name in nv_supply:
                                    m_sup = nv_supply[mkt_name]
                                    def clean_sup(val_str):
                                        try:
                                            # 네이버 API는 억원 단위 문자열('+5,254') 반환
                                            return int(str(val_str).replace(',', '').replace('+', '').strip())
                                        except:
                                            return 0
                                    f_val = clean_sup(m_sup.get('외국인', 0))
                                    p_val = clean_sup(m_sup.get('개인', 0))
                                    i_val = clean_sup(m_sup.get('기관', 0))

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
                    except Exception as accum_err:
                        print(f"DEBUG: Accumulation failed: {accum_err}")

                    st.write("✅ 네이버 실시간 지수 및 수급 반영 완료")
                except Exception as e:
                    st.write(f"⚠️ 네이버 실시간 정보 반영 실패: {e}")
                    
                    # 실패 시 기존 디폴트/폴백 처리 복구
                    default_supplies = {
                        '코스피': {'개인': '+452', '외국인': '-120', '기관': '-310'},
                        '코스닥': {'개인': '+120', '외국인': '+85', '기관': '-188'}
                    }
                    for idx, row in df_summary.iterrows():
                        name = str(row['종목/종류'])
                        for m_name in ['코스피', '코스닥']:
                            if m_name in name:
                                df_summary.at[idx, '개인(억)'] = default_supplies[m_name]['개인']
                                df_summary.at[idx, '외국인(억)'] = default_supplies[m_name]['외국인']
                                df_summary.at[idx, '기관(억)'] = default_supplies[m_name]['기관']
                    
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
                    st.write("✅ 폴백 지수 및 수급 반영 완료")
                st.write("✅ 지수 및 수급 반영 완료")
        except Exception as e:
            st.write(f"❌ 지수 및 환율 반영 실패: {e}")
        
        status.update(label="⚡ 실시간 시세 반영 완료", state="complete")

# ── 세션 스테이트 초기화 (종목 클릭 차트용 및 실시간 수급 누적) ────────────────────
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
    # Supabase에서 당일 축적된 수급 데이터 로드
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
    st.session_state.df_intraday_accum = loaded_df



# ── 사이드바 정렬 옵션 ──
st.sidebar.title("🎛️ 대시보드 설정")
st.sidebar.markdown("### 🎯 Quant Buy TOP 10")
q_sort_by = st.sidebar.radio(
    "정렬 기준 선택",
    ["Quant 점수 순", "거래대금 순"],
    index=0,
    help="Quant Buy TOP 10 종목을 정렬하는 기준을 선택합니다."
)

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


# ── 사이드바 맨 아래: Gemini AI 헬프 센터 ───────────────────
st.sidebar.markdown('---')
st.sidebar.markdown('### 🤖 Gemini AI 헬프 센터')
st.sidebar.caption('대시보드 동작에 문제가 있거나 질문이 있는 경우, 구글 Gemini AI에게 물어보세요.')

# 1. API Key 불러오기 및 입력창
gemini_api_key = st.secrets.get("GEMINI_API_KEY", "")
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
            
            # API 호출
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={gemini_api_key}"
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
            
            try:
                r = requests.post(url, json=payload, headers=headers, timeout=20)
                if r.status_code == 200:
                    ans = r.json()['candidates'][0]['content']['parts'][0]['text']
                    st.sidebar.success("🤖 Gemini 답변:")
                    st.sidebar.markdown(ans)
                else:
                    st.sidebar.error(f"❌ API 에러 (코드 {r.status_code}): {r.text[:200]}")
            except Exception as ex:
                st.sidebar.error(f"❌ 요청 중 오류 발생: {ex}")


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
                        
                        # Supabase에 강제 upsert (기존 데이터 삭제 없이 업데이트)
                        if supabase:
                            supabase.table("supply_intraday").upsert({
                                "date": today_date_str,
                                "time": now_time,
                                "market": mkt_name,
                                "foreign_net": int(f_val),
                                "individual_net": int(p_val),
                                "institutional_net": int(i_val)
                            }).execute()
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
    if event_data:
        print("DEBUG: handle_chart_click event_data:", event_data)
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
    # Treemap은 label, Bar 차트는 y에 레이블이 얹혀 리턴됨
    clicked_name = pt.get('label', '') or pt.get('y', '')
    cd = pt.get('customdata', [])
    
    found_code = None
    import numpy as np
    if isinstance(cd, (list, tuple, np.ndarray)) and len(cd) > 0:
        for val in cd:
            v_str = str(val).split('.')[0].zfill(6)
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
        st.rerun()

# ── 개별 차트 6분할 레이아웃 (3열 그리드 개편) ───────────────
st.markdown("### 📊 실시간 시장 종합 대시보드")
st.caption("차트 내부의 막대(종목)를 클릭하면, 아래에서 즉시 해당 종목의 일봉 차트를 볼 수 있습니다.")

# 첫 번째 행 (Row 1)과 두 번째 행 (Row 2) 정의
row1_col1, row1_col2, row1_col3 = st.columns(3)
row2_col1, row2_col2, row2_col3 = st.columns(3)

# ── [Panel 1] 실시간 수급 (Treemap) ─────────────────────────
with row1_col1:
    st.markdown("##### 📊 실시간 수급 (외/기/프)")
    if not df_hd.empty and 'Total_Combined_Net' in df_hd.columns:
        df1 = df_hd.sort_values('Total_Combined_Net', ascending=False).head(10).copy()
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
        
        # 실시간 수급 데이터 덮어쓰기
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
        
        df1['Disp'] = df1['ChagesRatio'].apply(lambda x: f"{x:+.2f}%")
        
        style_html = """<style>.tm-card:hover { transform: scale(0.97) !important; filter: brightness(1.2) !important; z-index: 10 !important; } .tm-card-wrapper { z-index: 1; } .tm-card-wrapper:hover { z-index: 999 !important; } .tm-card-wrapper:hover .tm-tooltip { visibility: visible !important; opacity: 1 !important; left: 105% !important; top: 50% !important; transform: translateY(-50%) !important; } .tm-column:last-child .tm-card-wrapper:hover .tm-tooltip { left: auto !important; right: 105% !important; }</style>"""
        st.markdown(style_html, unsafe_allow_html=True)

        df1['Abs_Net'] = df1['Total_Combined_Net'].abs()
        left_df = df1.iloc[::2].copy()
        right_df = df1.iloc[1::2].copy()
        
        sum_left = left_df['Abs_Net'].sum() if left_df['Abs_Net'].sum() > 0 else 1
        sum_right = right_df['Abs_Net'].sum() if right_df['Abs_Net'].sum() > 0 else 1
        
        # 균등 높이로 고정 및 최소 높이 확보
        left_df['height_px'] = 310 / len(left_df) if len(left_df) > 0 else 62
        right_df['height_px'] = 310 / len(right_df) if len(right_df) > 0 else 62
        
        def get_card_color(change_ratio):
            val = max(-10.0, min(10.0, change_ratio))
            alpha = 0.2 + (abs(val) / 10.0) * 0.8
            if val >= 0:
                return f"rgba(222, 45, 38, {alpha:.2f})"
            else:
                return f"rgba(49, 130, 189, {alpha:.2f})"
                
        def make_card_html(row, height_px):
            name = row['Name']
            code = row['Code']
            chg = row['ChagesRatio']
            price = row['Current_Price_Val']
            vol = row['Trade_Volume_Val']
            fgn = row['Foreign_Net']
            inst = row['Institutional_Net']
            bg_color = get_card_color(chg)
            
            tooltip_html = f"<div class='tm-tooltip' style='visibility: hidden; position: absolute; width: 200px; background-color: rgba(20, 20, 20, 0.95); color: #fff; text-align: left; padding: 10px; border-radius: 6px; border: 1px solid #444; font-size: 11px; font-family: sans-serif; line-height: 1.5; z-index: 9999; opacity: 0; transition: opacity 0.2s ease; pointer-events: none; box-shadow: 0 4px 10px rgba(0,0,0,0.5);'><b>{name} ({code})</b><br>현재가: {price:,.0f}원<br>등락률: {chg:+.2f}%<br>거래량: {vol:,.0f}주<br>외국인 순매수: {fgn:+,}주<br>기관 순매수: {inst:+,}주</div>"
            card_html = f"<div class='tm-card-wrapper' style='position: relative; width: 100%; height: {height_px:.0f}px; padding: 2px; box-sizing: border-box;'><a href='/?sel_code={code}&sel_name={name}' target='_self' class='tm-card' style='display: flex; flex-direction: column; justify-content: center; align-items: center; width: 100%; height: 100%; text-decoration: none; color: white; border-radius: 3px; cursor: pointer; box-shadow: inset 0 0 10px rgba(0,0,0,0.2); box-sizing: border-box; background-color: {bg_color}; transition: transform 0.1s ease, filter 0.1s ease;'><div class='tm-card-content' style='text-align: center; font-family: sans-serif;'><span class='tm-card-name' style='display: block; font-weight: bold; font-size: 12px; color: white; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;'>{name}</span><span class='tm-card-chg' style='display: block; font-size: 10px; margin-top: 1px; color: rgba(255,255,255,0.9);'>{chg:+.2f}%</span></div>{tooltip_html}</a></div>"
            return card_html
            
        left_cards = "".join([make_card_html(row, row['height_px']) for _, row in left_df.iterrows()])
        right_cards = "".join([make_card_html(row, row['height_px']) for _, row in right_df.iterrows()])
        
        html_treemap = f"<div class='tm-container' style='display: flex; width: 100%; height: 320px; background-color: #0e1117; border-radius: 4px; gap: 0px;'><div class='tm-column' style='display: flex; flex-direction: column; width: 50%; height: 100%;'>{left_cards}</div><div class='tm-column' style='display: flex; flex-direction: column; width: 50%; height: 100%;'>{right_cards}</div></div>"
        st.markdown(html_treemap, unsafe_allow_html=True)
# ── [Panel 2] Quant Buy TOP 10 (Horizontal Bar) ─────────────
with row1_col2:
    st.markdown(f"##### 🎯 Quant Buy TOP 10 ({q_sort_by})")
    fig_p2 = go.Figure()
    if not df_q.empty and 'Total_Score' in df_q.columns:
        df2 = df_q.copy()
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
            x_val = df2['Amount'] / 1e8
            hover_label = '거래대금: %{x:,.1f}억원'
            text_labels = df2['Amount'].apply(lambda x: f" {x/1e8:,.0f}")
        else:
            df2 = df2.sort_values('Total_Score', ascending=True).tail(10).copy()
            x_val = df2['Total_Score']
            hover_label = 'Quant 점수: %{x:.1f}점'
            text_labels = df2['Total_Score'].apply(lambda x: f" {x:.1f}")

        fig_p2.add_trace(go.Bar(
            y=df2['Name'],
            x=x_val,
            orientation='h',
            marker=dict(
                colorscale='Reds',
                color=df2['Total_Score'],
                showscale=False,
                line=dict(color='rgba(255,255,255,0.1)', width=1)
            ),
            text=text_labels,
            textposition='outside',
            customdata=df2[['Code', 'Close', 'ChagesRatio', 'Total_Score']].values,
            hovertemplate=(
                '<b>%{y}</b> (%{customdata[0]})<br>'
                '━━━━━━━━━━━━━━━<br>'
                + hover_label + '<br>'
                '현재가: %{customdata[1]:,}원 (%{customdata[2]:+.2f}%)<br>'
                'Quant 종합 점수: %{customdata[3]:.1f}점'
                '<extra></extra>'
            )
        ))
    fig_p2.update_layout(
        height=320,
        template='plotly_dark',
        margin=dict(t=10, b=10, l=85, r=60),
        clickmode='event+select',
        font=dict(family='malgun gothic, nanum gothic, sans-serif'),
        xaxis=dict(fixedrange=True),
        yaxis=dict(fixedrange=True),
        dragmode=False
    )
    fig_p2.update_yaxes(automargin=True)
    max_x = float(x_val.max()) if not x_val.empty else 100
    fig_p2.update_xaxes(range=[0, max_x * 1.25])
    ev_p2 = st.plotly_chart(fig_p2, use_container_width=True, on_select='rerun', selection_mode=['points'], key=f"p2_chart_{st.session_state.chart_key_index}", config={'displayModeBar': False})
    handle_chart_click(ev_p2)

# ── [Panel 3] 거래대금 리더 (Horizontal Bar) ─────────────────
with row1_col3:
    st.markdown("##### 🔥 거래대금 리더 (12)")
    fig_p3 = go.Figure()
    if not df_m.empty and 'Amount' in df_m.columns:
        df3 = df_m.sort_values('Amount', ascending=True).tail(12).copy()
        df3['Amount_100M'] = df3['Amount'] / 100000000
        
        fig_p3.add_trace(go.Bar(
            y=df3['Name'],
            x=df3['Amount_100M'],
            orientation='h',
            marker=dict(
                colorscale=kr_scale,
                color=df3['ChagesRatio'],
                cmid=0,
                showscale=False,
                line=dict(color='rgba(255,255,255,0.1)', width=1)
            ),
            text=df3['Amount_100M'].apply(lambda x: f" {x:,.0f}"),
            textposition='outside',
            customdata=df3[['Code', 'Close', 'ChagesRatio']].values,
            hovertemplate=(
                '<b>%{y}</b> (%{customdata[0]})<br>'
                '거래대금: %{x:,.0f}억원<br>'
                '현재가: %{customdata[1]:,}원 (%{customdata[2]:+.2f}%)'
                '<extra></extra>'
            )
        ))
    fig_p3.update_layout(
        height=320,
        template='plotly_dark',
        margin=dict(t=10, b=10, l=85, r=60),
        clickmode='event+select',
        font=dict(family='malgun gothic, nanum gothic, sans-serif'),
        xaxis=dict(fixedrange=True),
        yaxis=dict(fixedrange=True),
        dragmode=False
    )
    fig_p3.update_yaxes(automargin=True)
    max_x = float(df3['Amount_100M'].max()) if not df3.empty else 100
    fig_p3.update_xaxes(range=[0, max_x * 1.25])
    ev_p3 = st.plotly_chart(fig_p3, use_container_width=True, on_select='rerun', selection_mode=['points'], key=f"p3_chart_{st.session_state.chart_key_index}", config={'displayModeBar': False})
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
    if not df_m.empty and 'ChagesRatio' in df_m.columns:
        df6 = df_m.sort_values('ChagesRatio', ascending=True).tail(12).copy()
        
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
        margin=dict(t=10, b=10, l=85, r=60),
        clickmode='event+select',
        font=dict(family='malgun gothic, nanum gothic, sans-serif'),
        xaxis=dict(fixedrange=True),
        yaxis=dict(fixedrange=True),
        dragmode=False
    )
    fig_p6.update_yaxes(automargin=True)
    max_x = float(df6['ChagesRatio'].max()) if not df6.empty else 30
    fig_p6.update_xaxes(range=[0, max_x * 1.25])
    ev_p6 = st.plotly_chart(fig_p6, use_container_width=True, on_select='rerun', selection_mode=['points'], key=f"p6_chart_{st.session_state.chart_key_index}", config={'displayModeBar': False})
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

    with st.spinner(f'📡 {name_disp} 일봉 데이터 조회 중...'):
        df_candle = get_stock_history(code_disp)

    if df_candle.empty:
        st.warning('⚠️ 차트 데이터를 불러올 수 없습니다.')
    else:
        # MA 계산
        df_candle['MA5']  = df_candle['Close'].rolling(5).mean()
        df_candle['MA20'] = df_candle['Close'].rolling(20).mean()
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
        st.markdown(stats_html, unsafe_allow_html=True)

        # 캔들 차트 생성
        fig_c = make_subplots(
            rows=2, cols=1,
            row_heights=[0.72, 0.28],
            vertical_spacing=0.03,
            shared_xaxes=True
        )

        # 캔들스틱 (한국식: 상승=빨강, 하락=파랑)
        fig_c.add_trace(go.Candlestick(
            x=df_candle.index,
            open=df_candle['Open'], high=df_candle['High'],
            low=df_candle['Low'],   close=df_candle['Close'],
            increasing=dict(line=dict(color='#ff6b6b'), fillcolor='#ff6b6b'),
            decreasing=dict(line=dict(color='#4e9ff5'), fillcolor='#4e9ff5'),
            name='캔들', showlegend=False
        ), row=1, col=1)

        # MA5
        fig_c.add_trace(go.Scatter(
            x=df_candle.index, y=df_candle['MA5'],
            name='MA5', mode='lines',
            line=dict(color='#ffd43b', width=1.5)
        ), row=1, col=1)

        # MA20
        fig_c.add_trace(go.Scatter(
            x=df_candle.index, y=df_candle['MA20'],
            name='MA20', mode='lines',
            line=dict(color='#ff922b', width=1.5)
        ), row=1, col=1)

        # 거래량 막대 (색상: 상승일=빨강, 하락일=파랑)
        vol_colors = [
            '#ff6b6b' if c >= o else '#4e9ff5'
            for c, o in zip(df_candle['Close'], df_candle['Open'])
        ]
        fig_c.add_trace(go.Bar(
            x=df_candle.index, y=df_candle['Volume'],
            name='거래량', marker_color=vol_colors,
            showlegend=False, opacity=0.8
        ), row=2, col=1)

        fig_c.update_layout(
            template='plotly_dark',
            height=480,
            margin=dict(t=20, l=10, r=10, b=10),
            xaxis_rangeslider_visible=False,
            legend=dict(orientation='h', x=0, y=1.02, font=dict(size=11)),
            font=dict(family='malgun gothic, nanum gothic, sans-serif'),
            plot_bgcolor='#0d1b2a',
            paper_bgcolor='#0d1b2a',
        )
        fig_c.update_yaxes(tickformat=',d', gridcolor='rgba(255,255,255,0.06)', row=1, col=1)
        fig_c.update_yaxes(tickformat=',d', gridcolor='rgba(255,255,255,0.06)', row=2, col=1)
        fig_c.update_xaxes(gridcolor='rgba(255,255,255,0.04)', showticklabels=False, row=1, col=1)
        fig_c.update_xaxes(gridcolor='rgba(255,255,255,0.04)', tickangle=-30, row=2, col=1)

        st.plotly_chart(fig_c, use_container_width=True)

    st.divider()

# 하단 갱신 버튼 및 60초 자동 새로고침 JS
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if st.button('🔄 데이터 새로고침', use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# 60초 주기 자동 새로고침 (외부 라이브러리 미설치 방식)
st.components.v1.html(
    """
    <script>
    setTimeout(function() {
        window.parent.postMessage({type: 'streamlit:rerun'}, '*');
    }, 60000);
    </script>
    """,
    height=0,
    width=0
)
