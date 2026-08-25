# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')
import requests
import ast
import pandas as pd
import numpy as np

# Mock functions from app.py
def calculate_rsi(df, period=14):
    df = df.copy()
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    df['RSI_14'] = 100 - (100 / (1 + rs))
    return df

def calculate_vwap(df):
    df = df.copy()
    q = df['Volume']
    p = (df['High'] + df['Low'] + df['Close']) / 3
    df['Date'] = df['DateTime'].dt.date
    df['PV'] = p * q
    df['Cum_PV'] = df.groupby('Date')['PV'].cumsum()
    df['Cum_Vol'] = df.groupby('Date')['Volume'].cumsum()
    df['VWAP'] = df['Cum_PV'] / df['Cum_Vol']
    df['VWAP'] = df['VWAP'].fillna(df['Close'])
    df.drop(columns=['Date', 'PV', 'Cum_PV', 'Cum_Vol'], inplace=True)
    return df

def detect_volume_surge(df, lookback=10, multiplier=2.0):
    df = df.copy()
    df['Vol_MA'] = df['Volume'].rolling(window=lookback).mean()
    df['Vol_Surge'] = df['Volume'] >= (df['Vol_MA'].shift(1) * multiplier)
    df.drop(columns=['Vol_MA'], inplace=True)
    return df

def calculate_intraday_signals(df, my_entry_price=0.0, timeframe='1min', code=None):
    if timeframe == '5min':
        tp_pct = 1.0
        vol_mult = 1.5
    else:
        tp_pct = 0.7
        vol_mult = 2.0

    time_cut = 30
    atr_mult = 1.5

    if df.empty or len(df) < 20:
        return df

    df['MA5']  = df['Close'].rolling(5).mean()
    df['MA20'] = df['Close'].rolling(20).mean()

    df = calculate_vwap(df)
    df = calculate_rsi(df, period=14)
    df = detect_volume_surge(df, lookback=10, multiplier=vol_mult)

    # ATR
    high  = df['High'].values
    low   = df['Low'].values
    close = df['Close'].values
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1]))
    )
    tr = np.insert(tr, 0, high[0] - low[0])
    df['ATR_Scalp'] = pd.Series(tr).rolling(7).mean()

    # Buy conditions
    cond_vwap = df['Close'] > df['VWAP']
    cond_rsi  = df['RSI_14'].between(35, 65)
    cond_vol  = df['Vol_Surge']

    df['Raw_Buy'] = cond_vwap & cond_rsi & cond_vol
    dynamic_raw_sl = df['Close'] - atr_mult * df['ATR_Scalp']

    stop_loss_series = []
    exit_signal_list = []
    buy_signal_list  = []
    add_signal_list  = []
    fall_signal_list = []

    in_position = False
    entry_price = 0.0
    entry_idx   = 0
    current_sl  = np.nan
    add_count   = 0

    for i in range(len(df)):
        close_val = df['Close'].iloc[i]
        open_val  = df['Open'].iloc[i]
        raw_buy   = df['Raw_Buy'].iloc[i]
        raw_sl    = dynamic_raw_sl.iloc[i]

        prev_rsi = df['RSI_14'].iloc[i-1] if i > 0 else np.nan
        curr_rsi = df['RSI_14'].iloc[i]

        if pd.isna(raw_sl):
            stop_loss_series.append(np.nan)
            exit_signal_list.append(False)
            buy_signal_list.append(False)
            add_signal_list.append(False)
            fall_signal_list.append(False)
            continue

        if in_position:
            buy_signal_list.append(False)
            fall_signal_list.append(False)

            current_sl = raw_sl if pd.isna(current_sl) else max(current_sl, raw_sl)
            stop_loss_series.append(current_sl)

            prev_sl = stop_loss_series[-2] if (
                len(stop_loss_series) > 1 and not pd.isna(stop_loss_series[-2])
            ) else current_sl

            pnl_pct = (close_val - entry_price) / entry_price * 100 if entry_price > 0 else 0

            # Smart add
            cond_add_indicator = (not pd.isna(prev_rsi) and prev_rsi <= 30 and curr_rsi > 30) or \
                                 (close_val > df['VWAP'].iloc[i] and df['Vol_Surge'].iloc[i])
            
            if pnl_pct <= -3.0 and cond_add_indicator and add_count == 0:
                add_signal_list.append(True)
                add_count = 1
                entry_price = (entry_price + close_val) / 2
                entry_idx = i
            else:
                add_signal_list.append(False)

            # Exit triggers
            hit_stop = (open_val < prev_sl) or (close_val < current_sl)
            hit_tp   = pnl_pct >= tp_pct
            hit_time = (i - entry_idx) >= time_cut if entry_idx > 0 else False

            if hit_stop or hit_tp or hit_time:
                exit_signal_list.append(True)
                in_position = False
                current_sl  = np.nan
                add_count   = 0
            else:
                exit_signal_list.append(False)
        else:
            exit_signal_list.append(False)
            add_signal_list.append(False)
            stop_loss_series.append(raw_sl)

            cond_fall_indicator = (not pd.isna(prev_rsi) and prev_rsi <= 30 and curr_rsi > 30)

            if cond_fall_indicator:
                fall_signal_list.append(True)
                buy_signal_list.append(False)
                in_position = True
                entry_price = close_val
                entry_idx   = i
                current_sl  = raw_sl
                add_count   = 0
            elif raw_buy:
                buy_signal_list.append(True)
                fall_signal_list.append(False)
                in_position = True
                entry_price = close_val
                entry_idx   = i
                current_sl  = raw_sl
                add_count   = 0
            else:
                buy_signal_list.append(False)
                fall_signal_list.append(False)

    df['Stop_Loss']   = stop_loss_series
    df['Exit_Signal'] = exit_signal_list
    df['Buy_Signal']  = buy_signal_list
    df['Add_Signal']  = add_signal_list
    df['Fall_Signal'] = fall_signal_list
    return df

