# -*- coding: utf-8 -*-
"""
GD 3.0 Market Hub - 데이터 수집기 (GitHub Actions 전용)
- 한국 주식시장 개장 시간(09:00~15:30 KST)에 GitHub Actions로 자동 실행
- KIS API + FinanceDataReader로 시장 데이터 수집
- 수집된 CSV를 레포지토리 data/ 폴더에 저장 (GitHub Actions가 자동 커밋)
- 모든 민감 정보는 환경변수(GitHub Secrets)에서 읽음
"""

import os
import json
import requests
import pandas as pd
import numpy as np
import time
import FinanceDataReader as fdr
from datetime import datetime, timedelta

# ── KIS API 설정 (환경변수에서 읽기) ────────────────────────────
APP_KEY    = os.environ.get('KIS_APP_KEY', '')
APP_SECRET = os.environ.get('KIS_APP_SECRET', '')
URL_BASE   = 'https://openapi.koreainvestment.com:9443'

# ── 로컬 저장 경로 (레포지토리 data/ 폴더) ──────────────────────
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')


# ── KIS API 헬퍼 ────────────────────────────────────────────────
def get_access_token():
    """KIS API 액세스 토큰 발급"""
    res = requests.post(
        f'{URL_BASE}/oauth2/tokenP',
        headers={'content-type': 'application/json'},
        data=json.dumps({
            'grant_type': 'client_credentials',
            'appkey': APP_KEY,
            'appsecret': APP_SECRET
        })
    )
    return res.json().get('access_token')


def is_market_open():
    """한국 주식시장 개장 여부 확인 (09:00~15:30 평일)"""
    now = datetime.now()
    if now.weekday() >= 5:  # 토/일
        return False
    h, m = now.hour, now.minute
    return (9, 0) <= (h, m) <= (15, 30)


def fetch_stock_supply(token, stock_code):
    """KIS API: 종목별 외국인/기관 순매수 조회"""
    try:
        headers = {
            'Content-Type': 'application/json',
            'authorization': f'Bearer {token}',
            'appkey': APP_KEY,
            'appsecret': APP_SECRET,
            'tr_id': 'FHKST01010900',
        }
        params = {
            'FID_COND_MRKT_DIV_CODE': 'J',
            'FID_INPUT_ISCD': stock_code,
        }
        res = requests.get(
            f'{URL_BASE}/uapi/domestic-stock/v1/quotations/inquire-investor',
            headers=headers, params=params
        )
        res_json = res.json()
        output = res_json.get('output', [])
        
        # output이 리스트 형식인 경우 첫 번째 아이템(최신 영업일) 파싱
        if isinstance(output, list) and len(output) > 0:
            target_data = output[0]
        elif isinstance(output, dict):
            target_data = output
        else:
            target_data = {}

        def _safe_int(val):
            try:
                if val is None:
                    return 0
                val_str = str(val).strip()
                if not val_str or val_str == 'None':
                    return 0
                return int(val_str)
            except Exception:
                return 0

        return {
            'Foreign_Net':       _safe_int(target_data.get('frgn_ntby_qty', 0)),
            'Institutional_Net': _safe_int(target_data.get('orgn_ntby_qty', 0)),
            'Program_Net':       _safe_int(target_data.get('pgtr_ntby_qty', 0)),
        }
    except Exception as e:
        print(f"  ⚠️ fetch_stock_supply({stock_code}) 실패: {e}")
        return {'Foreign_Net': 0, 'Institutional_Net': 0, 'Program_Net': 0}


def fetch_stock_sector(token, stock_code):
    """KIS API: 종목의 HTS 업종명 조회 (bstp_kor_isnm)"""
    try:
        headers = {
            'Content-Type': 'application/json',
            'authorization': f'Bearer {token}',
            'appkey': APP_KEY,
            'appsecret': APP_SECRET,
            'tr_id': 'FHKST01010100',
        }
        params = {
            'FID_COND_MRKT_DIV_CODE': 'J',
            'FID_INPUT_ISCD': stock_code,
        }
        res = requests.get(
            f'{URL_BASE}/uapi/domestic-stock/v1/quotations/inquire-price',
            headers=headers, params=params
        )
        data = res.json().get('output', {})
        return data.get('bstp_kor_isnm', '').strip()
    except Exception:
        return ''


def fetch_market_index(token, market_code='0001'):
    """KIS API: 코스피/코스닥 지수 조회"""
    try:
        headers = {
            'Content-Type': 'application/json',
            'authorization': f'Bearer {token}',
            'appkey': APP_KEY,
            'appsecret': APP_SECRET,
            'tr_id': 'FHPUP02100000',
        }
        params = {
            'FID_COND_MRKT_DIV_CODE': 'U',
            'FID_INPUT_ISCD': market_code,
        }
        res = requests.get(
            f'{URL_BASE}/uapi/domestic-stock/v1/quotations/inquire-index-price',
            headers=headers, params=params
        )
        return res.json().get('output', {})
    except Exception:
        return {}


def fetch_market_investor(token, market_div='J'):
    """KIS API: 시장별 투자자 순매수 조회 (억원 단위)"""
    try:
        headers = {
            'Content-Type': 'application/json',
            'authorization': f'Bearer {token}',
            'appkey': APP_KEY,
            'appsecret': APP_SECRET,
            'tr_id': 'FHPTJ04400000',
        }
        params = {
            'FID_COND_MRKT_DIV_CODE': market_div,
            'FID_INPUT_DATE_1': (datetime.now() - timedelta(days=max(0, datetime.now().weekday() - 4))).strftime('%Y%m%d'),
        }
        res = requests.get(
            f'{URL_BASE}/uapi/domestic-stock/v1/quotations/inquire-investor',
            headers=headers, params=params
        )
        return res.json().get('output', [])
    except Exception:
        return []


# ── 로컬 CSV 저장 ────────────────────────────────────────────────
def save_df_to_local(df, filename):
    """DataFrame을 레포지토리 data/ 폴더에 CSV로 저장"""
    os.makedirs(DATA_DIR, exist_ok=True)
    filepath = os.path.join(DATA_DIR, filename)
    df.to_csv(filepath, index=False, encoding='utf-8-sig')
    print(f'  ✅ {filename} → data/ 저장 완료 ({len(df)}행)')


