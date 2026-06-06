# -*- coding: utf-8 -*-
"""
2026년 한국 증시 종합 분석
- KOSPI / KOSDAQ / USD/KRW 전체 데이터 분석
- 사이드카 추정 이벤트, 변동성 레짐, 월별 통계 산출
- 결과를 Google Drive에 CSV로 저장
"""
import os, json
import pandas as pd
import numpy as np
import FinanceDataReader as fdr
from datetime import datetime
from io import BytesIO
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.credentials import Credentials


def get_drive_service():
    creds = Credentials.from_authorized_user_info(
        json.loads(os.environ.get('GDRIVE_OAUTH_TOKEN', '{}')),
        scopes=['https://www.googleapis.com/auth/drive']
    )
    return build('drive', 'v3', credentials=creds)


def upload(service, df, name):
    b = df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
    m = MediaIoBaseUpload(BytesIO(b), mimetype='text/csv', resumable=False)
    f = service.files().create(body={'name': name}, media_body=m, fields='id').execute()
    print(f'  ✅ {name} → Drive (ID: {f.get("id")})')


def main():
    print('=' * 65)
    print('📊 2026년 한국 증시 종합 분석 시작')
    print('=' * 65)

    # ── 데이터 수집 ───────────────────────────────────────────────
    start = '2025-12-01'  # 연초 비교를 위해 2025-12 포함
    ks  = fdr.DataReader('KS11', start)   # KOSPI
    kq  = fdr.DataReader('KQ11', start)   # KOSDAQ
    usd = fdr.DataReader('USD/KRW', start)

    # 2026년 데이터만 필터
    ks_26  = ks[ks.index >= '2026-01-01'].copy()
    kq_26  = kq[kq.index >= '2026-01-01'].copy()
    usd_26 = usd[usd.index >= '2026-01-01'].copy()

    # ── 일간 통계 계산 ────────────────────────────────────────────
    ks_26['Change_pct']    = ks_26['Change'] * 100
    ks_26['HL_Range_pct']  = (ks_26['High'] - ks_26['Low']) / ks_26['Close'].shift(1) * 100
    ks_26['Vol_10d']       = ks_26['Change_pct'].rolling(10).std()  # 10일 σ
    ks_26['Vol_20d']       = ks_26['Change_pct'].rolling(20).std()  # 20일 σ
    ks_26['Cum_Ret']       = (1 + ks_26['Change']).cumprod() - 1
    ks_26['Month']         = ks_26.index.strftime('%Y-%m')

    kq_26['Change_pct']   = kq_26['Change'] * 100
    kq_26['HL_Range_pct'] = (kq_26['High'] - kq_26['Low']) / kq_26['Close'].shift(1) * 100

    # ── 사이드카 추정 이벤트 분류 ──────────────────────────────────
    # 기준:
    # - 매도 사이드카 추정: 일중 낙폭이 전일종가 대비 -3% 이상이거나 고저폭 4% 이상
    # - 매수 사이드카 추정: 일중 급등폭이 전일종가 대비 +3% 이상이거나 고저폭 4% 이상
    # - 실제 사이드카는 선물 기준이므로 현물 기준 근사치

    ks_26['Sidecar_Sell'] = (ks_26['Change_pct'] <= -3.0) | (ks_26['HL_Range_pct'] >= 5.0)
    ks_26['Sidecar_Buy']  = (ks_26['Change_pct'] >= 3.0)  | (ks_26['HL_Range_pct'] >= 5.0)
    ks_26['Extreme_Day']  = ks_26['HL_Range_pct'] >= 4.0  # 극단 변동일 (4% 이상)

    kq_26['Sidecar_Sell'] = (kq_26['Change_pct'] <= -3.0) | (kq_26['HL_Range_pct'] >= 5.0)
    kq_26['Sidecar_Buy']  = (kq_26['Change_pct'] >= 3.0)  | (kq_26['HL_Range_pct'] >= 5.0)

    # ── 월별 집계 ─────────────────────────────────────────────────
    monthly = []
    for month in ks_26['Month'].unique():
        mk = ks_26[ks_26['Month'] == month]
        mq = kq_26[kq_26.index.strftime('%Y-%m') == month]

        ks_ret    = mk['Change_pct'].sum()
        kq_ret    = mq['Change_pct'].sum() if not mq.empty else 0
        ks_std    = mk['Change_pct'].std()
        ks_max    = mk['Change_pct'].max()
        ks_min    = mk['Change_pct'].min()
        ks_hl_max = mk['HL_Range_pct'].max()
        sell_cnt  = mk['Sidecar_Sell'].sum()
        buy_cnt   = mk['Sidecar_Buy'].sum()
        extreme   = mk['Extreme_Day'].sum()
        days      = len(mk)

        monthly.append({
            '월':            month,
            '거래일수':       days,
            'KOSPI_누적수익(%)':  round(ks_ret, 2),
            'KOSDAQ_누적수익(%)': round(kq_ret, 2),
            'KOSPI_일간σ(%)':     round(ks_std, 2),
            'KOSPI_최대상승(%)':  round(ks_max, 2),
            'KOSPI_최대하락(%)':  round(ks_min, 2),
            '최대고저폭(%)':      round(ks_hl_max, 2),
            '급락일(매도사이드카추정)': int(sell_cnt),
            '급등일(매수사이드카추정)': int(buy_cnt),
            '극단변동일(4%이상)':   int(extreme),
        })

    df_monthly = pd.DataFrame(monthly)

    # ── 전체 기간 요약 ────────────────────────────────────────────
    ks_total_ret  = float((ks_26['Close'].iloc[-1] / ks_26['Close'].iloc[0] - 1) * 100)
    kq_total_ret  = float((kq_26['Close'].iloc[-1] / kq_26['Close'].iloc[0] - 1) * 100)
    total_days    = len(ks_26)
    annual_vol    = ks_26['Change_pct'].std() * (252 ** 0.5)
    max_drawdown  = ((ks_26['Close'] / ks_26['Close'].cummax()) - 1).min() * 100
    sell_total    = int(ks_26['Sidecar_Sell'].sum())
    buy_total     = int(ks_26['Sidecar_Buy'].sum())
    extreme_total = int(ks_26['Extreme_Day'].sum())

    # 변동성 레짐 분포
    high_vol_days    = int((ks_26['Vol_10d'] >= 2.0).sum())   # 10일σ ≥ 2%
    extreme_vol_days = int((ks_26['Vol_10d'] >= 2.5).sum())   # 10일σ ≥ 2.5%

    print('\n' + '=' * 65)
    print('📈 2026년 한국 증시 종합 결과')
    print('=' * 65)
    print(f'  분석 기간:          2026-01-02 ~ {ks_26.index[-1].strftime("%Y-%m-%d")} ({total_days}거래일)')
    print(f'  KOSPI 연초대비:     {ks_total_ret:+.2f}%')
    print(f'  KOSDAQ 연초대비:    {kq_total_ret:+.2f}%')
    print(f'  연환산 변동성(σ):   {annual_vol:.1f}%')
    print(f'  최대 낙폭(MDD):     {max_drawdown:.2f}%')
    print(f'  ─────────────────────────────────────────────────────')
    print(f'  급락일(매도사이드카 추정): {sell_total}일')
    print(f'  급등일(매수사이드카 추정): {buy_total}일')
    print(f'  고저폭 4% 이상 극단 변동일: {extreme_total}일')
    print(f'  고변동성 레짐(10일σ≥2%): {high_vol_days}일')
    print(f'  극단 레짐(10일σ≥2.5%): {extreme_vol_days}일')
    print('=' * 65)
    print('\n📅 월별 상세:')
    print(df_monthly.to_string(index=False))

    # ── 일별 상세 데이터 ──────────────────────────────────────────
    df_daily = ks_26[['Close','Change_pct','HL_Range_pct','Vol_10d','Vol_20d',
                       'Cum_Ret','Sidecar_Sell','Sidecar_Buy','Extreme_Day']].copy()
    df_daily.index.name = 'Date'
    df_daily = df_daily.reset_index()
    df_daily['Date'] = df_daily['Date'].dt.strftime('%Y-%m-%d')
    df_daily.columns = ['날짜','KOSPI종가','일간등락(%)','고저폭(%)','10일σ(%)','20일σ(%)',
                        '누적수익','매도사이드카추정','매수사이드카추정','극단변동일']
    for col in ['일간등락(%)','고저폭(%)','10일σ(%)','20일σ(%)','누적수익']:
        df_daily[col] = df_daily[col].round(2)

    # 요약 통계 데이터프레임
    df_summary = pd.DataFrame([
        {'항목': '분석 기간',              '값': f'2026-01-02 ~ {ks_26.index[-1].strftime("%Y-%m-%d")}'},
        {'항목': '총 거래일수',            '값': f'{total_days}일'},
        {'항목': 'KOSPI 연초대비 수익률',  '값': f'{ks_total_ret:+.2f}%'},
        {'항목': 'KOSDAQ 연초대비 수익률', '값': f'{kq_total_ret:+.2f}%'},
        {'항목': '연환산 변동성(σ)',        '값': f'{annual_vol:.1f}%'},
        {'항목': '최대 낙폭(MDD)',          '값': f'{max_drawdown:.2f}%'},
        {'항목': '급락일(매도사이드카 추정)','값': f'{sell_total}일'},
        {'항목': '급등일(매수사이드카 추정)','값': f'{buy_total}일'},
        {'항목': '고저폭 4% 이상 극단 변동일','값': f'{extreme_total}일'},
        {'항목': '고변동성 레짐(10일σ≥2%)일수','값': f'{high_vol_days}일'},
        {'항목': '극단 변동성 레짐(10일σ≥2.5%)일수','값': f'{extreme_vol_days}일'},
    ])

    # ── Drive 업로드 ──────────────────────────────────────────────
    try:
        svc = get_drive_service()
        upload(svc, df_summary, 'mkt2026_summary.csv')
        upload(svc, df_monthly, 'mkt2026_monthly.csv')
        upload(svc, df_daily,   'mkt2026_daily.csv')
        print('\n✅ 분석 완료 - Google Drive 업로드 성공')
    except Exception as e:
        print(f'\n⚠️ Drive 업로드 실패: {e}')
        df_summary.to_csv('mkt2026_summary.csv', index=False, encoding='utf-8-sig')
        df_monthly.to_csv('mkt2026_monthly.csv', index=False, encoding='utf-8-sig')
        df_daily.to_csv('mkt2026_daily.csv',     index=False, encoding='utf-8-sig')


if __name__ == '__main__':
    main()
