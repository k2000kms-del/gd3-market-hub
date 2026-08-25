import pandas as pd
import numpy as np
import FinanceDataReader as fdr

code = "402340"
start = "2025-06-01"
df_candle = fdr.DataReader(code, start)

# MA 계산
df_candle['MA5']  = df_candle['Close'].rolling(5).mean()
df_candle['MA20'] = df_candle['Close'].rolling(20).mean()

# ATR 14
high = df_candle['High'].values
low = df_candle['Low'].values
close = df_candle['Close'].values
tr = np.maximum(high[1:] - low[1:], np.maximum(abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1])))
tr = np.insert(tr, 0, high[0] - low[0])
df_candle['ATR'] = pd.Series(tr).rolling(14).mean().values

# 리스크 가속 조건
df_candle['Vol_MA20'] = df_candle['Volume'].rolling(20).mean()
candle_range = df_candle['High'] - df_candle['Low']
candle_range_safe = np.where(candle_range == 0, 1.0, candle_range)
upper_wick = df_candle['High'] - np.maximum(df_candle['Open'], df_candle['Close'])
is_pinbar = ((upper_wick / candle_range_safe) > 0.4) & (df_candle['Close'] <= df_candle['Open'])
is_vol_spike = df_candle['Volume'] > (df_candle['Vol_MA20'].fillna(df_candle['Volume']) * 1.5)
risk_accelerate = is_vol_spike & (is_pinbar | (df_candle['Close'] < df_candle['Open']))
atr_multiplier = np.where(risk_accelerate, 1.0, 2.5)

adjusted_high = np.where(is_pinbar & is_vol_spike, df_candle['Close'], df_candle['High'])
df_candle['Adj_Highest_High'] = pd.Series(adjusted_high, index=df_candle.index).rolling(20).max()

# nan 제거
df_candle = df_candle.dropna().copy()
atr_multiplier = atr_multiplier[-len(df_candle):]

# 1. 2.5 ATR 기반의 정석 샹들리에 출구 계산 (내려가지 않는 Trailing 스톱)
pure_raw_sl = df_candle['Adj_Highest_High'] - 2.5 * df_candle['ATR']

stop_loss_series = []
for i in range(len(df_candle)):
    if i == 0:
        stop_loss_series.append(pure_raw_sl.iloc[i])
    else:
        prev_sl = stop_loss_series[-1]
        curr_raw = pure_raw_sl.iloc[i]
        close_val = df_candle['Close'].iloc[i]
        
        # 보유 중일 때(종가가 이전 손절선보다 높을 때)는 수평 또는 상승 트레일링
        if close_val > prev_sl:
            stop_loss_series.append(max(prev_sl, curr_raw))
        else:
            # 이탈 시에는 주가를 유연하게 아래로 추종
            stop_loss_series.append(curr_raw)

df_candle['Stop_Loss'] = stop_loss_series

# 2. 동적 판정선
dynamic_trigger_sl = df_candle['Adj_Highest_High'] - atr_multiplier * df_candle['ATR']

# 3. 이탈 신호 판정
df_candle['Exit_Signal'] = (df_candle['Close'] < dynamic_trigger_sl) & (df_candle['Close'].shift(1) >= df_candle['Stop_Loss'].shift(1))

print("Signals detected:")
for idx in df_candle[df_candle['Exit_Signal'] == True].index:
    row = df_candle.loc[idx]
    print(f"Date: {idx.strftime('%Y-%m-%d')}, Close: {int(row['Close']):,}, StopLoss: {int(row['Stop_Loss']):,}")
print("Total signals detected:", df_candle['Exit_Signal'].sum())