# ── 데이터 수집 함수들 ───────────────────────────────────────────
def collect_full_market():
    """FinanceDataReader: 전체 시장 데이터 수집"""
    print('📊 전체 시장 데이터 수집 중...')
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        df_ks = fdr.StockListing('KOSPI')
        df_kq = fdr.StockListing('KOSDAQ')
        df_all = pd.concat([df_ks, df_kq], ignore_index=True)

        # ── [종목 필터링] 부실/특수 종목 제외 ──
        if 'Name' in df_all.columns:
            # 스팩, ETN, ETF, 우선주(우, 우B 등), 리츠, 인프라 등 제외
            junk_patterns = '스팩|SPAC|ETN|ETF|제[0-9]+호|우$|우[A-Z]$|리츠|인프라'
            df_all = df_all[~df_all['Name'].str.contains(junk_patterns, regex=True, na=False)]
        
        if 'Volume' in df_all.columns:
            # 거래량 0인 종목 제외 (거래정지 등)
            df_all = df_all[df_all['Volume'] > 0]

        # [퀄리티 필터] 시가총액 500억원 미만 극소형주 제외
        # 선행 매수 목적상 재무 건전성이 일정 수준 이상인 종목만 대상으로 함
        if 'Marcap' in df_all.columns:
            df_all = df_all[pd.to_numeric(df_all['Marcap'], errors='coerce').fillna(0) >= 50_000_000_000]

        df_all = df_all.reset_index(drop=True)

        # 컬럼 정리
        col_map = {
            'Symbol': 'Code', 'Name': 'Name', 'Market': 'Market',
            'Close': 'Close', 'ChagesRatio': 'ChagesRatio',
            'Volume': 'Volume', 'Amount': 'Amount', 'Marcap': 'Marcap'
        }
        df_all = df_all.rename(columns={k: v for k, v in col_map.items() if k in df_all.columns})
        for col in ['Close', 'ChagesRatio', 'Volume', 'Amount', 'Marcap']:
            if col in df_all.columns:
                df_all[col] = pd.to_numeric(df_all[col], errors='coerce').fillna(0)

        print(f'  → {len(df_all)}개 종목')
        return df_all
    except Exception as e:
        print(f'  ❌ 오류: {e}')
        return pd.DataFrame()


def collect_high_density(token, df_full):
    """KIS API: 수급 상위 종목 데이터 수집

    [목적] 선행 매수 타이밍 포착을 위한 후보군 확대 전략:
    - Pool A: 거래대금 절대 상위 50개 (시장 주도 종목)
    - Pool B: 시가총액 대비 거래대금 회전율 상위 20개 (아직 주목받지 않은 선행 이동 종목)
    두 풀을 합산(중복 제거)하여 최대 70개 종목을 수급 분석 대상으로 삼음.
    """
    print('📡 수급 상위 종목 데이터 수집 중...')
    if df_full.empty:
        return pd.DataFrame()

    # ── Pool A: 거래대금 절대 상위 50개 (시장 주도·핫 종목) ──
    pool_a = df_full.nlargest(50, 'Amount') if 'Amount' in df_full.columns else df_full.head(50)

    # ── Pool B: 시가총액 대비 거래대금 회전율 상위 20개 (선행 포착) ──
    # 아직 거래대금 절대규모는 크지 않지만 시총 대비 거래가 활발해지는 종목을 조기에 포착
    pool_b = pd.DataFrame()
    try:
        df_remaining = df_full[~df_full.index.isin(pool_a.index)].copy()
        if 'Marcap' in df_remaining.columns and 'Amount' in df_remaining.columns:
            df_remaining['Marcap_num'] = pd.to_numeric(df_remaining['Marcap'], errors='coerce').fillna(0)
            df_remaining['Amount_num'] = pd.to_numeric(df_remaining['Amount'], errors='coerce').fillna(0)
            # 최소 거래대금 10억 이상이고 시총이 있는 종목만 대상
            df_remaining = df_remaining[
                (df_remaining['Marcap_num'] > 0) & (df_remaining['Amount_num'] >= 1_000_000_000)
            ]
            df_remaining['TurnoverRatio'] = df_remaining['Amount_num'] / df_remaining['Marcap_num']
            pool_b = df_remaining.nlargest(20, 'TurnoverRatio')
    except Exception as e:
        print(f'  ⚠️ Pool B 선행 포착 조회 실패: {e}')

    # ── 두 풀 합산 및 중복 제거 ──
    top_stocks = pd.concat([pool_a, pool_b]).drop_duplicates(subset=['Code']).reset_index(drop=True)
    print(f'  → Pool A: {len(pool_a)}개, Pool B: {len(pool_b)}개, 합산: {len(top_stocks)}개 종목 대상')

    rows = []
    for _, row in top_stocks.iterrows():
        code = str(row.get('Code', '')).zfill(6)
        supply = fetch_stock_supply(token, code)

        rows.append({
            'Code': code,
            'Name': row.get('Name', ''),
            'Market': row.get('Market', ''),
            'Close': row.get('Close', 0),
            'ChagesRatio': row.get('ChagesRatio', 0),
            'Volume': row.get('Volume', 0),
            'Amount': row.get('Amount', 0),
            'Marcap': row.get('Marcap', 0),
            'Foreign_Net':        supply['Foreign_Net'],
            'Institutional_Net':  supply['Institutional_Net'],
            'Program_Net':        supply['Program_Net'],
            'Total_Combined_Net': supply['Foreign_Net'] + supply['Institutional_Net'],
            'FDR_Sector':         row.get('Sector', ''),
            'FDR_Industry':       row.get('Industry', ''),
        })

    df = pd.DataFrame(rows)
    print(f'  → {len(df)}개 종목 수급 수집 완료')
    return df


