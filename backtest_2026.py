# -*- coding: utf-8 -*-
"""
GD 3.0 Market Hub - 2026년 퀀트 스코어 백테스트
[목적] 선행 매수 타이밍 포착 스크리너의 실제 성과를 검증합니다.
[기간] 2026-01-02 ~ 2026-06-06
[주의] Score_Supply(수급)는 KIS API 과거 이력 불가로 중립값(15점) 고정.
       나머지 4개 점수는 실제 히스토리컬 데이터로 계산합니다.
"""

import os
import json
import pandas as pd
import numpy as np
import FinanceDataReader as fdr
from datetime import datetime, timedelta
from io import BytesIO
import time

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.credentials import Credentials


# ── Google Drive 연결 ──────────────────────────────────────────────
def get_drive_service():
    token_info = json.loads(os.environ.get('GDRIVE_OAUTH_TOKEN', '{}'))
    creds = Credentials.from_authorized_user_info(
        token_info, scopes=['https://www.googleapis.com/auth/drive']
    )
    return build('drive', 'v3', credentials=creds)


def upload_to_drive(service, df, filename):
    csv_bytes = df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
    media = MediaIoBaseUpload(BytesIO(csv_bytes), mimetype='text/csv', resumable=False)
    f = service.files().create(
        body={'name': filename}, media_body=media, fields='id'
    ).execute()
    print(f'  ✅ {filename} → Drive 업로드 완료 (ID: {f.get("id")})')


# ── 점수 계산 함수들 ───────────────────────────────────────────────
def score_ma(df_s):
    """이평선 추세 점수 (최대 15점)"""
    if len(df_s) < 5:
        return 7.5
    ma5  = df_s['Close'].rolling(5).mean().iloc[-1]
    ma20 = df_s['Close'].rolling(20).mean().iloc[-1] if len(df_s) >= 20 else ma5
    ma60 = df_s['Close'].rolling(60).mean().iloc[-1] if len(df_s) >= 60 else ma20
    c    = df_s['Close'].iloc[-1]

    if   c > ma5 > ma20 and ma20 > ma60: s = 15.0
    elif c > ma5 > ma20:                 s = 13.0
    elif c > ma5 and c > ma20:           s = 12.0
    elif c > ma5:                        s = 9.0
    elif c > ma20:                       s = 7.0
    else:                                s = 0.0

    if c <= ma60: s = min(8.0, s)
    if ma20 > 0 and (c / ma20) * 100 >= 115: s -= 4.0
    if ma20 > 0 and abs(ma5 - ma20) / ma20 <= 0.03 and c > ma5 and c > ma20: s += 2.0
    return min(15.0, max(0.0, s))


def score_candle(df_s):
    """캔들 시그널 점수 (최대 15점)"""
    if len(df_s) < 2:
        return 7.5
    o = float(df_s['Open'].iloc[-1])
    h = float(df_s['High'].iloc[-1])
    l = float(df_s['Low'].iloc[-1])
    c = float(df_s['Close'].iloc[-1])
    pc = float(df_s['Close'].iloc[-2])

    if h == l:
        return 15.0 if c > pc else 0.0
    body = c - o
    rng  = h - l
    ls   = min(o, c) - l
    us   = h - max(o, c)
    is_doji = (abs(body) / o <= 0.002) if o > 0 else (body == 0)

    if is_doji:
        return 10.0 if ls > rng * 0.5 else 5.0
    elif body > 0:
        if ls > body * 0.5: return 15.0
        if us > body and (body / o >= 0.005): return 8.0
        if us > body * 2: return 8.0
        return 12.0
    else:
        return 8.0 if ls > abs(body) * 1.5 else 0.0


def score_volume(df_s):
    """거래대금 증가율 점수 (최대 20점, 10억 미만 소외주 제한)"""
    if len(df_s) < 5:
        return 10.0
    df_s = df_s.copy()
    df_s['Amt'] = df_s['Close'] * df_s['Volume']
    today_amt = df_s['Amt'].iloc[-1]
    avg_amt   = df_s['Amt'].iloc[max(0, len(df_s)-21):len(df_s)-1].mean()

    if today_amt < 1_000_000_000:
        return min(5, (today_amt / 1_000_000_000) * 5)
    ratio = today_amt / avg_amt if avg_amt > 0 else 1.0
    return min(20, max(0, (ratio - 1.0) * 10 + 10))


