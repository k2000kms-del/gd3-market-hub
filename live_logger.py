import csv
import os
import pandas as pd
from datetime import datetime

LOG_PATH = "scalping_signal_log.csv"

def _ensure_log_file():
    if not os.path.exists(LOG_PATH):
        with open(LOG_PATH, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "ticker", "event", "timestamp", "price",
                "pnl_pct", "holding_minutes"
            ])

def is_already_logged(ticker: str, event: str, timestamp_str: str) -> bool:
    """동일한 종목, 이벤트, 시간에 이미 기록된 로그가 있는지 확인 (중복 방지)"""
    if not os.path.exists(LOG_PATH):
        return False
    
    try:
        df = pd.read_csv(LOG_PATH, encoding="utf-8-sig")
        if df.empty:
            return False
            
        # 정확히 일치하는 행이 있는지 검사
        match = df[(df['ticker'] == str(ticker)) & 
                   (df['event'] == event) & 
                   (df['timestamp'] == timestamp_str)]
        
        return not match.empty
    except Exception as e:
        print(f"DEBUG: is_already_logged error: {e}")
        return False

def get_last_entry(ticker: str):
    """특정 종목의 가장 최근 매수(BUY_SIGNAL) 기록을 찾아 반환 (매도 시 수익률 계산용)"""
    if not os.path.exists(LOG_PATH):
        return None
        
    try:
        df = pd.read_csv(LOG_PATH, encoding="utf-8-sig")
        if df.empty:
            return None
            
        # 해당 종목의 로그만 필터링
        df_ticker = df[df['ticker'] == str(ticker)].copy()
        if df_ticker.empty:
            return None
            
        # 가장 최근 기록 찾기
        last_row = df_ticker.iloc[-1]
        
        # 만약 가장 최근 기록이 BUY_SIGNAL 이라면 정보 반환
        if last_row['event'] == 'BUY_SIGNAL':
            return {
                "entry_price": float(last_row['price']),
                "entry_time": pd.to_datetime(last_row['timestamp'])
            }
        return None
    except Exception as e:
        print(f"DEBUG: get_last_entry error: {e}")
        return None

def log_buy_signal(ticker: str, price: float, timestamp: datetime):
    _ensure_log_file()
    ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')
    
    if is_already_logged(ticker, "BUY_SIGNAL", ts_str):
        return  # 이미 기록됨
        
    with open(LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow([
            str(ticker), "BUY_SIGNAL", ts_str, price,
            "", ""
        ])

def log_exit_signal(ticker: str, price: float, timestamp: datetime):
    _ensure_log_file()
    ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')
    
    if is_already_logged(ticker, "EXIT_SIGNAL", ts_str):
        return  # 이미 기록됨
        
    entry = get_last_entry(ticker)
    pnl_pct = ""
    holding_minutes = ""

    if entry:
        pnl_pct = round((price - entry["entry_price"]) / entry["entry_price"] * 100, 3)
        # 수수료(0.015%) 및 세금(0.18%) 차감
        pnl_pct = round(pnl_pct - 0.195, 3)
        holding_minutes = round((timestamp - entry["entry_time"]).total_seconds() / 60, 1)

    with open(LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow([
            str(ticker), "EXIT_SIGNAL", ts_str, price,
            pnl_pct, holding_minutes
        ])