# ── 섹터 분류 함수 ────────────────────────────────────────────────
def _classify_sector(code, name, fdr_sector="", fdr_industry=""):
    """종목 코드/이름/FDR 분류 기반 섹터 분류
    반환값: 섹터 문자열 (반도체, 자동차, 금융, 에너지, 항공운송, 바이오, 통신, 내수, 건설, 기타 공식 업종명)
    """
    # 주요 종목 코드 직접 매핑 (정확도 최우선)
    sector_by_code = {
        # 반도체
        '005930': '반도체', '000660': '반도체', '042700': '반도체',
        '240810': '반도체', '403870': '반도체', '090360': '반도체',
        '005290': '반도체', '357780': '반도체', '054730': '반도체',
        '104830': '반도체', '000990': '반도체', '336370': '반도체',
        # 자동차
        '005380': '자동차', '000270': '자동차', '012330': '자동차',
        '011210': '자동차', '161390': '자동차', '204320': '자동차',
        # 금융
        '055550': '금융', '105560': '금융', '086790': '금융',
        '316140': '금융', '032830': '금융', '000810': '금융',
        '138930': '금융', '139130': '금융',
        # 에너지/정유
        '096770': '에너지', '010950': '에너지', '078930': '에너지',
        '267250': '에너지',
        # 항공/운송
        '003490': '항공운송', '020560': '항공운송', '011200': '항공운송',
        '000120': '항공운송',
        # 바이오
        '207940': '바이오', '068270': '바이오', '000100': '바이오',
        '128940': '바이오', '326030': '바이오',
        # 통신
        '017670': '통신', '030200': '통신', '032640': '통신',
        # 건설
        '028260': '건설', '000720': '건설', '375500': '건설',
        '010140': '건설',
    }
    if code in sector_by_code:
        return sector_by_code[code]

    # 이름 및 FDR 분류 정보를 모두 고려한 통합 검색 텍스트 생성
    check_str = f"{fdr_sector} {fdr_industry} {name}".lower()

    if any(kw in check_str for kw in ['반도체', 'semiconductor', '웨이퍼', '파운드리', '식각', 'hbm', 'dram', 'nand', 'ic', '칩']):
        return '반도체'
    if any(kw in check_str for kw in ['자동차', '모터스', '모비스', '타이어', '부품', '완성차', 'automotive']):
        return '자동차'
    if any(kw in check_str for kw in ['금융', '은행', '증권', '보험', '캐피탈', '카드', '지주회사', 'financial', 'bank']):
        if '금융' in check_str or '은행' in check_str or '카드' in check_str or '투자' in check_str:
            return '금융'
    if any(kw in check_str for kw in ['에너지', '정유', '오일', '가스', '석유', '석탄', '발전', '전력', 'energy', 'oil']):
        return '에너지'
    if any(kw in check_str for kw in ['항공', '에어', '해운', '물류', '운송', '택배', 'shipping', 'transport']):
        return '항공운송'
    if any(kw in check_str for kw in ['바이오', '제약', '의약', '셀', '헬스', '테라퓨틱', '의료기기', 'bio', 'pharma']):
        return '바이오'
    if any(kw in check_str for kw in ['텔레콤', 'telecom', '통신']):
        return '통신'
    if any(kw in check_str for kw in ['건설', '물산', '이앤씨', '산업개발', '건축', '토목', 'construction']):
        return '건설'
    if any(kw in check_str for kw in ['식품', '유통', '마트', '백화점', '패션', '의류', '화장품', '소매', '식음료', 'cosmetic', 'retail']):
        return '내수'

    # 매크로 가중치 적용 9대 섹터에 속하지 않는 경우, '기타'로 뭉뚱그리지 않고 FDR 제공 업종명 또는 상세 산업명을 명시
    if fdr_sector:
        return fdr_sector
    if fdr_industry:
        ind = fdr_industry.split(',')[0].strip()
        return ind[:15]

    return '기타'


