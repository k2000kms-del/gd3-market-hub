import threading
import os
import sys
import json
import time
import re
import base64
import urllib.request
import requests
import numpy as np
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import live_logger

# ── 전역 상수 정의 ───────────────────────────────────────────────
DATA_FILES = [
    'df_full_market.csv',
    'df_high_density.csv',
    'df_quant_final.csv',
    'df_market_summary.csv',
    'df_supply_intraday.csv',
]
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/k2000kms-del/gd3-market-hub/main/data"

EXCLUDE_KEYWORDS = [
    'KODEX', 'TIGER', 'ACE', 'KBSTAR', 'SOL', 'ARIRANG', 'HANARO', 'KOSEF', 'PLUS',
    'TIMEFOLIO', '스팩', 'ETN', '선물', '인버스', '레버리지', '2X', '3X', 'RISE', 'BNK',
    '대신34호스팩', '하나32호스팩', '신한제13호스팩', 'KB제28호스팩', '유진스팩10호'
]

# ── 수량 및 화폐 포맷 헬퍼 ───────────────────────────────────────
def fmt_shares_korean(shares):
    if shares is None or pd.isna(shares):
        return "-"
    try:
        s = float(shares)
        if abs(s) >= 10000:
            return f"{s / 10000:+,.1f}만 주"
        return f"{s:+,.0f}주"
    except:
        return str(shares)

def fmt_shares_html(shares):
    if shares is None or pd.isna(shares):
        return '<span style="color:#888;">-</span>'
    try:
        s = float(shares)
        txt = fmt_shares_korean(s)
        if s > 0:
            return f'<span style="color:#ff6b6b; font-weight:600;">{txt}</span>'
        elif s < 0:
            return f'<span style="color:#4dabf7; font-weight:600;">{txt}</span>'
        return f'<span style="color:#888;">{txt}</span>'
    except:
        return str(shares)

def clean_market_condition_korean(raw_cond_str: str) -> str:
    """시장 판단 문자열을 한글 표준 국면명으로 정제"""
    if not raw_cond_str:
        return "중립"
    s = str(raw_cond_str).strip()
    if "강세" in s or "Bull" in s:
        return "강세"
    elif "약세" in s or "Bear" in s:
        return "약세"
    elif "과열" in s:
        return "과열"
    elif "침체" in s:
        return "침체"
    return "중립"

def _get_josa(word: str, josa_type: str = '을를') -> str:
    if not word:
        return ''
    last_char = word[-1]
    if '가' <= last_char <= '힣':
        has_batchim = (ord(last_char) - ord('가')) % 28 > 0
        if josa_type == '을를':
            return '을' if has_batchim else '를'
        elif josa_type == '이가':
            return '이' if has_batchim else '가'
        elif josa_type == '은는':
            return '은' if has_batchim else '는'
        elif josa_type == '와과':
            return '과' if has_batchim else '와'
    return ''

@st.cache_data(ttl=90)
def fetch_naver_realtime_supply():
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        url = "https://m.stock.naver.com/api/home/market/trend"
        r = requests.get(url, headers=headers, timeout=2.0)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"DEBUG: fetch_naver_realtime_supply failed: {e}")
    return {}

@st.cache_data(ttl=30)
def fetch_naver_realtime_indices():
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        url = "https://polling.finance.naver.com/api/realtime/domestic/index/KOSPI,KOSDAQ"
        r = requests.get(url, headers=headers, timeout=2.0)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"DEBUG: fetch_naver_realtime_indices failed: {e}")
    return {}

