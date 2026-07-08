# -*- coding: utf-8 -*-
import csv
import os
import pandas as pd
from datetime import datetime

# 텔레그램 알림 모듈 임포트
try:
    from telegram_notifier import notify_buy_signal, notify_exit_signal, notify_add_signal, notify_fall_buy_signal
    _TG_AVAILABLE = True
except ImportError:
    _TG_AVAILABLE = False

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
    """특정 종목의 가장 최근 진입 기록을 찾아 반환하되, 추가 매수(ADD_SIGNAL)가 존재할 경우 평단가를 가중평균하여 반환"""
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
            
        # 가장 최근의 청산(EXIT_SIGNAL)이 일어난 인덱스 찾기
        exit_indices = df_ticker[df_ticker['event'] == 'EXIT_SIGNAL'].index
        last_exit_idx = exit_indices[-1] if len(exit_indices) > 0 else -1
        
        # 마지막 청산 이후의 모든 행 필터링
        df_active = df_ticker.loc[df_ticker.index > last_exit_idx]
        if df_active.empty:
            return None
            
        # 최초 진입 신호(BUY_SIGNAL 또는 FALL_BUY_SIGNAL) 찾기
        entry_rows = df_active[df_active['event'].isin(['BUY_SIGNAL', 'FALL_BUY_SIGNAL'])]
        if entry_rows.empty:
            return None
            
        first_entry = entry_rows.iloc[0]
        entry_price = float(first_entry['price'])
        entry_time = pd.to_datetime(first_entry['timestamp'])
        
        # 그 이후에 추가 매수가 있었는지 확인
        add_rows = df_active[df_active['event'] == 'ADD_SIGNAL']
        if not add_rows.empty:
            # 1:1 추가 매수이므로 가중평균 단가 계산
            add_price = float(add_rows.iloc[0]['price'])
            entry_price = (entry_price + add_price) / 2
            
        return {
            "entry_price": entry_price,
            "entry_time": entry_time
        }
    except Exception as e:
        print(f"DEBUG: get_last_entry error: {e}")
        return None

def log_buy_signal(
    ticker: str,
    price: float,
    timestamp: datetime,
    name: str = "",
    tg_token: str = "",
    tg_chat_id: str = "",
    rsi: float = None,
    vwap: float = None,
):
    """일반 매수 신호를 CSV에 기록하고 텔레그램 알림을 전송"""
    _ensure_log_file()
    ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')
    
    if is_already_logged(ticker, "BUY_SIGNAL", ts_str):
        return
        
    with open(LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow([
            str(ticker), "BUY_SIGNAL", ts_str, price,
            "", ""
        ])
    
    if _TG_AVAILABLE and tg_token and tg_chat_id:
        try:
            notify_buy_signal(
                token=tg_token,
                chat_id=tg_chat_id,
                ticker=ticker,
                name=name if name else ticker,
                price=price,
                timestamp=timestamp,
                rsi=rsi,
                vwap=vwap,
            )
        except Exception as e:
            print(f"DEBUG: 텔레그램 매수 알림 전송 실패: {e}")

def log_add_signal(
    ticker: str,
    price: float,
    timestamp: datetime,
    name: str = "",
    tg_token: str = "",
    tg_chat_id: str = "",
    rsi: float = None,
    vwap: float = None,
):
    """추가 매수 신호를 CSV에 기록하고 텔레그램 알림을 전송"""
    _ensure_log_file()
    ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')
    
    if is_already_logged(ticker, "ADD_SIGNAL", ts_str):
        return
        
    with open(LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow([
            str(ticker), "ADD_SIGNAL", ts_str, price,
            "", ""
        ])
    
    if _TG_AVAILABLE and tg_token and tg_chat_id:
        try:
            notify_add_signal(
                token=tg_token,
                chat_id=tg_chat_id,
                ticker=ticker,
                name=name if name else ticker,
                price=price,
                timestamp=timestamp,
                rsi=rsi,
                vwap=vwap,
            )
        except Exception as e:
            print(f"DEBUG: 텔레그램 추가매수 알림 전송 실패: {e}")

def log_fall_buy_signal(
    ticker: str,
    price: float,
    timestamp: datetime,
    name: str = "",
    tg_token: str = "",
    tg_chat_id: str = "",
    rsi: float = None,
    vwap: float = None,
):
    """낙주 매수 신호를 CSV에 기록하고 텔레그램 알림을 전송"""
    _ensure_log_file()
    ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')
    
    if is_already_logged(ticker, "FALL_BUY_SIGNAL", ts_str):
        return
        
    with open(LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow([
            str(ticker), "FALL_BUY_SIGNAL", ts_str, price,
            "", ""
        ])
    
    if _TG_AVAILABLE and tg_token and tg_chat_id:
        try:
            notify_fall_buy_signal(
                token=tg_token,
                chat_id=tg_chat_id,
                ticker=ticker,
                name=name if name else ticker,
                price=price,
                timestamp=timestamp,
                rsi=rsi,
                vwap=vwap,
            )
        except Exception as e:
            print(f"DEBUG: 텔레그램 낙주매수 알림 전송 실패: {e}")

def log_exit_signal(
    ticker: str,
    price: float,
    timestamp: datetime,
    name: str = "",
    tg_token: str = "",
    tg_chat_id: str = "",
):
    """매도/청산 신호를 CSV에 기록하고, PnL 계산 후 텔레그램 알림을 전송"""
    _ensure_log_file()
    ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')
    
    if is_already_logged(ticker, "EXIT_SIGNAL", ts_str):
        return
        
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
    
    if _TG_AVAILABLE and tg_token and tg_chat_id:
        try:
            notify_exit_signal(
                token=tg_token,
                chat_id=tg_chat_id,
                ticker=ticker,
                name=name if name else ticker,
                price=price,
                timestamp=timestamp,
                pnl_pct=pnl_pct if pnl_pct != "" else None,
                holding_minutes=holding_minutes if holding_minutes != "" else None,
            )
        except Exception as e:
            print(f"DEBUG: 텔레그램 청산 알림 전송 실패: {e}")