def collect_quant_final(token, df_hd, df_full):
    """Quant 점수 계산 - 선행 매수 타이밍 포착 전용 스크리너

    [목적]
    이 함수는 단순한 당일 강세 종목 선별이 아닌, 아직 시장의 본격적인 주목을 받기 전
    '선행 매수(Early Entry)' 타이밍을 포착하기 위한 종합 퀀트 스코어를 산출합니다.

    [점수 구성 - 총 100점 만점]
    - Score_Momentum (20점): 당일 등락률(10) + 5거래일 누적 추세(10) → 지속적 상승 흐름 확인
    - Score_Supply   (30점): 시가총액 대비 외인+기관 순매수 비율 → 스마트머니 선행 유입 포착
    - Score_Volume   (20점): 평균 대비 거래대금 급증률 (최소 10억 허들) → 관심도 증가 조기 감지
    - Score_MA       (15점): 이평선 배열 + 60일선 필터 + 이격도/수렴 보정 → 추세 구조 확인
    - Score_Candle   (15점): 당일 캔들 매수세 강도 → 진입 타이밍 최적화

    [매크로 보정 로직 - 3중 레이어 사이드카 대응 구조]
    ● Layer 1 - 방향성 패널티: 당일/3일/5일 누적 낙폭 기반 (기존 방식)
    ● Layer 2 - 변동성 레짐 패널티: 10일 일간 변동성(σ) 기반 (신규)
      → 사이드카처럼 매수/매도가 교대로 발생해 방향성이 상쇄될 때도 포착
      → σ > 2.0% (연환산 ~32%) 이면 고변동성 레짐으로 별도 패널티 부여
    ● Layer 3 - 장중 충격 감지: 당일 고저폭/전일종가 비율 기반 (신규)
      → 사이드카가 장중 발동되었으나 종가가 회복된 경우에도 감지
    - USD/KRW 환율 급등 감지: 환율 5일 +3% 이상 시 섹터별 차등 적용
    - 유가 급등 감지: 정유 에너지 섹터 수혜 / 항공·운송 패널티
    - 종목별 변동성 조정: 20일 연환산 변동성 30% 초과 시 점수 하향
    - 섹터 가중치: 매크로 국면에 따라 섹터별 점수 계수를 차등 적용
    - 이중 신호 중복 보정: 거래대금 급증과 가격 급등이 동시에 만점일 때 과대평가 방지
    """
    print('🎯 선행 매수 퀀트 스코어 계산 중...')
    if df_hd.empty:
        return pd.DataFrame()

    # ── 매크로 팩터 사전 수집 ────────────────────────────────────────
    # Layer 1: 방향성 패널티 (누적 낙폭)
    layer1_penalty = 1.0
    # Layer 2: 변동성 레짐 패널티 (방향성과 독립적 - 사이드카 상쇄 문제 해결)
    layer2_vol_regime = 1.0
    # Layer 3: 당일 장중 충격 감지 패널티
    layer3_intraday = 1.0

    market_condition = '중립'
    usd_krw_chg_5d = 0.0
    oil_surge = False

    try:
        start_mkt = (datetime.now() - timedelta(days=20)).strftime('%Y-%m-%d')
        df_ks  = fdr.DataReader('KS11', start_mkt)
        df_kq  = fdr.DataReader('KQ11', start_mkt)
        df_usd = fdr.DataReader('USD/KRW', start_mkt)

        def last_chg(df):
            return float(df['Change'].iloc[-1] * 100) if not df.empty and 'Change' in df.columns else 0

        def cumret(df, n):
            if len(df) < n + 1: return 0
            p0 = float(df['Close'].iloc[-(n+1)])
            p1 = float(df['Close'].iloc[-1])
            return ((p1 - p0) / p0 * 100) if p0 > 0 else 0

        ks_1d = last_chg(df_ks); kq_1d = last_chg(df_kq); avg_1d = (ks_1d + kq_1d) / 2
        avg_3d = (cumret(df_ks, 3) + cumret(df_kq, 3)) / 2
        avg_5d = (cumret(df_ks, 5) + cumret(df_kq, 5)) / 2

        # ── Layer 1: 방향성 패널티 (기존 로직 유지) ──────────────────
        if avg_1d <= -1.5 or avg_3d <= -3.0 or avg_5d <= -5.0:
            layer1_penalty = 0.80
            market_condition = f'하락위기 (1d:{avg_1d:.1f}% 3d:{avg_3d:.1f}% 5d:{avg_5d:.1f}%)'
        elif avg_1d <= -0.5 or avg_3d <= -1.5 or avg_5d <= -3.0:
            layer1_penalty = 0.90
            market_condition = f'약세 (1d:{avg_1d:.1f}% 3d:{avg_3d:.1f}% 5d:{avg_5d:.1f}%)'
        elif avg_1d >= 1.0 and avg_3d >= 2.0:
            market_condition = f'강세 (1d:{avg_1d:.1f}% 3d:{avg_3d:.1f}% 5d:{avg_5d:.1f}%)'
        else:
            market_condition = f'중립 (1d:{avg_1d:.1f}% 3d:{avg_3d:.1f}% 5d:{avg_5d:.1f}%)'

        # ── Layer 2: 변동성 레짐 패널티 (사이드카 상쇄 핵심 해결) ──────
        # 최근 10일 KOSPI 일간 수익률의 표준편차로 레짐 판별
        # → 매수/매도 사이드카가 교대로 발생해 방향성이 0%에 수렴해도
        #   변동성(σ)은 높게 유지되므로 이 레이어에서 독립적으로 포착
        if len(df_ks) >= 11:
            ks_10d_std = df_ks['Change'].tail(10).std() * 100  # 일간 σ (%)
            kq_10d_std = df_kq['Change'].tail(10).std() * 100
            avg_10d_std = (ks_10d_std + kq_10d_std) / 2

            if avg_10d_std >= 2.5:
                # 일간 σ ≥ 2.5% (연환산 ≈ 40%↑): 사이드카 빈발 극단 레짐
                layer2_vol_regime = 0.80
                market_condition += f' | ⚡극단변동성(σ={avg_10d_std:.1f}%)'
            elif avg_10d_std >= 2.0:
                # 일간 σ ≥ 2.0% (연환산 ≈ 32%↑): 고변동성 레짐
                layer2_vol_regime = 0.88
                market_condition += f' | 고변동성(σ={avg_10d_std:.1f}%)'
            elif avg_10d_std >= 1.5:
                # 일간 σ ≥ 1.5% (연환산 ≈ 24%↑): 주의 레짐
                layer2_vol_regime = 0.95
                market_condition += f' | 주의(σ={avg_10d_std:.1f}%)'

        # ── Layer 3: 당일 장중 충격 감지 ─────────────────────────────
        # 고가-저가 폭이 전일 종가 대비 4% 이상이면 장중 사이드카 수준의
        # 극단 변동이 발생했을 가능성이 높음 (종가 회복 여부와 무관하게 감지)
        if len(df_ks) >= 2:
            ks_h  = float(df_ks['High'].iloc[-1])
            ks_l  = float(df_ks['Low'].iloc[-1])
            ks_pc = float(df_ks['Close'].iloc[-2])
            intraday_range = ((ks_h - ks_l) / ks_pc * 100) if ks_pc > 0 else 0
            if intraday_range >= 5.0:
                # 코스피 당일 고저폭 5% 이상: 사이드카 발동 수준의 장중 충격
                layer3_intraday = 0.88
                market_condition += f' | 장중충격(범위{intraday_range:.1f}%)'
            elif intraday_range >= 3.5:
                layer3_intraday = 0.94

        # 최종 시장 패널티: 3개 레이어 곱셈 적용
        market_penalty = round(layer1_penalty * layer2_vol_regime * layer3_intraday, 3)

        # USD/KRW 5일 변동률 계산
        if not df_usd.empty and len(df_usd) >= 6:
            usd_p0 = float(df_usd['Close'].iloc[-6])
            usd_p1 = float(df_usd['Close'].iloc[-1])
            usd_krw_chg_5d = ((usd_p1 - usd_p0) / usd_p0 * 100) if usd_p0 > 0 else 0

        # 유가 급등 감지
        try:
            df_oil_proxy = fdr.DataReader('096770', start_mkt)
            if not df_oil_proxy.empty and len(df_oil_proxy) >= 6:
                oil_surge = cumret(df_oil_proxy, 5) >= 5.0
        except:
            oil_surge = False

        print(f'  📊 시장 국면: {market_condition}')
        print(f'  🔢 패널티: L1(방향)x{layer1_penalty} × L2(변동성)x{layer2_vol_regime} × L3(장중)x{layer3_intraday} = x{market_penalty}')
        print(f'  💱 USD/KRW 5일 변동: {usd_krw_chg_5d:+.2f}% | 유가급등: {oil_surge}')
    except Exception as e:
        print(f'  ⚠️ 매크로 데이터 조회 실패 (기본값 적용): {e}')

    # ── 섹터별 가중치 산출 (매크로 국면 연동) ────────────────────────
    def get_sector_multiplier(sector):
        """매크로 환경에 따른 섹터별 점수 가중치 반환"""
        m = 1.0  # 기본 중립

        # 환율 급등 국면 (USD/KRW +3% 이상): 수출주 수혜, 내수 패널티
        if usd_krw_chg_5d >= 3.0:
            if sector == '반도체':   m *= 1.10  # 달러 매출 → 환차익 수혜
            elif sector == '자동차': m *= 1.05  # 수출 수혜
            elif sector in ('내수', '바이오', '건설'): m *= 0.90  # 수입 원가↑

        # 환율 급락 국면 (USD/KRW -3% 이하): 반대 적용
        elif usd_krw_chg_5d <= -3.0:
            if sector == '반도체':   m *= 0.93
            elif sector in ('내수',): m *= 1.05

        # 유가 급등 국면: 정유 수혜 / 항공·운송 패널티
        if oil_surge:
            if sector == '에너지':     m *= 1.10
            elif sector == '항공운송': m *= 0.82  # 항공유 원가 급등
            elif sector == '반도체':   m *= 0.95  # 전력비 부담

        # 시장 위기 국면: 금융·방어주 상대 강세
        if market_penalty <= 0.80:
            if sector == '금융':       m *= 0.95  # 금리 불확실성
            if sector == '통신':       m *= 1.03  # 경기 방어

        return round(m, 3)

    print(f'  📊 시장 국면: {market_condition} (점수 계수: x{market_penalty})')

    rows = []
    # 60일선(MA60) 및 가격 이력을 충분히 조회하기 위해 시작 날짜 계산 (안전하게 100일 전으로 설정)
    start_date = (datetime.now() - timedelta(days=100)).strftime('%Y-%m-%d')

    for _, row in df_hd.iterrows():
        code = str(row.get('Code', '')).zfill(6)
        name = row.get('Name', '')
        
        # 이전 루프의 변수 오염을 막기 위한 초기화
        df_hist = None
        today_amount = 0

        # 1. 가격 모멘텀 점수 (최대 20점) [선행 매수 최적 구간 재설계]
        # 선행 매수 관점: +1~+3% 구간이 가장 이상적 진입 신호 (만점 10점)
        # +5% 이상 급등은 추격 위험이 있어 선형 감소 적용 (단, 6점 하한선 유지)
        # → 외국인/기관 주도 급등은 수급 점수로 이미 반영되므로 모멘텀만 과도하게 낮추지 않음
        change = float(row.get('ChagesRatio', 0))
        if 1.0 <= change < 3.0:
            score_day = 10.0                          # 이상적 선행 진입 구간 (소폭 상승)
        elif change >= 3.0:
            # +3%=9점, +5%=8점, +7%=7점 순으로 선형 감소, 최소 6점 하한 유지
            score_day = max(6.0, 10.0 - (change - 1.0) * 0.5)
        elif 0.0 <= change < 1.0:
            score_day = 8.0                           # 보합~미세 상승 (눌림목 진입 가능)
        elif -1.0 <= change < 0.0:
            score_day = 6.0                           # 소폭 조정 (건강한 눌림목 가능)
        elif -3.0 <= change < -1.0:
            score_day = 2.0                           # 하락세
        else:
            score_day = 0.0                           # 급락 (-3% 이하)
        # 5일 누적 모멘텀: FDR 조회 전이므로 일단 중립값 5점으로 초기화 (아래 FDR 블록에서 갱신)
        score_5d = 5.0
        score_momentum = score_day + score_5d  # FDR 블록에서 최종 갱신됨

        # 2. 수급 점수 (최대 30점) [개선: 로그 스케일 시총 보정으로 소형주 과대평가 방지]
        # 외인+기관 합산 순매수 금액(원화) 기준. KIS API 순매수량은 주식수이므로 종가를 곱해 금액 계산.
        close = float(row.get('Close', 0))
        foreign_qty = float(row.get('Foreign_Net', 0))
        inst_qty = float(row.get('Institutional_Net', 0))
        marcap = float(row.get('Marcap', 0))

        net_buy_amount = (foreign_qty + inst_qty) * close
        # [개선] 기존 고정 임계값(0.05%)은 소형주/대형주 체급 무관하게 동일해 소형주 과대평가 유발
        # 로그 스케일 시총 기반 동적 임계값: 대형주일수록 같은 점수에 더 많은 매수 필요
        # 시총 1천억(10^11) → threshold≈0.03%, 1조(10^12) → 0.05%, 10조(10^13) → 0.07%, 100조(10^14) → 0.10%
        if marcap > 0:
            net_ratio = (net_buy_amount / marcap) * 100
            log_adj = float(np.log10(max(marcap, 50_000_000_000)) - 11.0)  # 0 at 1천억
            threshold = max(0.03, min(0.12, 0.05 + log_adj * 0.02))       # 0.03~0.12% 범위
            score_supply = min(30, max(0, (net_ratio / threshold) * 15 + 15))
        else:
            # 시가총액 정보가 없을 경우 절대 금액 방식 폴백 (+5억원 이상 30점)
            score_supply = min(30, max(0, net_buy_amount / 100_000_000 * 3 + 15))

        # 기본 차트 점수 및 거래대금 증가율 초기화 (FDR 실패 대비)
        score_volume = 10.0
        score_ma = 7.5
        score_candle = 7.5

        # fdr을 통한 일봉 데이터 조회 (MA 및 캔들, 거래대금 증가율 계산용)
        try:
            df_hist = fdr.DataReader(code, start_date)
            if not df_hist.empty and len(df_hist) >= 5:
                # 3. 거래대금 증가율 점수 (최대 20점) [개선: 절대 거래대금 최소 허들 적용]
                # 거래대금 = 종가 * 거래량
                df_hist['Amount_Hist'] = df_hist['Close'] * df_hist['Volume']
                today_amount = df_hist['Amount_Hist'].iloc[-1]

                # [개선] 20일+60일 기준 중 더 보수적(높은) 평균 사용 → 최근 단기 급등으로 기준치가 낮아지는 왜곡 방지
                hist_len = len(df_hist)
                avg_20d = df_hist['Amount_Hist'].iloc[max(0, hist_len-21):hist_len-1].mean()
                avg_60d_range = df_hist['Amount_Hist'].iloc[max(0, hist_len-61):hist_len-1]
                avg_60d = avg_60d_range.mean() if len(avg_60d_range) >= 20 else avg_20d
                avg_amount = max(avg_20d, avg_60d)  # 더 높은(보수적) 기준 적용
                if pd.isna(avg_amount) or avg_amount <= 0:
                    avg_amount = today_amount

                # 절대 거래대금 최소 허들: 당일 거래대금 10억원 미만이면 소외주 펌핑으로 판단, 최대 5점 제한
                MIN_AMOUNT_THRESHOLD = 1_000_000_000  # 10억원
                if today_amount < MIN_AMOUNT_THRESHOLD:
                    score_volume = min(5, max(0, (today_amount / MIN_AMOUNT_THRESHOLD) * 5))
                else:
                    surge_ratio = today_amount / avg_amount if avg_amount > 0 else 1.0
                    score_volume = min(20, max(0, (surge_ratio - 1.0) * 10 + 10))

                    # [신규] 신선도 보정: 최근 5 거래일 이내 이미 2배 급증이 있었다면 -30% 감점
                    # → 이미 한 번 터진 거래대금 재급증은 선행 신호가 아닌 뒤늦은 추격 가능성
                    recent_5d_max = df_hist['Amount_Hist'].iloc[max(0, hist_len-6):hist_len-1].max()
                    if pd.notna(recent_5d_max) and recent_5d_max > avg_amount * 2.0:
                        score_volume = round(score_volume * 0.7, 1)  # 이미 급증 경험 → 30% 감점

                # [개선] 가격 모멘텀 점수 - 5일 누적 등락률 파트 갱신
                # 최근 5일(오늘 포함) 종가 기준 누적 수익률 계산
                if len(df_hist) >= 6:
                    price_5d_ago = float(df_hist['Close'].iloc[-6])  # 5거래일 전 종가
                    price_now = float(df_hist['Close'].iloc[-1])
                    change_5d = ((price_now - price_5d_ago) / price_5d_ago * 100) if price_5d_ago > 0 else 0
                    # 5일 누적 +10% 이상 10점, -10% 이하 0점, 0%일 때 5점
                    score_5d = min(10, max(0, change_5d * 0.5 + 5))
                else:
                    score_5d = 5.0  # 이력 부족 시 중립값

                # 최종 모멘텀 점수 재계산 (당일 10점 + 5일 누적 10점)
                score_momentum = min(20, max(0, score_day + score_5d))

                # 4. 차트 기술적 점수 (최대 30점)
                # (1) 이동평균선 점수 (최대 15점)
                ma5 = df_hist['Close'].rolling(5).mean().iloc[-1]
                ma20 = df_hist['Close'].rolling(20).mean().iloc[-1] if len(df_hist) >= 20 else ma5
                ma60 = df_hist['Close'].rolling(60).mean().iloc[-1] if len(df_hist) >= 60 else ma20
                today_close = df_hist['Close'].iloc[-1]

                # [개선] 선행 매수 관점으로 이평선 점수 재설계
                # 기존: 완벽 정배열=15점(이미 많이 오른 상태), 골든크로스 직전=12점(선행 타이밍인데 낮은 점수)
                # 개선: 골든크로스 직전·20일선 눌림목 지지를 최우선 선행 신호로 재평가
                disparity_from_ma20 = (today_close / ma20 - 1.0) * 100 if ma20 > 0 else 0
                ma_spread = abs(ma5 - ma20) / ma20 if ma20 > 0 else 1.0

                if today_close > ma5 and today_close > ma20 and ma5 <= ma20:
                    score_ma = 14.0  # 역배열 돌파 (골든크로스 직전) → 선행 매수 최적!
                elif -2.0 <= disparity_from_ma20 <= 2.0 and today_close > ma20:
                    score_ma = 13.0  # 20일선 직상방 지지 (눌림목) → 선행 매수 최적!
                elif today_close > ma5 > ma20 and ma20 > ma60:
                    score_ma = 11.0  # 완벽 정배열 (이미 오른 상태, 추격 위험)
                elif today_close > ma5 > ma20 and ma20 <= ma60:
                    score_ma = 10.0  # 단기 정배열, 장기선 아래
                elif today_close > ma20 and today_close <= ma5:
                    score_ma = 7.0   # 20일선 지지, 5일선 아래 (단기 조정 중)
                elif today_close > ma5 and today_close <= ma20:
                    score_ma = 5.0   # 5일선 위이나 20일선 아래
                else:
                    score_ma = 0.0   # 완전 역배열

                # 가감점 필터 적용
                # 1) 대세 하락 필터: 60일선 아래에 있을 때 최대 점수 8점으로 제한
                if today_close <= ma60:
                    score_ma = min(8.0, score_ma)

                # 2) 이격도 과열 감점: 20일선 대비 15% 이상 괴리 시 -4점
                disparity = (today_close / ma20) * 100 if ma20 > 0 else 100
                if disparity >= 115:
                    score_ma -= 4.0

                # 3) 수렴 돌파 가점: 5일선과 20일선 3% 이내 수렴 후 종가가 두 선 모두 상회 시 +2점
                if ma_spread <= 0.03 and today_close > ma5 and today_close > ma20:
                    score_ma += 2.0

                # 0~15점 범위 보정
                score_ma = min(15.0, max(0.0, score_ma))

                # (2) 캔들 패턴 점수 (최대 15점)
                o = float(df_hist['Open'].iloc[-1])
                h = float(df_hist['High'].iloc[-1])
                l = float(df_hist['Low'].iloc[-1])
                c = float(df_hist['Close'].iloc[-1])
                prev_close = float(df_hist['Close'].iloc[-2]) if len(df_hist) >= 2 else o

                # 점상한가 / 점하한가 예외 처리 (고가와 저가가 같은 경우)
                if h == l:
                    if c > prev_close:
                        score_candle = 15.0  # 점상한가 (매수세 최강)
                    else:
                        score_candle = 0.0   # 점하한가 (매도세 최강)
                else:
                    body = c - o
                    rng = h - l
                    lower_shadow = min(o, c) - l
                    upper_shadow = h - max(o, c)

                    # 1) 도지형 판별 임계값 도입 (시가 대비 몸통 크기가 0.2% 이하인 경우 도지로 분류)
                    is_doji = (abs(body) / o <= 0.002) if o > 0 else (body == 0)

                    if is_doji:
                        if lower_shadow > rng * 0.5:
                            score_candle = 10.0  # 밑꼬리가 긴 도지 (지지세 유입)
                        else:
                            score_candle = 5.0   # 일반 도지
                    elif body > 0:  # 양봉
                        if lower_shadow > body * 0.5:
                            score_candle = 15.0  # 아래꼬리가 긴 망치형 양봉 (매수세 강함)
                        elif upper_shadow > body and (body / o >= 0.005):
                            # 몸통이 시가 대비 0.5% 이상으로 유의미할 때만 위꼬리 감점 적용
                            score_candle = 8.0   # 위꼬리가 긴 양봉 (매물 저항)
                        elif upper_shadow > body * 2:
                            # 몸통이 미세할 때는 위꼬리가 몸통의 2배 이상일 때만 감점
                            score_candle = 8.0
                        else:
                            score_candle = 12.0  # 일반 양봉 / 장대양봉
                    else:  # 음봉
                        # [개선] 거래량으로 음봉 품질 구분: 저거래량 음봉은 건강한 눌림목, 고거래량 음봉은 매도 압력
                        vol_today = float(df_hist['Volume'].iloc[-1]) if 'Volume' in df_hist.columns else 0
                        avg_vol_5d = df_hist['Volume'].iloc[max(0, hist_len-6):hist_len-1].mean() if 'Volume' in df_hist.columns else vol_today
                        avg_vol_5d = avg_vol_5d if pd.notna(avg_vol_5d) and avg_vol_5d > 0 else vol_today

                        if lower_shadow > abs(body) * 1.5:
                            # 아래꼬리 긴 음봉 - 거래량 동반 여부로 신호 강도 구분
                            score_candle = 10.0 if vol_today >= avg_vol_5d else 8.0
                        elif vol_today < avg_vol_5d * 0.7:
                            score_candle = 5.0   # 저거래량 조정 음봉 = 건강한 눌림목 (선행 매수 기회)
                        elif vol_today < avg_vol_5d:
                            score_candle = 3.0   # 평균 이하 거래량 음봉 (보통 조정)
                        else:
                            score_candle = 0.0   # 고거래량 하락 = 매도 압력 강함

        except Exception as e:
            print(f'  ⚠️ [{name}] 가격 이력 조회 실패: {e}')

        # ── 이중 신호 중복 측정 보정 [개선: 극단적 중복 신호만 보정] ──────────────────────
        # 거래대금 만점권(≥14점)과 가격 급등 만점권(≥14점)이 동시에 나타날 때만 보정
        # → 중간 강도(12점)까지 보정하면 일반적인 강세 종목도 패널티를 받는 부작용 발생
        if score_volume >= 14 and score_momentum >= 14:
            excess_v = score_volume - 14
            excess_m = score_momentum - 14
            score_volume   = max(14, score_volume   - excess_v * 0.5)
            score_momentum = max(14, score_momentum - excess_m * 0.5)

        # ── 섹터 분류 및 매크로 가중치 적용 ──────────────────────────
        fdr_sector = row.get('FDR_Sector', '')
        fdr_industry = row.get('FDR_Industry', '')
        sector = _classify_sector(code, name, fdr_sector, fdr_industry)

        # 만약 로컬/FDR 분류에서 '기타'로 분류되었을 경우, KIS HTS API 실시간 조회 폴백 (10-15개 소수 종목만 동적 호출)
        if sector == '기타':
            hts_sector = fetch_stock_sector(token, code)
            if hts_sector:
                # HTS 업종명을 기반으로 9대 핵심 섹터 분류 재시도
                sector = _classify_sector(code, name, hts_sector)
                if sector == '기타':
                    sector = hts_sector  # 재분류 불가 시 HTS 업종명 그대로 사용 (기타 방지)
            time.sleep(0.05)  # TPS 방지

        sector_mult = get_sector_multiplier(sector)

        # ── 변동성 조정 패널티 (리스크 조정 수익률 관점) ──────────────
        # 20일 연환산 변동성(σ)이 30% 초과 시 고변동성 종목 점수 하향
        # 급등락장에서 변동성 큰 종목의 역선택 문제를 방지함
        vol_penalty = 1.0
        try:
            if df_hist is not None and len(df_hist) >= 20:
                daily_returns = df_hist['Close'].pct_change().dropna()
                vol_20d = daily_returns.tail(20).std() * (252 ** 0.5)  # 연환산 변동성
                if vol_20d > 0.5:    vol_penalty = 0.80  # 50% 초과: 극고변동성 강한 패널티
                elif vol_20d > 0.35: vol_penalty = 0.90  # 35~50%: 고변동성 패널티
                elif vol_20d > 0.25: vol_penalty = 0.95  # 25~35%: 약한 패널티
        except:
            vol_penalty = 1.0

        # ── 합산 점수 + 전체 보정 계수 적용 ──────────────────────────
        # 적용 순서: 원점수 → 이중신호보정 → 변동성조정 → 섹터가중치 → 시장국면패널티
        raw_score   = score_momentum + score_supply + score_volume + score_ma + score_candle
        total_score = round(raw_score * vol_penalty * sector_mult * market_penalty, 1)

        # FDR 당일 거래대금(today_amount)이 산출되어 있으면 사용, 없으면 df_hd의 Amount 사용 (단위: 원)
        amount = today_amount if today_amount > 0 else float(row.get('Amount', 0))

        rows.append({
            'Code':             code,
            'Name':             name,
            'Total_Score':      total_score,
            'Score_Momentum':   round(score_momentum, 1),
            'Score_Supply':     round(score_supply, 1),
            'Score_Volume':     round(score_volume, 1),
            'Score_MA':         round(score_ma, 1),
            'Score_Candle':     round(score_candle, 1),
            'Close':            close,
            'ChagesRatio':      change,
            'Amount':           amount,          # 거래대금 컬럼 추가
            'Sector':           sector,          # 섹터 분류
            'Sector_Mult':      sector_mult,     # 섹터 가중치 계수
            'Vol_Penalty':      vol_penalty,     # 변동성 패널티 계수
            'Market_Penalty':   market_penalty,  # 시장 패널티 계수
            'Market_Condition': market_condition,
        })
        time.sleep(0.05) # 서버 부하 방지 및 FDR 호출 조절

    df = pd.DataFrame(rows).sort_values('Total_Score', ascending=False)
    print(f'  → {len(df)}개 종목')
    return df


