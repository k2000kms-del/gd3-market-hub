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
            'FID_INPUT_DATE_1': datetime.now().strftime('%Y%m%d'),
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
    """KIS API: 수급 상위 종목 데이터 수집"""
    print('📡 수급 상위 종목 데이터 수집 중...')
    if df_full.empty:
        return pd.DataFrame()

    # 거래량 상위 30개 종목 대상
    top_stocks = df_full.nlargest(30, 'Volume') if 'Volume' in df_full.columns else df_full.head(30)
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
    print(f'  → {len(df)}개 종목')
    return df


def collect_quant_final(df_hd, df_full):
    """Quant 점수 계산"""
    print('🎯 Quant 점수 계산 중...')
    if df_hd.empty:
        return pd.DataFrame()

    rows = []
    for _, row in df_hd.iterrows():
        # 간단한 Quant 점수 계산
        change  = float(row.get('ChagesRatio', 0))
        foreign = float(row.get('Foreign_Net', 0))
        inst    = float(row.get('Institutional_Net', 0))
        prog    = float(row.get('Program_Net', 0))
        volume  = float(row.get('Volume', 0))

        # 점수 계산 (각 항목 최대 25점)
        score_momentum = min(25, max(0, change * 5 + 12.5))
        score_supply   = min(35, max(0, (foreign + inst) / 1000 + 17.5))
        score_volume   = min(25, max(0, volume / 1000000 * 5 + 12.5))
        score_program  = min(15, max(0, prog / 500 + 7.5))
        total_score    = score_momentum + score_supply + score_volume + score_program

        rows.append({
            'Code':             row.get('Code', ''),
            'Name':             row.get('Name', ''),
            'Total_Score':      round(total_score, 1),
            'Score_Momentum':   round(score_momentum, 1),
            'Score_Supply':     round(score_supply, 1),
            'Score_Volume':     round(score_volume, 1),
            'Score_Program':    round(score_program, 1),
        })

    df = pd.DataFrame(rows).sort_values('Total_Score', ascending=False)
    print(f'  → {len(df)}개 종목')
    return df


def collect_market_summary(token, df_intraday):
    """시장 요약 데이터 수집 (코스피/코스닥/환율)"""
    print('📉 시장 요약 데이터 수집 중...')
    rows = []

    # FinanceDataReader로 지수 조회
    try:
        df_ks = fdr.DataReader('KS11', datetime.now().strftime('%Y-%m-%d'))
        df_kq = fdr.DataReader('KQ11', datetime.now().strftime('%Y-%m-%d'))
        df_usd = fdr.DataReader('USD/KRW', datetime.now().strftime('%Y-%m-%d'))

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
                'FID_INPUT_DATE_1': datetime.now().strftime('%Y%m%d'),
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
            print(f'  ❌ {market_name} 수급 조회 오류: {e}')
            # 오류 시 현재 시간 기준 0 데이터 추가
            rows.append({
                'Time': now_str, 'Market': market_name,
                'Foreign_Net': 0, 'Individual_Net': 0, 'Institutional_Net': 0
            })

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
