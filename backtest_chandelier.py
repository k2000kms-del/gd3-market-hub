# -*- coding: utf-8 -*-
"""
GD 3.0 Market Hub - Chandelier Exit 동적 ATR 변동성 조절 전략 5개년 백테스트
[목적] 대시보드에 적용된 Chandelier Exit 손절선 및 MA5/20 돌파 매수 전략의 5개년 성과를 검증합니다.
[기간] 2021-06-29 ~ 2026-06-29 (5년)
"""

import os
import pandas as pd
import numpy as np
import FinanceDataReader as fdr
from datetime import datetime

def main():
    print("=" * 70)
    print("📊 Chandelier Exit 동적 ATR 전략 5개년 백테스트 실행")
    print(f"   실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 1. 코스닥 시총 상위 종목 수집 및 필터링
    print("\n📋 코스닥 상위 50개 종목 정보 수집 중...")
    df_kq = fdr.StockListing('KOSDAQ')
    junk = '스팩|SPAC|ETN|ETF|제[0-9]+호|우$|우[A-Z]$|리츠|인프라'
    df_kq = df_kq[~df_kq['Name'].str.contains(junk, regex=True, na=False)]
    df_kq['Marcap'] = pd.to_numeric(df_kq['Marcap'], errors='coerce').fillna(0)
    
    top_50 = df_kq.nlargest(50, 'Marcap')
    codes = list(top_50['Code'].astype(str).str.zfill(6).unique())
    code_to_name = dict(zip(top_50['Code'].astype(str).str.zfill(6), top_50['Name']))
    print(f"  → 백테스트 대상 종목: {len(codes)}개 선정 완료")

    # 2. 백테스팅 설정
    start_date = '2021-01-01'  # 지표 계산용 마진 포함
    end_date = '2026-06-29'
    target_start_date = pd.to_datetime('2021-06-29')

    all_trades = []
    stock_summaries = []

    print("\n📈 종목별 과거 데이터 수집 및 시뮬레이션 진행 중...")
    for i, code in enumerate(codes):
        name = code_to_name[code]
        try:
            df = fdr.DataReader(code, start_date, end_date)
            if df.empty or len(df) < 150:
                print(f"  [{code}] {name:15s} | ⚠️ 데이터 부족으로 스킵")
                continue
        except Exception as e:
            print(f"  [{code}] {name:15s} | ⚠️ 데이터 수집 실패: {e}")
            continue

        # 기술적 지표 계산 (MA5, MA20)
        df['MA5'] = df['Close'].rolling(5).mean()
        df['MA20'] = df['Close'].rolling(20).mean()

        # ATR 14일 계산
        high = df['High'].values
        low = df['Low'].values
        close = df['Close'].values
        tr = np.maximum(high[1:] - low[1:], np.maximum(abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1])))
        tr = np.insert(tr, 0, high[0] - low[0])
        df['ATR'] = pd.Series(tr, index=df.index).rolling(14).mean()

        # 20일 평균 거래량
        df['Vol_MA20'] = df['Volume'].rolling(20).mean()

        # 피뢰침(위꼬리) 조건 정의: 위꼬리 비율이 전체 봉 길이의 40% 이상이고 음봉인 경우
        candle_range = df['High'] - df['Low']
        candle_range_safe = np.where(candle_range == 0, 1.0, candle_range)
        upper_wick = df['High'] - np.maximum(df['Open'], df['Close'])
        is_pinbar = ((upper_wick / candle_range_safe) > 0.4) & (df['Close'] <= df['Open'])

        # 거래량 폭발 조건: 거래량이 최근 20일 평균 거래량의 1.5배 이상
        is_vol_spike = df['Volume'] > (df['Vol_MA20'].fillna(df['Volume']) * 1.5)

        # 리스크 가속 조건 (대량거래량 피뢰침 또는 대량거래량 음봉)
        risk_accelerate = is_vol_spike & (is_pinbar | (df['Close'] < df['Open']))

        # 동적 ATR 승수 적용 (위험 관리 극대화 시 승수를 2.5 -> 1.0으로 축소)
        atr_multiplier = np.where(risk_accelerate, 1.0, 2.5)

        # 최고가 계산 시 고가 왜곡 방지 (대량거래 피뢰침 날은 High 대신 Close 적용)
        adjusted_high = np.where(is_pinbar & is_vol_spike, df['Close'], df['High'])
        df['Adj_Highest_High'] = pd.Series(adjusted_high, index=df.index).rolling(20).max()

        # 동적 ATR 손절선 계산
        df['dynamic_raw_sl'] = df['Adj_Highest_High'] - atr_multiplier * df['ATR']

        # 백테스트 구간 필터링
        df_bt = df[df.index >= target_start_date].copy()
        if df_bt.empty:
            continue

        # 시뮬레이션 루프
        in_position = False
        entry_price = 0.0
        entry_date = None
        max_price_since_entry = 0.0
        current_sl = np.nan
        prev_sl = np.nan

        trades = []
        df_indices = df.index.get_indexer(df_bt.index)

        for idx_in_df in df_indices:
            date = df.index[idx_in_df]
            row = df.iloc[idx_in_df]

            close_val = row['Close']
            open_val = row['Open']
            ma5_val = row['MA5']
            ma20_val = row['MA20']
            raw_sl = row['dynamic_raw_sl']

            if pd.isna(raw_sl) or pd.isna(ma5_val) or pd.isna(ma20_val):
                continue

            if in_position:
                max_price_since_entry = max(max_price_since_entry, close_val)

                # 손절선 래칫 (위로만 이동)
                current_sl = max(current_sl, raw_sl)

                # 본전 보호 룰 (10% 이상 수익 시 본전+1% 확보)
                if max_price_since_entry >= entry_price * 1.10:
                    current_sl = max(current_sl, entry_price * 1.01)

                # 매도 판단
                # 1) 시가 갭하락 손절: 시가가 전일 기준 손절선을 하회하여 급락 출발 시 청산
                if not pd.isna(prev_sl) and open_val < prev_sl:
                    exit_price = open_val
                    pnl = (exit_price - entry_price) / entry_price * 100
                    trades.append({
                        'Code': code,
                        'Name': name,
                        'Entry_Date': entry_date.strftime('%Y-%m-%d'),
                        'Exit_Date': date.strftime('%Y-%m-%d'),
                        'Entry_Price': int(entry_price),
                        'Exit_Price': int(exit_price),
                        'Return': round(pnl, 2),
                        'Exit_Reason': 'Gap-down Exit'
                    })
                    in_position = False
                    current_sl = np.nan
                    prev_sl = np.nan
                # 2) 일반 종가 이탈 손절
                elif close_val < current_sl:
                    exit_price = close_val
                    pnl = (exit_price - entry_price) / entry_price * 100
                    trades.append({
                        'Code': code,
                        'Name': name,
                        'Entry_Date': entry_date.strftime('%Y-%m-%d'),
                        'Exit_Date': date.strftime('%Y-%m-%d'),
                        'Entry_Price': int(entry_price),
                        'Exit_Price': int(exit_price),
                        'Return': round(pnl, 2),
                        'Exit_Reason': 'Chandelier Exit'
                    })
                    in_position = False
                    current_sl = np.nan
                    prev_sl = np.nan
                else:
                    prev_sl = current_sl
            else:
                # 매수 판단: 상승 추세(MA5 및 MA20 상회) 진입 시 매수
                if close_val > ma5_val and close_val > ma20_val:
                    in_position = True
                    entry_price = close_val
                    entry_date = date
                    max_price_since_entry = close_val
                    current_sl = raw_sl
                    prev_sl = raw_sl

        # 백테스트 종료 시 보유 중인 종목 강제 청산
        if in_position:
            last_row = df_bt.iloc[-1]
            exit_price = last_row['Close']
            pnl = (exit_price - entry_price) / entry_price * 100
            trades.append({
                'Code': code,
                'Name': name,
                'Entry_Date': entry_date.strftime('%Y-%m-%d'),
                'Exit_Date': df_bt.index[-1].strftime('%Y-%m-%d'),
                'Entry_Price': int(entry_price),
                'Exit_Price': int(exit_price),
                'Return': round(pnl, 2),
                'Exit_Reason': 'Holding Force Exit'
            })

        all_trades.extend(trades)

        # 단순 보유 수익률 계산
        bh_return = (df_bt['Close'].iloc[-1] - df_bt['Close'].iloc[0]) / df_bt['Close'].iloc[0] * 100

        # 개별 종목 성과 지표 산출
        if trades:
            pnl_series = [t['Return'] for t in trades]
            win_trades = sum(1 for p in pnl_series if p > 0)
            win_rate = win_trades / len(trades) * 100
            avg_ret = np.mean(pnl_series)
            cum_ret = np.prod([1 + p/100 for p in pnl_series]) - 1
            cum_ret_percent = cum_ret * 100
        else:
            win_rate = 0.0
            avg_ret = 0.0
            cum_ret_percent = 0.0

        stock_summaries.append({
            'Code': code,
            'Name': name,
            'Total_Trades': len(trades),
            'Win_Rate': round(win_rate, 2),
            'Avg_Return': round(avg_ret, 2),
            'Strategy_Cum_Return': round(cum_ret_percent, 2),
            'Buy_Hold_Return': round(bh_return, 2)
        })

        if (i + 1) % 10 == 0:
            print(f"  → {i+1}/50개 종목 완료...")

    # 3. 데이터프레임 변환 및 전체 결과 집계
    df_trades = pd.DataFrame(all_trades)
    df_stocks = pd.DataFrame(stock_summaries)

    # 코스닥 지수 수익률 벤치마크 계산
    try:
        df_kq_idx = fdr.DataReader('KQ11', '2021-06-29', end_date)
        kq_idx_return = (df_kq_idx['Close'].iloc[-1] - df_kq_idx['Close'].iloc[0]) / df_kq_idx['Close'].iloc[0] * 100
    except:
        kq_idx_return = 0.0

    total_trades = len(df_trades)
    avg_win_rate = df_stocks['Win_Rate'].mean()
    avg_trade_return = df_trades['Return'].mean() if not df_trades.empty else 0.0
    avg_strat_return = df_stocks['Strategy_Cum_Return'].mean()
    avg_bh_return = df_stocks['Buy_Hold_Return'].mean()
    
    # 최고/최저 성과 종목 추출
    best_stock = df_stocks.loc[df_stocks['Strategy_Cum_Return'].idxmax()]
    worst_stock = df_stocks.loc[df_stocks['Strategy_Cum_Return'].idxmin()]

    print("\n" + "=" * 70)
    print("📊 5개년 (2021-06-29 ~ 2026-06-29) 백테스트 종합 결과")
    print("=" * 70)
    print(f"  대상 자산:           코스닥 시가총액 상위 50개 종목")
    print(f"  총 거래 횟수:        {total_trades}회 (종목당 평균 {total_trades/50:.1f}회)")
    print(f"  평균 거래 승률:      {avg_win_rate:.2f}%")
    print(f"  평균 1회 거래 수익:  {avg_trade_return:+.2f}%")
    print(f"  ───────────────────────────────────────────")
    print(f"  전략 평균 누적 수익: {avg_strat_return:+.2f}%")
    print(f"  동일 종목 단순 보유: {avg_bh_return:+.2f}%")
    print(f"  코스닥 지수 등락률: {kq_idx_return:+.2f}%")
    print(f"  ───────────────────────────────────────────")
    print(f"  최고 성과 종목:      {best_stock['Name']} ({best_stock['Strategy_Cum_Return']:+.2f}%)")
    print(f"  최저 성과 종목:      {worst_stock['Name']} ({worst_stock['Strategy_Cum_Return']:+.2f}%)")
    print("=" * 70)

    # 요약 정보 테이블화
    df_summary = pd.DataFrame([
        {'항목': '테스트 기간', '값': '2021-06-29 ~ 2026-06-29 (5년)'},
        {'항목': '대상 자산군', '값': '코스닥 시가총액 상위 50개 종목'},
        {'항목': '총 거래 횟수', '값': f"{total_trades}회 (종목당 평균 {total_trades/50:.1f}회)"},
        {'항목': '평균 거래 승률', '값': f"{avg_win_rate:.2f}%"},
        {'항목': '평균 1회 거래 수익률', '값': f"{avg_trade_return:+.2f}%"},
        {'항목': '전략 평균 누적 수익률', '값': f"{avg_strat_return:+.2f}%"},
        {'항목': '대상 종목 단순 보유 수익률', '값': f"{avg_bh_return:+.2f}%"},
        {'항목': '동기간 코스닥 지수 수익률', '값': f"{kq_idx_return:+.2f}%"},
        {'항목': '최고 성과 종목', '값': f"{best_stock['Name']} ({best_stock['Strategy_Cum_Return']:+.2f}%)"},
        {'항목': '최저 성과 종목', '값': f"{worst_stock['Name']} ({worst_stock['Strategy_Cum_Return']:+.2f}%)"}
    ])

    # CSV 저장
    df_summary.to_csv('bt_chandelier_summary.csv', index=False, encoding='utf-8-sig')
    df_stocks.to_csv('bt_chandelier_stocks.csv', index=False, encoding='utf-8-sig')
    if not df_trades.empty:
        df_trades.to_csv('bt_chandelier_trades.csv', index=False, encoding='utf-8-sig')
    
    print("\n✅ 백테스트 완료! CSV 결과 파일이 저장되었습니다.")

if __name__ == '__main__':
    main()