def collect_market_summary(token, df_intraday):
    """시장 요약 데이터 수집 (코스피/코스닥/환율)"""
    print('📉 시장 요약 데이터 수집 중...')
    rows = []

    # FinanceDataReader로 지수 조회
    try:
        # 최근 7일치 데이터를 불러와 마지막 데이터(최신 종가)를 사용
        start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        df_ks = fdr.DataReader('KS11', start_date)
        df_kq = fdr.DataReader('KQ11', start_date)
        df_usd = fdr.DataReader('USD/KRW', start_date)

        def last(df, col='Close'):
            return float(df[col].iloc[-1]) if not df.empty and col in df.columns else 0

        def chg(df):
            return float(df['Change'].iloc[-1] * 100) if not df.empty and 'Change' in df.columns else 0

        def trend(v):
            return '📈' if v > 0 else ('📉' if v < 0 else '➖')

        # 수급 데이터 (intraday 마지막 값)
        def get_supply(market):
            if df_intraday.empty or 'Market' not in df_intraday.columns:
                return 0, 0, 0
            df_m = df_intraday[df_intraday['Market'] == market]
            if df_m.empty:
                return 0, 0, 0
            last_row = df_m.sort_values('Time').iloc[-1]
            return (
                int(last_row.get('Foreign_Net', 0)),
                int(last_row.get('Individual_Net', 0)),
                int(last_row.get('Institutional_Net', 0))
            )

        ks_chg = chg(df_ks)
        kq_chg = chg(df_kq)
        usd_chg = chg(df_usd)

        fgn_ks, ind_ks, inst_ks = get_supply('코스피')
        fgn_kq, ind_kq, inst_kq = get_supply('코스닥')

        rows = [
            {
                '종목/종류': '코스피',
                '지수': f'{last(df_ks):,.2f}',
                '등락률': f'{ks_chg:+.2f}%',
                '추이': trend(ks_chg),
                '외국인(억)': str(fgn_ks),
                '개인(억)': str(ind_ks),
                '기관(억)': str(inst_ks),
            },
            {
                '종목/종류': '코스닥',
                '지수': f'{last(df_kq):,.2f}',
                '등락률': f'{kq_chg:+.2f}%',
                '추이': trend(kq_chg),
                '외국인(억)': str(fgn_kq),
                '개인(억)': str(ind_kq),
                '기관(억)': str(inst_kq),
            },
            {
                '종목/종류': 'USD/KRW',
                '지수': f'{last(df_usd):,.2f}',
                '등락률': f'{usd_chg:+.2f}%',
                '추이': trend(usd_chg),
                '외국인(억)': '-',
                '개인(억)': '-',
                '기관(억)': '-',
            },
        ]
    except Exception as e:
        print(f'  ❌ 지수 조회 오류: {e}')
        rows = []

    df = pd.DataFrame(rows)
    print(f'  → {len(df)}행')
    return df