# Fetch Naver minute history for 036930 (주성엔지니어링)
url = "https://api.finance.naver.com/siseJson.naver?symbol=036930&requestType=0&timeframe=minute&count=2000"
res = requests.get(url)
text = res.content.decode('utf-8')
text = text.replace("'", '"').replace("null", "None").replace("NaN", "None").strip()

import ast
raw_data = ast.literal_eval(text)
columns = raw_data[0]
rows = raw_data[1:]
df = pd.DataFrame(rows, columns=columns)
df.rename(columns={'날짜': 'Time', '시가': 'Open', '고가': 'High', '저가': 'Low', '종가': 'Close', '거래량': 'Volume'}, inplace=True)
for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
    df[col] = pd.to_numeric(df[col], errors='coerce')
df['Open'] = df['Open'].fillna(df['Close'].shift(1).fillna(df['Close']))
df['High'] = df['High'].fillna(df[['Open', 'Close']].max(axis=1) + df['Close'] * 0.0005)
df['Low'] = df['Low'].fillna((df[['Open', 'Close']].min(axis=1) - df['Close'] * 0.0005).clip(lower=0))
df['DateTime'] = pd.to_datetime(df['Time'], format='%Y%m%d%H%M', errors='coerce')

df = calculate_intraday_signals(df)
df_tail = df.tail(400).copy()

print("=== 1-Minute signals in the last 400 bars ===")
print("Buy_Signals:", df_tail['Buy_Signal'].sum())
print("Fall_Signals:", df_tail['Fall_Signal'].sum())
print("Exit_Signals:", df_tail['Exit_Signal'].sum())
print("Add_Signals:", df_tail['Add_Signals'].sum() if 'Add_Signals' in df_tail else df_tail['Add_Signal'].sum())

# Print some rows where Fall_Signal is True
fall_rows = df_tail[df_tail['Fall_Signal'] == True]
if not fall_rows.empty:
    print("\nFall Signal Examples:")
    print(fall_rows[['DateTime', 'Close']])
else:
    print("\nNo Fall Signals in the tail!")