@st.cache_data(ttl=90)
def fetch_stock_realtime_investors(code_list):
    res = {}
    if not code_list:
        return res
    headers = {"User-Agent": "Mozilla/5.0"}

    def _fetch_one(code):
        try:
            url = f"https://m.stock.naver.com/api/stock/{code}/trend?pageSize=1"
            r = requests.get(url, headers=headers, timeout=1.5)
            if r.status_code == 200:
                data = r.json()
                if data and len(data) > 0:
                    item = data[0]
                    fgn = str(item.get("foreignerPureBuyQuant", "0")).replace(',', '').replace('+', '')
                    org = str(item.get("organPureBuyQuant", "0")).replace(',', '').replace('+', '')
                    return code, {
                        "foreign": int(fgn) if fgn.replace('-', '').isdigit() else 0,
                        "institutional": int(org) if org.replace('-', '').isdigit() else 0
                    }
        except Exception:
            pass
        return code, None

    with ThreadPoolExecutor(max_workers=min(len(code_list), 8)) as executor:
        for code, data in executor.map(_fetch_one, code_list):
            if data is not None:
                res[code] = data
    return res

@st.cache_data(ttl=60)
def fetch_stock_supply_trend(code: str, days: int = 10):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        url = f"https://m.stock.naver.com/api/stock/{code}/trend?pageSize={days}"
        r = requests.get(url, headers=headers, timeout=3)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and len(data) > 0:
                fgn_sum = 0
                org_sum = 0
                ind_sum = 0
                daily_list = []
                for item in data[:days]:
                    fgn_str = str(item.get("foreignerPureBuyQuant", "0")).replace(',', '').replace('+', '')
                    org_str = str(item.get("organPureBuyQuant", "0")).replace(',', '').replace('+', '')
                    ind_str = str(item.get("individualPureBuyQuant", "0")).replace(',', '').replace('+', '')
                    
                    fgn = int(fgn_str) if fgn_str.replace('-', '').isdigit() else 0
                    org = int(org_str) if org_str.replace('-', '').isdigit() else 0
                    ind = int(ind_str) if ind_str.replace('-', '').isdigit() else 0
                    
                    fgn_sum += fgn
                    org_sum += org
                    ind_sum += ind
                    
                    daily_list.append({
                        "date": item.get("bizdate", "")[-4:],
                        "foreign": fgn,
                        "institutional": org,
                        "individual": ind,
                        "close": int(str(item.get("closePrice", "0")).replace(',', ''))
                    })
                return {
                    "success": True,
                    "cumulative": {"foreigner": fgn_sum, "organ": org_sum, "individual": ind_sum},
                    "daily": daily_list
                }
    except Exception as e:
        print(f"DEBUG: fetch_stock_supply_trend failed: {e}")
    return {"success": False, "cumulative": {}, "daily": []}

@st.cache_data(ttl=120)
def fetch_stock_recent_news(code: str, count: int = 3):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        url = f"https://m.stock.naver.com/api/news/item/{code}?pageSize={count}"
        r = requests.get(url, headers=headers, timeout=2.5)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return [{"title": n.get("tit", ""), "date": n.get("dt", "")[:8], "office": n.get("onm", "")} for n in data[:count]]
    except Exception as e:
        print(f"DEBUG: fetch_stock_recent_news failed: {e}")
    return []