def collect_supply_intraday(token):
    """네이버 API: 코스피/코스닥 수급 일중 추이 데이터 수집 (30분 단위 누적)

    [방식]
    - 네이버 m.stock trend API로 현재 시점 수급 스냅샷(억원) 획득
    - 기존 당일 CSV를 GitHub raw URL에서 불러와 현재 시간 포인트를 append
    - 새 날짜이면 자동으로 초기화 (날짜 컬럼으로 구분)
    - GitHub Actions가 30분마다 실행하므로 하루 최대 13개 포인트(09:00~15:30) 적재
    """
    print('⏱️ 수급 시계열 데이터 수집 중 (네이버 API)...')
    now = datetime.now()
    now_str = now.strftime('%H:%M')
    today_str = now.strftime('%Y%m%d')

    def _parse_naver_supply(val_str):
        """'+5,254' 형태의 네이버 수급 문자열을 억원 정수로 변환"""
        try:
            return int(str(val_str).replace(',', '').replace('+', '').strip())
        except Exception:
            return 0

    # 1. 네이버 API로 현재 수급 스냅샷 획득
    headers = {'User-Agent': 'Mozilla/5.0'}
    new_rows = []
    for mkt_code, mkt_name in [('KOSPI', '코스피'), ('KOSDAQ', '코스닥')]:
        try:
            r = requests.get(
                f'https://m.stock.naver.com/api/index/{mkt_code}/trend',
                headers=headers, timeout=5
            )
            if r.status_code == 200:
                d = r.json()
                # bizdate 확인: 오늘 날짜 데이터인지 검증
                api_date = str(d.get('bizdate', today_str))
                if api_date != today_str:
                    print(f'  ⚠️ {mkt_name} 수급: API 날짜({api_date}) ≠ 오늘({today_str}), 스킵')
                    continue
                new_rows.append({
                    'Date':             today_str,
                    'Time':             now_str,
                    'Market':           mkt_name,
                    'Foreign_Net':      _parse_naver_supply(d.get('foreignValue', '0')),
                    'Individual_Net':   _parse_naver_supply(d.get('personalValue', '0')),
                    'Institutional_Net': _parse_naver_supply(d.get('institutionalValue', '0')),
                })
                print(f'  ✅ {mkt_name}: 외국인={d.get("foreignValue")} 개인={d.get("personalValue")} 기관={d.get("institutionalValue")}')
        except Exception as e:
            print(f'  ❌ {mkt_name} 네이버 수급 조회 실패: {e}')

    if not new_rows:
        print('  ⚠️ 수급 스냅샷 데이터 없음 → 기존 파일 유지')
        # 기존 파일이 있으면 그대로 반환
        existing_path = os.path.join(DATA_DIR, 'df_supply_intraday.csv')
        if os.path.exists(existing_path):
            try:
                df_existing = pd.read_csv(existing_path, encoding='utf-8-sig')
                # 오늘 날짜 데이터만 유지
                if 'Date' in df_existing.columns:
                    df_existing = df_existing[df_existing['Date'].astype(str) == today_str]
                return df_existing
            except Exception:
                pass
        return pd.DataFrame(columns=['Date', 'Time', 'Market', 'Foreign_Net', 'Individual_Net', 'Institutional_Net'])

    df_new = pd.DataFrame(new_rows)

    # 2. 기존 당일 누적 데이터 로드 (로컬 파일 우선, 없으면 GitHub raw URL)
    df_existing = pd.DataFrame(columns=['Date', 'Time', 'Market', 'Foreign_Net', 'Individual_Net', 'Institutional_Net'])
    local_path = os.path.join(DATA_DIR, 'df_supply_intraday.csv')

    if os.path.exists(local_path):
        try:
            df_loaded = pd.read_csv(local_path, encoding='utf-8-sig')
            # 날짜 컬럼이 없는 구버전 파일이면 초기화
            if 'Date' not in df_loaded.columns:
                print('  ℹ️ 구버전 포맷 감지 → 오늘부터 새로 누적')
            else:
                # 오늘 날짜 데이터만 유지 (전일 데이터 자동 제거)
                df_existing = df_loaded[df_loaded['Date'].astype(str) == today_str].copy()
                print(f'  ✅ 기존 {len(df_existing)}개 포인트 로드 완료')
        except Exception as e:
            print(f'  ⚠️ 기존 파일 로드 실패: {e}')

    # 3. 현재 시간 중복 제거 후 append
    if not df_existing.empty:
        # 이미 같은 시간·같은 시장 데이터가 있으면 덮어쓰기 (중복 방지)
        df_existing = df_existing[
            ~((df_existing['Time'] == now_str) &
              (df_existing['Market'].isin(df_new['Market'].tolist())))
        ]

    df_combined = pd.concat([df_existing, df_new], ignore_index=True)
    # 시간 순 정렬
    df_combined = df_combined.sort_values(['Market', 'Time']).reset_index(drop=True)

    print(f'  → 총 {len(df_combined)}개 포인트 (오늘 {today_str})')
    return df_combined