def score_momentum(df_s, chg_1d):
    """가격 모멘텀 점수 (당일 10점 + 5일 누적 10점)"""
    s_day = min(10, max(0, chg_1d * 1 + 5))
    if len(df_s) >= 6:
        p5  = float(df_s['Close'].iloc[-6])
        now = float(df_s['Close'].iloc[-1])
        c5d = ((now - p5) / p5 * 100) if p5 > 0 else 0
        s5d = min(10, max(0, c5d * 0.5 + 5))
    else:
        s5d = 5.0
    return min(20, max(0, s_day + s5d))


def get_market_penalty(idx_ks, idx_kq, date):
    """시장 국면에 따른 점수 패널티 계수 반환"""
    try:
        ks = idx_ks[idx_ks.index.date == date]
        kq = idx_kq[idx_kq.index.date == date]
        if ks.empty or kq.empty:
            return 1.0, '중립'
        avg = (float(ks['Change'].iloc[0]) + float(kq['Change'].iloc[0])) / 2 * 100
        if   avg <= -1.5: return 0.8, f'급락({avg:.1f}%)'
        elif avg <= -0.5: return 0.9, f'약세({avg:.1f}%)'
        elif avg >=  1.0: return 1.0, f'강세({avg:.1f}%)'
        else:             return 1.0, f'중립({avg:.1f}%)'
    except:
        return 1.0, '중립'