def get_local_fallback_commentary(code, name, t_score_adj, s_score, change, market_cond,
                                  current_price=None, stop_loss_price=None, recent_high_price=None,
                                  rsi=None, macd=None, macd_signal=None, bb_upper=None, bb_middle=None, bb_lower=None,
                                  avg_price=None, supply_trend=None, recent_news=None):
    ret_str = ""
    if avg_price and avg_price > 0 and current_price:
        ret = ((current_price - avg_price) / avg_price) * 100
        ret_str = f" (보유 평단가 대비 {ret:+.1f}% 수익권)"
    
    summary = f"1. <strong>현재 상황 요약</strong>: {name}은(는) 당일 등락률 {change:+.2f}%를 기록 중이며, 퀀트 매수 점수 {t_score_adj:.1f}점, 매도 점수 {s_score:.1f}점으로 시장 국면은 '{market_cond}' 상태입니다{ret_str}.<br>"
    
    tech = "2. <strong>기술적 차트 분석</strong>: "
    tech_items = []
    if rsi is not None:
        tech_items.append(f"RSI는 {rsi:.1f}로 " + ("과매수 구간에 근접했습니다." if rsi > 70 else "과매도 구간으로 반등 기대가 있습니다." if rsi < 30 else "안정적인 중립 영역에 위치합니다."))
    if macd is not None and macd_signal is not None:
        tech_items.append(f"MACD({macd:.1f})가 Signal({macd_signal:.1f}) 대비 " + ("골든크로스를 유지 중입니다." if macd > macd_signal else "데드크로스 경계 국면입니다."))
    if bb_upper is not None and current_price is not None:
        tech_items.append(f"볼린저 상한선({bb_upper:,.0f}원) 및 중심선({bb_middle:,.0f}원) 대비 지지/저항을 시험 중입니다.")
    tech += " ".join(tech_items) + "<br>"
    
    strat = "3. <strong>매매 대응 전략</strong>: "
    if t_score_adj >= 70:
        strat += f"강력한 매수 모멘텀이 포착되었습니다. "
        if recent_high_price:
            strat += f"1차 목표가는 {recent_high_price:,.0f}원이며, "
        if stop_loss_price:
            strat += f"손절선은 {stop_loss_price:,.0f}원으로 설정하여 분할 접근을 권장합니다."
    elif s_score >= 60:
        strat += f"매도 압력이 높아지고 있습니다. "
        if stop_loss_price:
            strat += f"손절/수익보전 기준선({stop_loss_price:,.0f}원) 이탈 시 비중 축소 대응이 유효합니다."
    else:
        strat += f"단기 관망 및 기존 포지션 홀딩을 권장하며, 명확한 수급 돌파 확인 후 대응하세요."
        
    return f"{summary}\n{tech}\n{strat}"

# ── 포트폴리오 로드 및 백업 함수군 ───────────────────────────────
@st.cache_data(ttl=60)
def fetch_remote_portfolio():
    gh_token = ""
    try:
        if hasattr(st, "secrets"):
            gh_token = st.secrets.get("GITHUB_TOKEN", "")
        if not gh_token:
            gh_token = os.environ.get("GITHUB_TOKEN", "")
    except:
        pass
    if gh_token:
        url = "https://api.github.com/repos/k2000kms-del/gd3-market-hub/contents/data/my_portfolio.json"
        headers = {"Authorization": f"token {gh_token}", "Accept": "application/vnd.github.v3+json"}
        try:
            res = requests.get(url, headers=headers, timeout=3)
            if res.status_code == 200:
                content_b64 = res.json().get('content', '')
                if content_b64:
                    content_str = base64.b64decode(content_b64).decode('utf-8')
                    return json.loads(content_str)
        except Exception as e:
            print(f"DEBUG: fetch_remote_portfolio failed: {e}")
    return None

def _backup_portfolio_daily(portfolio):
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

def _load_portfolio_raw(force_remote: bool = False):
    return load_portfolio(force_remote)

def _sync_and_load_csv_raw(fname):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    local_path = os.path.join(base_dir, 'data', fname)
    if os.path.exists(local_path):
        try:
            return pd.read_csv(local_path)
        except:
            pass
    return pd.DataFrame()

def load_portfolio(force_remote: bool = False):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    port_path = os.path.join(base_dir, 'data', 'my_portfolio.json')

    sb = get_supabase()
    if sb:
        try:
            res = sb.table("portfolio").select("*").execute()
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
                    except:
                        pass
                    return port_dict
        except Exception:
            pass

    if not force_remote and 'session_portfolio' in st.session_state and st.session_state['session_portfolio']:
        return st.session_state['session_portfolio']

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
            except:
                pass

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

    remote_data = fetch_remote_portfolio()
    if remote_data is not None:
        try:
            os.makedirs(os.path.dirname(port_path), exist_ok=True)
            with open(port_path, 'w', encoding='utf-8') as f:
                json.dump(remote_data, f, ensure_ascii=False, indent=2)
            _backup_portfolio_daily(remote_data)
            st.session_state['session_portfolio'] = remote_data
        except:
            pass
        return remote_data

    return {}



