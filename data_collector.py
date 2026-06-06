# -*- coding: utf-8 -*-
"""
GD 3.0 Market Hub - 데이터 수집기 (GitHub Actions 전용)
- 한국 주식시장 개장 시간(09:00~15:30 KST)에 GitHub Actions로 자동 실행
- KIS API + FinanceDataReader로 시장 데이터 수집
- Google Drive API(Service Account)로 CSV 업로드
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
from io import BytesIO

# ── Google Drive API 관련 ────────────────────────────────────────
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.credentials import Credentials

# ── KIS API 설정 (환경변수에서 읽기) ────────────────────────────
APP_KEY    = os.environ.get('KIS_APP_KEY', '')
APP_SECRET = os.environ.get('KIS_APP_SECRET', '')
URL_BASE   = 'https://openapi.koreainvestment.com:9443'

# ── Google Drive 파일 ID (기존 파일 덮어쓰기) ───────────────────
FILE_IDS = {
    'df_high_density.csv':    '1UQTyfpFD2xuK-fKlq2RqK2MvCqxXaAB3',
    'df_quant_final.csv':     '1eD7HHBnQ_7FYE5ZCpnjMgYcW_rmmAqjP',
    'df_full_market.csv':     '1RA1PkDChDuLpj6YkmTb6uGfS6Nhpleve',
    'df_market_summary.csv':  '17F5LJf4UcA0neVw60oRCP2qk7PugRAok',
    'df_supply_intraday.csv': '1sYEK6PsAoH1ybupVbtQKnL289LCwnhvc',
}


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
        data = res.json().get('output', {})
        return {
            'Foreign_Net':       int(data.get('frgn_ntby_qty', 0)),
            'Institutional_Net': int(data.get('orgn_ntby_qty', 0)),
            'Program_Net':       int(data.get('pgtr_ntby_qty', 0)),
        }
    except Exception:
        return {'Foreign_Net': 0, 'Institutional_Net': 0, 'Program_Net': 0}


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


# ── Google Drive 업로드 ──────────────────────────────────────────
def get_drive_service():
    """Google Drive API 서비스 객체 생성 (OAuth 2.0)"""
    token_json_str = os.environ.get('GDRIVE_OAUTH_TOKEN', '')
    if not token_json_str:
        raise ValueError('GDRIVE_OAUTH_TOKEN 환경변수가 설정되지 않았습니다.')

    token_info = json.loads(token_json_str)
    creds = Credentials.from_authorized_user_info(
        token_info,
        scopes=['https://www.googleapis.com/auth/drive']
    )
    return build('drive', 'v3', credentials=creds)


def upload_df_to_drive(service, df, file_id, filename):
    """DataFrame을 CSV로 Google Drive에 업로드 (기존 파일 덮어쓰기)"""
    csv_bytes = df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
    media = MediaIoBaseUpload(BytesIO(csv_bytes), mimetype='text/csv', resumable=False)
    service.files().update(fileId=file_id, media_body=media).execute()
    print(f'  ✅ {filename} → Drive 업로드 완료 ({len(df)}행)')


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
        })

    df = pd.DataFrame(rows)
    print(f'  → {len(df)}개 종목 수급 수집 완료')
    return df


def collect_quant_final(df_hd, df_full):
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

    [핵심 보정 로직]
    - 시장 국면 패널티: 코스피/코스닥 동반 약세 시 전체 점수 자동 하향 조정
    - 이중 신호 중복 보정: 거래대금 급증과 가격 급등이 동시에 만점일 때 과대평가 방지
    """
    print('🎯 선행 매수 퀀트 스코어 계산 중...')
    if df_hd.empty:
        return pd.DataFrame()

    # ── 시장 국면 사전 파악 (전체 점수 조정 계수 산출) ──────────────
    market_penalty = 1.0   # 기본값: 패널티 없음 (1.0 = 100%)
    market_condition = '중립'
    try:
        start_mkt = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
        df_ks = fdr.DataReader('KS11', start_mkt)
        df_kq = fdr.DataReader('KQ11', start_mkt)
        ks_chg = float(df_ks['Change'].iloc[-1] * 100) if not df_ks.empty and 'Change' in df_ks.columns else 0
        kq_chg = float(df_kq['Change'].iloc[-1] * 100) if not df_kq.empty and 'Change' in df_kq.columns else 0
        avg_chg = (ks_chg + kq_chg) / 2

        if avg_chg <= -1.5:
            market_penalty = 0.8   # 시장 급락: 전체 점수 20% 하향 → 매수 신호 보수적으로 처리
            market_condition = f'급락 ({avg_chg:.2f}%)'
        elif avg_chg <= -0.5:
            market_penalty = 0.9   # 시장 약세: 전체 점수 10% 하향
            market_condition = f'약세 ({avg_chg:.2f}%)'
        elif avg_chg >= 1.0:
            market_condition = f'강세 ({avg_chg:.2f}%)'
        else:
            market_condition = f'중립 ({avg_chg:.2f}%)'
        print(f'  📊 시장 국면: {market_condition} (점수 계수: x{market_penalty})')
    except Exception as e:
        print(f'  ⚠️ 시장 국면 조회 실패 (기본값 적용): {e}')

    rows = []
    # 60일선(MA60) 및 가격 이력을 충분히 조회하기 위해 시작 날짜 계산 (안전하게 100일 전으로 설정)
    start_date = (datetime.now() - timedelta(days=100)).strftime('%Y-%m-%d')

    for _, row in df_hd.iterrows():
        code = str(row.get('Code', '')).zfill(6)
        name = row.get('Name', '')

        # 1. 가격 모멘텀 점수 (최대 20점) [개선: 당일(10점) + 5일 누적(10점) 혼합]
        # 당일 등락률: +5% 이상 10점, -5% 이하 0점, 보합 5점
        change = float(row.get('ChagesRatio', 0))
        score_day = min(10, max(0, change * 1 + 5))
        # 5일 누적 모멘텀: FDR 조회 전이므로 일단 중립값 5점으로 초기화 (아래 FDR 블록에서 갱신)
        score_5d = 5.0
        score_momentum = score_day + score_5d  # FDR 블록에서 최종 갱신됨

        # 2. 수급 점수 (최대 30점) [개선: 시가총액 대비 순매수 비율 기준]
        # 외인+기관 합산 순매수 금액(원화) 기준. KIS API 순매수량은 주식수이므로 종가를 곱해 금액 계산.
        close = float(row.get('Close', 0))
        foreign_qty = float(row.get('Foreign_Net', 0))
        inst_qty = float(row.get('Institutional_Net', 0))
        marcap = float(row.get('Marcap', 0))

        net_buy_amount = (foreign_qty + inst_qty) * close
        # 시가총액 대비 순매수 비율(%) 기준으로 평가하여 대형주/소형주 체급 차이를 공평하게 반영
        # 비율 +0.05% 이상 30점, -0.05% 이하 0점, 0%일 때 15점
        if marcap > 0:
            net_ratio = (net_buy_amount / marcap) * 100  # 시가총액 대비 순매수 비율(%)
            score_supply = min(30, max(0, net_ratio / 0.05 * 15 + 15))
        else:
            # 시가총액 정보가 없을 경우 절대 금액 방식 폴백 (+5억원 이상 30점)
            score_supply = min(30, max(0, net_buy_amount / 100000000 * 3 + 15))

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

                # 최근 20일 평균 거래대금 계산 (당일 제외한 최근 20일)
                hist_len = len(df_hist)
                avg_range = df_hist['Amount_Hist'].iloc[max(0, hist_len-21):hist_len-1]
                avg_amount = avg_range.mean() if not avg_range.empty else today_amount

                # [핵심 개선] 절대 거래대금 최소 허들: 당일 거래대금 10억원 미만이면 소외주 펌핑으로 판단, 최대 5점 제한
                MIN_AMOUNT_THRESHOLD = 1_000_000_000  # 10억원
                if today_amount < MIN_AMOUNT_THRESHOLD:
                    # 소외주: 거래 자체가 미미하므로 배율이 높아도 최대 5점 이하로 제한
                    score_volume = min(5, max(0, (today_amount / MIN_AMOUNT_THRESHOLD) * 5))
                else:
                    if avg_amount > 0:
                        surge_ratio = today_amount / avg_amount
                    else:
                        surge_ratio = 1.0
                    # 거래대금 증가율 점수 공식: 2배 이상 20점, 1배(평균)일 때 10점, 0배일 때 0점
                    score_volume = min(20, max(0, (surge_ratio - 1.0) * 10 + 10))

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

                # 기본 이평선 배열 점수 산정 (최대 15점)
                if today_close > ma5 > ma20 and ma20 > ma60:
                    score_ma = 15.0  # 완벽한 정배열 우상향
                elif today_close > ma5 > ma20 and ma20 <= ma60:
                    score_ma = 13.0  # 단기 정배열 안착 (장기선 아래)
                elif today_close > ma5 and today_close > ma20 and ma5 <= ma20:
                    score_ma = 12.0  # 강한 역배열 돌파 (골든크로스 직전)
                elif today_close > ma5 and today_close <= ma20:
                    score_ma = 9.0   # 단기 반등 (5일선 돌파)
                elif today_close > ma20 and today_close <= ma5:
                    score_ma = 7.0   # 눌림목 지지 (20일선 지지)
                else:
                    score_ma = 0.0   # 완전 역배열 및 하락세

                # 고도화 가감점 필터 적용
                # 1) 대세 하락 필터: 60일선 아래에 있을 때 최대 점수 8점으로 제한
                if today_close <= ma60:
                    score_ma = min(8.0, score_ma)

                # 2) 이격도 과열 감점: 20일선 대비 주가 괴리율이 15% 이상일 때 4점 감점
                disparity = (today_close / ma20) * 100 if ma20 > 0 else 100
                if disparity >= 115:
                    score_ma -= 4.0

                # 3) 수렴 돌파 가점: 5일선과 20일선이 3% 이내로 수렴한 상태에서 종가가 두 선을 모두 상회할 때 +2점 가점
                ma_spread = abs(ma5 - ma20) / ma20 if ma20 > 0 else 1.0
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
                        if lower_shadow > abs(body) * 1.5:
                            score_candle = 8.0   # 아래꼬리가 매우 긴 음봉 (저점 매수세 유입)
                        else:
                            score_candle = 0.0   # 일반 음봉 / 장대음봉 (매도세 지배)

        except Exception as e:
            print(f'  ⚠️ [{name}] 가격 이력 조회 실패: {e}')

        # ── 이중 신호 중복 측정 보정 ──────────────────────────────────
        # Score_Volume(거래대금 급증)과 Score_Momentum(가격 급등)은 동일한 매수세를
        # 서로 다른 지표로 중복 측정하는 경향이 있음.
        # 두 점수가 동시에 15점 이상(고득점)이면 초과분의 40%를 상호 조정하여 과대평가 방지.
        if score_volume >= 15 and score_momentum >= 15:
            excess_v = score_volume - 15
            excess_m = score_momentum - 15
            score_volume   = max(15, score_volume   - excess_v * 0.4)
            score_momentum = max(15, score_momentum - excess_m * 0.4)

        # ── 합산 점수 + 시장 국면 패널티 적용 ────────────────────────
        raw_score = score_momentum + score_supply + score_volume + score_ma + score_candle
        total_score = round(raw_score * market_penalty, 1)

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
            'Market_Condition': market_condition,  # 시장 국면 상태 기록
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
    """KIS API: 코스피/코스닥 수급 시계열 데이터 수집 (1분 단위 누적)"""
    print('⏱️ 수급 시계열 데이터 수집 중...')
    now_str = datetime.now().strftime('%H:%M')
    rows = []

    for market, market_name, market_div in [
        ('0001', '코스피', 'J'),
        ('1001', '코스닥', 'Q'),
    ]:
        try:
            headers = {
                'Content-Type': 'application/json',
                'authorization': f'Bearer {token}',
                'appkey': APP_KEY,
                'appsecret': APP_SECRET,
                'tr_id': 'FHPUP02310000',
            }
            params = {
                'FID_COND_MRKT_DIV_CODE': 'U',
                'FID_INPUT_ISCD': market,
                # 주말일 경우 가장 최근 금요일(또는 그 이전)을 타겟으로 함
                'FID_INPUT_DATE_1': (datetime.now() - timedelta(days=max(0, datetime.now().weekday() - 4))).strftime('%Y%m%d'),
            }
            res = requests.get(
                f'{URL_BASE}/uapi/domestic-stock/v1/quotations/inquire-investor-time-itemlist',
                headers=headers, params=params
            )
            output = res.json().get('output2', [])

            for item in output:
                t = item.get('stck_bsop_date', now_str)[:4]
                time_str = f'{t[:2]}:{t[2:]}' if len(t) == 4 else now_str
                rows.append({
                    'Time':             time_str,
                    'Market':           market_name,
                    'Foreign_Net':      int(item.get('frgn_ntby_tr_pbmn', 0)) // 100000000,
                    'Individual_Net':   int(item.get('indv_ntby_tr_pbmn', 0)) // 100000000,
                    'Institutional_Net': int(item.get('orgn_ntby_tr_pbmn', 0)) // 100000000,
                })
        except Exception as e:
            print(f'  ❌ {market_name} 수급 조회 에러: {e}')
            # 주말/에러 시 0을 넣지 않고 패스하여, 기존 금요일 데이터가 덮어씌워지지 않도록 함
            pass

    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=['Time', 'Market', 'Foreign_Net', 'Individual_Net', 'Institutional_Net']
    )
    print(f'  → {len(df)}행')
    return df


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

    # Google Drive 서비스 초기화
    print('\n🔗 Google Drive 연결 중...')
    try:
        drive_service = get_drive_service()
        print('  ✅ Drive 연결 완료')
    except Exception as e:
        print(f'  ❌ Drive 연결 실패: {e}')
        return

    # 데이터 수집
    print('\n📥 데이터 수집 시작...')
    df_full     = collect_full_market()
    df_intraday = collect_supply_intraday(token)
    df_hd       = collect_high_density(token, df_full)
    df_quant    = collect_quant_final(df_hd, df_full)
    df_summary  = collect_market_summary(token, df_intraday)

    # Google Drive 업로드
    print('\n📤 Google Drive 업로드 중...')
    uploads = [
        (df_full,     'df_full_market.csv'),
        (df_intraday, 'df_supply_intraday.csv'),
        (df_hd,       'df_high_density.csv'),
        (df_quant,    'df_quant_final.csv'),
        (df_summary,  'df_market_summary.csv'),
    ]

    for df, fname in uploads:
        if df.empty:
            print(f'  ⚠️ {fname}: 데이터 없음, 건너뜀')
            continue
        try:
            upload_df_to_drive(drive_service, df, FILE_IDS[fname], fname)
        except Exception as e:
            print(f'  ❌ {fname} 업로드 실패: {e}')

    print('\n' + '=' * 50)
    print(f'✅ 수집 완료: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 50)


if __name__ == '__main__':
    main()