# ── 메인 실행 ────────────────────────────────────────────────────
def main():
    print('=' * 50)
    print(f'🚀 GD 3.0 데이터 수집 시작: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 50)

    if not APP_KEY or not APP_SECRET:
        print('❌ KIS_APP_KEY / KIS_APP_SECRET 환경변수가 설정되지 않았습니다.')
        return

    # KIS 토큰 발급
    print('\n🔑 KIS API 토큰 발급 중...')
    token = get_access_token()
    if not token:
        print('❌ 토큰 발급 실패')
        return
    print('  ✅ 토큰 발급 완료')

    # 데이터 수집
    print('\n📥 데이터 수집 시작...')
    df_full     = collect_full_market()
    df_intraday = collect_supply_intraday(token)
    df_hd       = collect_high_density(token, df_full)
    df_quant    = collect_quant_final(token, df_hd, df_full)
    df_summary  = collect_market_summary(token, df_intraday)

    # 로컬 data/ 폴더에 CSV 저장 (GitHub Actions가 커밋·푸시)
    print('\n💾 data/ 폴더에 CSV 저장 중...')
    saves = [
        (df_full,     'df_full_market.csv'),
        (df_intraday, 'df_supply_intraday.csv'),
        (df_hd,       'df_high_density.csv'),
        (df_quant,    'df_quant_final.csv'),
        (df_summary,  'df_market_summary.csv'),
    ]

    for df, fname in saves:
        if df.empty:
            print(f'  ⚠️ {fname}: 데이터 없음, 건너뜀')
            continue
        try:
            save_df_to_local(df, fname)
        except Exception as e:
            print(f'  ❌ {fname} 저장 실패: {e}')

    print('\n' + '=' * 50)
    print(f'✅ 수집 완료: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 50)


if __name__ == '__main__':
    main()