# ── 메인 백테스트 ────────────────────────────────────────────────
def main():
    print('=' * 60)
    print('📊 GD 3.0 Market Hub - 2026년 백테스트 시작')
    print(f'   실행 시각: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 60)

    # 1. 종목 유니버스 (시총 상위 200개, 500억 이상)
    print('\n📋 종목 유니버스 수집 중...')
    df_ks  = fdr.StockListing('KOSPI')
    df_kq  = fdr.StockListing('KOSDAQ')
    df_all = pd.concat([df_ks, df_kq], ignore_index=True)
    df_all = df_all.rename(columns={'Symbol': 'Code', 'ChagesRatio': 'ChagesRatio'})

    junk = '스팩|SPAC|ETN|ETF|제[0-9]+호|우$|우[A-Z]$|리츠|인프라'
    if 'Name' in df_all.columns:
        df_all = df_all[~df_all['Name'].str.contains(junk, regex=True, na=False)]
    for col in ['Volume', 'Amount', 'Marcap']:
        if col in df_all.columns:
            df_all[col] = pd.to_numeric(df_all[col], errors='coerce').fillna(0)
    if 'Volume'  in df_all.columns: df_all = df_all[df_all['Volume'] > 0]
    if 'Marcap'  in df_all.columns: df_all = df_all[df_all['Marcap'] >= 50_000_000_000]

    universe = df_all.nlargest(200, 'Marcap') if 'Marcap' in df_all.columns else df_all.head(200)
    codes    = list(universe['Code'].astype(str).str.zfill(6).unique())
    print(f'  → 유니버스: {len(codes)}개 종목')

    # 2. 가격 이력 사전 수집 (MA60 확보를 위해 2025-09-01부터)
    print('\n📈 가격 이력 수집 중 (약 5~10분 소요)...')
    hist_start = '2025-09-01'
    price_db   = {}
    for i, code in enumerate(codes):
        try:
            df_h = fdr.DataReader(code, hist_start)
            if not df_h.empty:
                price_db[code] = df_h
        except:
            pass
        if (i + 1) % 25 == 0:
            print(f'  → {i+1}/{len(codes)} 완료...')
        time.sleep(0.05)
    print(f'  → {len(price_db)}개 종목 데이터 수집 완료')

    # 3. 지수 데이터 (시장 국면 + 벤치마크)
    print('\n📉 지수 데이터 수집 중...')
    idx_ks = fdr.DataReader('KS11', hist_start)
    idx_kq = fdr.DataReader('KQ11', hist_start)

    # 4. 백테스트 실행
    print('\n🧪 백테스트 실행 중...')
    bt_start = datetime(2026, 1, 2).date()
    bt_end   = datetime(2026, 6, 6).date()
    tdays    = [d.date() for d in idx_ks.index if bt_start <= d.date() <= bt_end]

    daily_results = []
    stock_results = []  # 종목별 상세 기록

    for ti, today in enumerate(tdays):
        penalty, mkt_cond = get_market_penalty(idx_ks, idx_kq, today)
        day_scores = []

        for code, df_hist in price_db.items():
            df_s = df_hist[df_hist.index.date <= today]
            if df_s.empty or df_s.index.date[-1] != today or len(df_s) < 5:
                continue

            c    = float(df_s['Close'].iloc[-1])
            vol  = float(df_s['Volume'].iloc[-1] if 'Volume' in df_s.columns else 0)
            amt  = c * vol
            if amt < 1_000_000_000:
                continue  # 10억 미만 소외주 제외

            pc   = float(df_s['Close'].iloc[-2]) if len(df_s) >= 2 else c
            chg  = ((c - pc) / pc * 100) if pc > 0 else 0

            sm  = score_momentum(df_s, chg)
            ss  = 15.0  # 수급: KIS API 불가 → 중립값 고정
            sv  = score_volume(df_s)
            sma = score_ma(df_s)
            sc  = score_candle(df_s)

            # 이중 신호 보정
            if sv >= 15 and sm >= 15:
                sv = max(15, sv - (sv - 15) * 0.4)
                sm = max(15, sm - (sm - 15) * 0.4)

            total = round((sm + ss + sv + sma + sc) * penalty, 1)

            day_scores.append({
                'Date': today.strftime('%Y-%m-%d'),
                'Code': code,
                'Close': c,
                'Total_Score': total,
                'Score_Momentum': round(sm, 1),
                'Score_Volume':   round(sv, 1),
                'Score_MA':       round(sma, 1),
                'Score_Candle':   round(sc, 1),
                'Market_Condition': mkt_cond,
            })

        if not day_scores:
            continue

        top10 = pd.DataFrame(day_scores).nlargest(10, 'Total_Score')

        # 5일 후 수익률 계산
        fi = ti + 5
        if fi >= len(tdays):
            continue
        fdate = tdays[fi]

        rets = []
        for _, r in top10.iterrows():
            df_h = price_db.get(r['Code'])
            if df_h is None:
                continue
            fr = df_h[df_h.index.date == fdate]
            if fr.empty:
                continue
            ret = ((float(fr['Close'].iloc[0]) - r['Close']) / r['Close'] * 100) if r['Close'] > 0 else 0
            rets.append(ret)
            stock_results.append({**r.to_dict(), 'Return_5d': round(ret, 2), 'Future_Date': fdate.strftime('%Y-%m-%d')})

        if not rets:
            continue

        # KOSPI 벤치마크
        ks_t = idx_ks[idx_ks.index.date == today]
        ks_f = idx_ks[idx_ks.index.date == fdate]
        kospi_ret = ((float(ks_f['Close'].iloc[0]) - float(ks_t['Close'].iloc[0])) /
                     float(ks_t['Close'].iloc[0]) * 100) if (not ks_t.empty and not ks_f.empty) else 0

        avg_ret    = np.mean(rets)
        excess_ret = avg_ret - kospi_ret

        daily_results.append({
            'Date':             today.strftime('%Y-%m-%d'),
            'Top10':            ','.join(top10['Code'].tolist()),
            'Avg_Return_5d':    round(avg_ret, 2),
            'KOSPI_Return_5d':  round(kospi_ret, 2),
            'Excess_Return':    round(excess_ret, 2),
            'Win':              1 if avg_ret > 0 else 0,
            'Beat_Market':      1 if excess_ret > 0 else 0,
            'Candidates':       len(day_scores),
            'Market_Condition': mkt_cond,
        })

        if (ti + 1) % 10 == 0:
            print(f'  → {ti+1}/{len(tdays)}일 완료 | 평균 수익: {avg_ret:+.2f}% | 초과: {excess_ret:+.2f}%')

    # 5. 결과 요약 출력
    df_daily   = pd.DataFrame(daily_results)
    df_stocks  = pd.DataFrame(stock_results)

    if df_daily.empty:
        print('❌ 백테스트 결과 없음')
        return

    win_rate    = df_daily['Win'].mean() * 100
    beat_rate   = df_daily['Beat_Market'].mean() * 100
    avg_ret     = df_daily['Avg_Return_5d'].mean()
    avg_kospi   = df_daily['KOSPI_Return_5d'].mean()
    avg_excess  = df_daily['Excess_Return'].mean()
    ir          = avg_excess / df_daily['Excess_Return'].std() if df_daily['Excess_Return'].std() > 0 else 0

    print('\n' + '=' * 60)
    print('📊 2026년 백테스트 결과 요약')
    print('=' * 60)
    print(f"  테스트 기간:        2026-01-02 ~ 2026-06-06")
    print(f"  총 테스트 일수:     {len(df_daily)}거래일")
    print(f"  종목 유니버스:      {len(price_db)}개")
    print(f"  ─────────────────────────────────────────")
    print(f"  평균 5일 수익률:    {avg_ret:+.2f}%")
    print(f"  KOSPI 5일 수익률:  {avg_kospi:+.2f}%")
    print(f"  평균 초과 수익률:   {avg_excess:+.2f}%")
    print(f"  ─────────────────────────────────────────")
    print(f"  수익 달성 비율:     {win_rate:.1f}%")
    print(f"  시장 초과 비율:     {beat_rate:.1f}%")
    print(f"  최고 5일 수익률:    {df_daily['Avg_Return_5d'].max():+.2f}%")
    print(f"  최저 5일 수익률:    {df_daily['Avg_Return_5d'].min():+.2f}%")
    print(f"  수익률 표준편차:    {df_daily['Avg_Return_5d'].std():.2f}%")
    print(f"  정보 비율 (IR):     {ir:.2f}")
    print('=' * 60)

    # 요약 데이터프레임
    df_summary = pd.DataFrame([
        {'항목': '테스트 기간',              '값': '2026-01-02 ~ 2026-06-06'},
        {'항목': '총 테스트 거래일',          '값': f'{len(df_daily)}일'},
        {'항목': '종목 유니버스',             '값': f'{len(price_db)}개'},
        {'항목': '평균 5일 수익률 (TOP10)',   '값': f'{avg_ret:+.2f}%'},
        {'항목': 'KOSPI 동기간 평균 수익률',  '값': f'{avg_kospi:+.2f}%'},
        {'항목': '평균 초과 수익률 (알파)',    '값': f'{avg_excess:+.2f}%'},
        {'항목': '5일 수익률 양봉 비율',      '값': f'{win_rate:.1f}%'},
        {'항목': '시장 초과 달성 비율',        '값': f'{beat_rate:.1f}%'},
        {'항목': '최고 5일 수익률',           '값': f'{df_daily["Avg_Return_5d"].max():+.2f}%'},
        {'항목': '최저 5일 수익률',           '값': f'{df_daily["Avg_Return_5d"].min():+.2f}%'},
        {'항목': '수익률 표준편차',            '값': f'{df_daily["Avg_Return_5d"].std():.2f}%'},
        {'항목': '정보 비율 (IR)',             '값': f'{ir:.2f}'},
    ])

    # 6. Google Drive 업로드
    try:
        service = get_drive_service()
        upload_to_drive(service, df_summary, 'bt2026_summary.csv')
        upload_to_drive(service, df_daily,   'bt2026_daily.csv')
        upload_to_drive(service, df_stocks,  'bt2026_stocks.csv')
    except Exception as e:
        print(f'\n⚠️ Drive 업로드 실패: {e}')
        df_summary.to_csv('bt2026_summary.csv', index=False, encoding='utf-8-sig')
        df_daily.to_csv('bt2026_daily.csv',     index=False, encoding='utf-8-sig')
        df_stocks.to_csv('bt2026_stocks.csv',   index=False, encoding='utf-8-sig')

    print('\n✅ 백테스트 완료!')


if __name__ == '__main__':
    main()
