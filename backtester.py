import pandas as pd
import numpy as np
from itertools import product
import os
import sys
import time

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

def load_data(file_path):
    """
    HTS에서 다운로드한 CSV 데이터를 불러옵니다.
    필수 컬럼: Date, Open, High, Low, Close, Volume
    (경우에 따라 컬럼명이 한글일 수 있으므로 매핑 로직 추가)
    """
    if not os.path.exists(file_path):
        print(f"❌ 파일을 찾을 수 없습니다: {file_path}")
        return pd.DataFrame()
        
    df = pd.read_csv(file_path)
    
    # 일반적인 한글 컬럼명을 영문으로 자동 매핑
    rename_dict = {
        '일자': 'Date', '시간': 'Time', '일시': 'DateTime', '날짜': 'Date',
        '시가': 'Open', '고가': 'High', '저가': 'Low', '종가': 'Close', '현재가': 'Close', '거래량': 'Volume'
    }
    df.rename(columns=rename_dict, inplace=True)
    
    # 필수 컬럼 체크
    required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    for col in required_cols:
        if col not in df.columns:
            print(f"❌ 데이터에 필수 컬럼 '{col}'이(가) 없습니다. HTS 다운로드 설정을 확인하세요.")
            return pd.DataFrame()
            
    # DateTime 파싱 (Date 컬럼이 없으면 인덱스나 다른 조합으로 생성)
    if 'Date' not in df.columns and 'DateTime' in df.columns:
        df['DateTime'] = pd.to_datetime(df['DateTime'])
        df['Date'] = df['DateTime'].dt.date
    elif 'Date' in df.columns and 'Time' in df.columns:
        df['DateTime'] = pd.to_datetime(df['Date'].astype(str) + ' ' + df['Time'].astype(str))
        df['Date'] = df['DateTime'].dt.date
    elif 'Date' in df.columns:
        df['DateTime'] = pd.to_datetime(df['Date'])
        df['Date'] = df['DateTime'].dt.date
    else:
        # 가상의 Date 생성 (단일 거래일 가정)
        df['Date'] = pd.Timestamp.today().date()
        
    # 날짜순 정렬 (과거 -> 현재)
    df = df.sort_values(by='DateTime').reset_index(drop=True)
    
    # 숫자형 변환 (콤마 제거 등)
    for col in required_cols:
        if df[col].dtype == object:
            df[col] = df[col].astype(str).str.replace(',', '').astype(float)
            
    return df

def calculate_indicators(df, rsi_period=14, vol_lookback=10, vol_mult=2.5, atr_period=7):
    # MA 계산
    df['MA5'] = df['Close'].rolling(5).mean()
    df['MA20'] = df['Close'].rolling(20).mean()
    
    # VWAP
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3
    df['_tp_vol'] = typical_price * df['Volume']
    df['VWAP'] = df.groupby('Date')['_tp_vol'].cumsum() / df.groupby('Date')['Volume'].cumsum()
    df.drop(columns=['_tp_vol'], inplace=True)
    
    # RSI
    delta = df['Close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(rsi_period).mean()
    avg_loss = loss.rolling(rsi_period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + rs))
    df['RSI'] = df['RSI'].fillna(50)
    
    # Volume Surge
    avg_vol = df['Volume'].rolling(vol_lookback).mean().shift(1)
    df['Vol_Surge'] = df['Volume'] > (avg_vol * vol_mult)
    
    # ATR Scalp
    high = df['High'].values
    low = df['Low'].values
    close = df['Close'].values
    tr = np.maximum(high[1:] - low[1:], np.maximum(abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1])))
    tr = np.insert(tr, 0, high[0] - low[0])
    df['ATR'] = pd.Series(tr).rolling(atr_period).mean()
    
    return df

