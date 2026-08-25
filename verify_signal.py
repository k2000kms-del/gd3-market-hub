import pandas as pd
import numpy as np
import FinanceDataReader as fdr

code = "005380"
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
        
        if close_val > prev_sl:
            stop_loss_series.append(max(prev_sl, curr_raw))
        else:
            stop_loss_series.append(curr_raw)

df_candle['Stop_Loss'] = stop_loss_series
df_candle['ATR_Multiplier'] = atr_multiplier

# 2. 동적 판정선
df_candle['Dynamic_Trigger_SL'] = df_candle['Adj_Highest_High'] - df_candle['ATR_Multiplier'] * df_candle['ATR']

# 3. 중복 신호 차단 상태 기계 루프
exit_signals = []
in_position = True

for i in range(len(df_candle)):
    close_val = df_candle['Close'].iloc[i]
    dyn_sl = df_candle['Dynamic_Trigger_SL'].iloc[i]
    smooth_sl = df_candle['Stop_Loss'].iloc[i]
    
    if in_position:
        if close_val < dyn_sl:
            exit_signals.append(True)
            in_position = False
        else:
            exit_signals.append(False)
    else:
        exit_signals.append(False)
        if close_val >= smooth_sl:
            in_position = True

df_candle['Exit_Signal'] = exit_signals

# 2026-02-20 ~ 2026-03-10 부근 출력
df_target = df_candle.loc["2026-02-20":"2026-03-10"]

print("=== VERIFICATION REPORT FOR 005380 (State Machine Applied) ===")
cols_to_print = ['Open', 'High', 'Low', 'Close', 'Volume', 'ATR', 'Adj_Highest_High', 'ATR_Multiplier', 'Stop_Loss', 'Dynamic_Trigger_SL', 'Exit_Signal']
print(df_target[cols_to_print].to_string())
print("Total exit signals in whole dataset:", df_candle['Exit_Signal'].sum())
print("Exit signals dates in whole dataset:", df_candle[df_candle['Exit_Signal'] == True].index.strftime('%Y-%m-%d').tolist())
