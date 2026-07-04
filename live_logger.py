import csv
import os
import pandas as pd
from datetime import datetime

# 텔레그램 알림 모듈 임포트 (선택적 — 미설치 시에도 로거는 정상 동작)
try:
    from telegram_notifier import notify_buy_signal, notify_exit_signal
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
    """매수 신호를 CSV에 기록하고, 텔레그램으로 실시간 알림을 전송.
    
    Args:
        ticker:     종목 코드
        price:      현재가
        timestamp:  신호 발생 시각
        name:       종목명 (텔레그램 메시지 표시용)
        tg_token:   텔레그램 봇 토큰 (없으면 알림 생략)
        tg_chat_id: 텔레그램 Chat ID (없으면 알림 생략)
        rsi:        RSI 값 (선택 — 메시지에 포함)
        vwap:       VWAP 값 (선택 — 메시지에 포함)
    """
    _ensure_log_file()
    ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')
    
    if is_already_logged(ticker, "BUY_SIGNAL", ts_str):
        return  # 이미 기록됨 (중복 방지)
        
    with open(LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow([
            str(ticker), "BUY_SIGNAL", ts_str, price,
            "", ""
        ])
    
    # 텔레그램 알림 전송 (토큰/Chat ID가 설정된 경우에만)
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


def log_exit_signal(
    ticker: str,
    price: float,
    timestamp: datetime,
    name: str = "",
    tg_token: str = "",
    tg_chat_id: str = "",
):
    """매도/청산 신호를 CSV에 기록하고, PnL 계산 후 텔레그램으로 실시간 알림을 전송.
    
    Args:
        ticker:     종목 코드
        price:      현재가
        timestamp:  신호 발생 시각
        name:       종목명 (텔레그램 메시지 표시용)
        tg_token:   텔레그램 봇 토큰 (없으면 알림 생략)
        tg_chat_id: 텔레그램 Chat ID (없으면 알림 생략)
    """
    _ensure_log_file()
    ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')
    
    if is_already_logged(ticker, "EXIT_SIGNAL", ts_str):
        return  # 이미 기록됨 (중복 방지)
        
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
    
    # 텔레그램 알림 전송 (토큰/Chat ID가 설정된 경우에만)
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