def run_backtest(df, take_profit_pct, atr_mult, time_stop_bars, fee_rate=0.00195):
    """
    fee_rate: 0.18%(거래세) + 0.015%(수수료) = 0.195% (0.00195)
    슬리피지를 고려하여 실제 수수료율을 살짝 더 높게 설정 가능.
    """
    df = df.copy()
    
    # 매수 기본 조건
    cond_vwap = df['Close'] > df['VWAP']
    cond_rsi = df['RSI'].between(30, 70)
    cond_vol = df['Vol_Surge']
    cond_ma = df['MA5'] > df['MA20']
    
    raw_buy_signal = cond_vwap & cond_rsi & cond_vol & cond_ma
    df['Buy_Trigger'] = raw_buy_signal.rolling(2).sum() == 2  # 2봉 연속
    
    # 동적 손절선 기준값
    df['Raw_SL'] = df['Close'] - atr_mult * df['ATR']
    
    trades = []
    in_position = False
    entry_price = 0.0
    entry_idx = 0
    current_sl = np.nan
    
    for i in range(len(df)):
        close_val = df['Close'].iloc[i]
        open_val = df['Open'].iloc[i]
        raw_sl = df['Raw_SL'].iloc[i]
        buy_trigger = df['Buy_Trigger'].iloc[i]
        
        if pd.isna(raw_sl):
            continue
            
        if in_position:
            # Trailing Stop
            if pd.isna(current_sl):
                current_sl = raw_sl
            else:
                current_sl = max(current_sl, raw_sl)
                
            hit_stop = (close_val < current_sl)
            hit_tp = ((close_val - entry_price) / entry_price * 100) >= take_profit_pct
            hit_time = (i - entry_idx) >= time_stop_bars
            
            if hit_stop or hit_tp or hit_time:
                exit_price = close_val
                # 수익률 계산 (매도금액 - 매수금액) / 매수금액 - 수수료/세금
                raw_return = (exit_price - entry_price) / entry_price
                net_return = raw_return - fee_rate
                
                reason = "익절(TP)" if hit_tp else ("시간컷(Time)" if hit_time else "트레일링 손절(SL)")
                
                trades.append({
                    'entry_idx': entry_idx,
                    'exit_idx': i,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'net_return_pct': net_return * 100,
                    'reason': reason
                })
                in_position = False
                current_sl = np.nan
        else:
            if buy_trigger:
                in_position = True
                entry_price = close_val
                entry_idx = i
                current_sl = raw_sl
                
    # 통계 계산
    if len(trades) == 0:
        return {
            'total_trades': 0, 'win_rate': 0.0, 'total_return': 0.0, 'mdd': 0.0, 'avg_profit': 0.0
        }
        
    trades_df = pd.DataFrame(trades)
    winning_trades = trades_df[trades_df['net_return_pct'] > 0]
    
    total_trades = len(trades_df)
    win_rate = (len(winning_trades) / total_trades) * 100
    
    # 단리 누적 수익률 가정 (복리로 계산시: (1 + pct/100).prod() - 1)
    total_return = trades_df['net_return_pct'].sum()
    avg_profit = trades_df['net_return_pct'].mean()
    
    # 간단한 MDD 계산 (자산 곡선 기반)
    cumulative_returns = (1 + trades_df['net_return_pct'] / 100).cumprod()
    peak = cumulative_returns.cummax()
    drawdown = (cumulative_returns - peak) / peak * 100
    mdd = drawdown.min()
    
    return {
        'total_trades': total_trades,
        'win_rate': win_rate,
        'total_return': total_return,
        'mdd': mdd,
        'avg_profit': avg_profit
    }

def optimize_strategy(file_path):
    print("="*60)
    print("🚀 스캘핑 로직 백테스팅 및 파라미터 최적화 (Grid Search)")
    print("="*60)
    
    df = load_data(file_path)
    if df.empty:
        return
        
    print(f"✅ 데이터 로드 완료: 총 {len(df)} 캔들 (기간: {df['Date'].iloc[0]} ~ {df['Date'].iloc[-1]})")
    
    # 보조지표를 미리 한 번만 계산해두면 속도가 매우 빠름 (거래량 승수는 고정)
    df = calculate_indicators(df, rsi_period=14, vol_lookback=10, vol_mult=2.5, atr_period=7)
    
    # 테스트할 파라미터 조합 (Grid)
    tp_pcts = [0.5, 1.0, 1.5, 2.0]
    atr_mults = [1.0, 1.3, 1.5, 2.0]
    time_stops = [10, 20, 30]
    
    print("\n⏳ 최적화 시뮬레이션을 시작합니다...")
    start_time = time.time()
    
    results = []
    
    for tp, atr, ts in product(tp_pcts, atr_mults, time_stops):
        stats = run_backtest(df, take_profit_pct=tp, atr_mult=atr, time_stop_bars=ts)
        
        # 유의미한 거래 횟수 필터 (최소 10회 이상)
        if stats['total_trades'] >= 10:
            results.append({
                'TP(%)': tp,
                'ATR_Mult': atr,
                'TimeStop': ts,
                'Trades': stats['total_trades'],
                'WinRate(%)': round(stats['win_rate'], 2),
                'TotalReturn(%)': round(stats['total_return'], 2),
                'MDD(%)': round(stats['mdd'], 2),
                'AvgProfit(%)': round(stats['avg_profit'], 2)
            })
            
    res_df = pd.DataFrame(results)
    
    if res_df.empty:
        print("\n❌ 조건에 맞는 매매가 발생하지 않았거나 유의미한 결과(최소 10회 거래)가 없습니다.")
        return
        
    # 총 수익률 기준으로 내림차순 정렬
    res_df = res_df.sort_values(by='TotalReturn(%)', ascending=False).reset_index(drop=True)
    
    elapsed = time.time() - start_time
    print(f"\n✅ 최적화 완료! (소요 시간: {elapsed:.2f}초)")
    
    print("\n🏆 최적의 파라미터 TOP 5 (수익률 순):")
    print(res_df.head(5).to_string(index=False))
    
    print("\n💡 [권장 행동]:")
    print("위 표에서 'TotalReturn'과 'WinRate'가 가장 밸런스 좋은 조합을 찾으세요.")
    print("결정한 값을 app.py 의 calculate_intraday_signals() 내부에 적용하시면 됩니다.")

if __name__ == "__main__":
    # 실행 방법 안내
    print("\n[사용 방법 안내]")
    print("1. 영웅문 등 HTS에서 분석하고자 하는 종목의 '1분봉' 또는 '5분봉' 차트를 띄웁니다.")
    print("2. 마우스 우클릭 -> '데이터 저장' 또는 '엑셀로 보내기'를 선택하여 CSV 파일로 저장합니다.")
    print("3. 저장한 파일을 이 파이썬 스크립트와 같은 폴더에 넣고 아래에 파일명을 입력하세요.")
    
    # 예시: user_data.csv 가 있다고 가정
    sample_file = "sample_data.csv"
    if not os.path.exists(sample_file):
        print("\n⚠️ 현재 sample_data.csv 파일이 없습니다. (위 가이드 참조)")
        # 더미 데이터 생성 시연용 코드
        print("시연을 위해 임의의 가상 데이터를 생성하여 테스트합니다...\n")
        
        dates = pd.date_range("2024-01-01 09:00", periods=2000, freq="1min")
        dummy_df = pd.DataFrame({
            "DateTime": dates,
            "Open": np.random.normal(10000, 50, 2000).cumsum(),
            "High": 0, "Low": 0, "Close": 0, "Volume": np.random.randint(100, 10000, 2000)
        })
        dummy_df["High"] = dummy_df["Open"] + np.random.randint(10, 100, 2000)
        dummy_df["Low"] = dummy_df["Open"] - np.random.randint(10, 100, 2000)
        dummy_df["Close"] = dummy_df["Open"] + np.random.randint(-50, 50, 2000)
        
        # 억지 상승장 조성 (시그널 확인용)
        dummy_df["Close"] += np.arange(2000) * 2
        
        dummy_df.to_csv(sample_file, index=False)
        
    optimize_strategy(sample_file)
