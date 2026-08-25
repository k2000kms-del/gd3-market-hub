# -*- coding: utf-8 -*-
"""
live_logger.py (v2 — 쿨다운 및 스마트 손절가 알림 보완판)
- 30분 시간 기반 알림 쿨다운(Cool-down) 적용하여 텔레그램 도배 차단
- 포트폴리오 손절가(stop_loss) 하향 이탈 시 최초 1회만 스마트 경고 알림 전송
"""
import csv
import os
import pandas as pd
from datetime import datetime, timedelta

# 텔레그램 알림 모듈 임포트
try:
    from telegram_notifier import notify_buy_signal, notify_exit_signal, notify_add_signal, notify_fall_buy_signal, _send
    _TG_AVAILABLE = True
except ImportError:
    _TG_AVAILABLE = False

LOG_PATH = "scalping_signal_log.csv"
STOP_LOSS_ALERT_PATH = "stop_loss_alert_history.json"
DEFAULT_COOLDOWN_MINUTES = 30  # 동일 종목/동일 신호 쿨다운 시간 (30분)


def _ensure_log_file():
    if not os.path.exists(LOG_PATH):
        with open(LOG_PATH, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "ticker", "event", "timestamp", "price",
                "pnl_pct", "holding_minutes"
            ])


def is_in_cooldown(ticker: str, event: str, current_ts: datetime, cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES) -> bool:
    """동일 종목 & 동일 이벤트에 대해 지정한 쿨다운 시간(예: 30분) 이내에 이미 알림이 전송되었는지 확인"""
    if not os.path.exists(LOG_PATH):
        return False

    try:
        df = pd.read_csv(LOG_PATH, encoding="utf-8-sig")
        if df.empty or 'ticker' not in df.columns or 'timestamp' not in df.columns:
            return False

        # 해당 종목 & 해당 이벤트 필터링
        sub_df = df[(df['ticker'].astype(str) == str(ticker)) & (df['event'] == event)].copy()
        if sub_df.empty:
            return False

        # 최근 로그 시각 변환
        sub_df['ts_dt'] = pd.to_datetime(sub_df['timestamp'], errors='coerce')
        sub_df = sub_df.dropna(subset=['ts_dt'])
        if sub_df.empty:
            return False

        last_ts = sub_df['ts_dt'].max()
        time_diff = (current_ts - last_ts).total_seconds() / 60.0

        # 쿨다운 시간 이내라면 True (알림 건너뜀)
        return time_diff < cooldown_minutes
    except Exception as e:
        print(f"DEBUG: is_in_cooldown check error: {e}")
        return False


def get_last_entry(ticker: str):
    """특정 종목의 가장 최근 진입 기록을 찾아 반환하되, 추가 매수(ADD_SIGNAL)가 존재할 경우 평단가를 가중평균하여 반환"""
    if not os.path.exists(LOG_PATH):
        return None

    try:
        df = pd.read_csv(LOG_PATH, encoding="utf-8-sig")
        if df.empty:
            return None

        df_ticker = df[df['ticker'].astype(str) == str(ticker)].copy()
        if df_ticker.empty:
            return None

        exit_indices = df_ticker[df_ticker['event'] == 'EXIT_SIGNAL'].index
        last_exit_idx = exit_indices[-1] if len(exit_indices) > 0 else -1

        df_active = df_ticker.loc[df_ticker.index > last_exit_idx]
        if df_active.empty:
            return None

        entry_rows = df_active[df_active['event'].isin(['BUY_SIGNAL', 'FALL_BUY_SIGNAL'])]
        if entry_rows.empty:
            return None

        first_entry = entry_rows.iloc[0]
        entry_price = float(first_entry['price'])
        entry_time = pd.to_datetime(first_entry['timestamp'])

        add_rows = df_active[df_active['event'] == 'ADD_SIGNAL']
        if not add_rows.empty:
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
    cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES,
):
    """일반 매수 신호를 기록하고 쿨다운(30분) 검증 후 텔레그램 알림 전송"""
    _ensure_log_file()
    ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')

    # 30분 쿨다운 적용 (중복 발송 방지)
    if is_in_cooldown(ticker, "BUY_SIGNAL", timestamp, cooldown_minutes=cooldown_minutes):
        print(f"DEBUG: [{name or ticker}] 매수 알림 쿨다운 중 ({cooldown_minutes}분 미경과) — 알림 건너뜀")
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
    cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES,
):
    """추가 매수 신호를 기록하고 쿨다운(30분) 검증 후 텔레그램 알림 전송"""
    _ensure_log_file()
    ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')

    if is_in_cooldown(ticker, "ADD_SIGNAL", timestamp, cooldown_minutes=cooldown_minutes):
        print(f"DEBUG: [{name or ticker}] 추가매수 알림 쿨다운 중 — 알림 건너뜀")
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
    cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES,
):
    """낙폭과대 반등 매수 신호를 기록하고 쿨다운(30분) 검증 후 텔레그램 알림 전송"""
    _ensure_log_file()
    ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')

    if is_in_cooldown(ticker, "FALL_BUY_SIGNAL", timestamp, cooldown_minutes=cooldown_minutes):
        print(f"DEBUG: [{name or ticker}] 낙폭과대 매수 알림 쿨다운 중 — 알림 건너뜀")
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
            print(f"DEBUG: 텔레그램 낙폭과대매수 알림 전송 실패: {e}")


def log_exit_signal(
    ticker: str,
    price: float,
    timestamp: datetime,
    name: str = "",
    tg_token: str = "",
    tg_chat_id: str = "",
    cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES,
):
    """매도/청산 신호를 기록하고, PnL 계산 후 쿨다운(30분) 검증 후 텔레그램 알림 전송"""
    _ensure_log_file()
    ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')

    if is_in_cooldown(ticker, "EXIT_SIGNAL", timestamp, cooldown_minutes=cooldown_minutes):
        print(f"DEBUG: [{name or ticker}] 청산 알림 쿨다운 중 — 알림 건너뜀")
        return

    entry = get_last_entry(ticker)
    pnl_pct = ""
    holding_minutes = ""

    if entry:
        pnl_pct = round((price - entry["entry_price"]) / entry["entry_price"] * 100, 3)
        pnl_pct = round(pnl_pct - 0.195, 3)  # 수수료/세금
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


# ══════════════════════════════════════════════════════════════
# 스마트 손절가 이탈 감지 (Event-Triggered Single Alert)
# ══════════════════════════════════════════════════════════════

import json

def _load_stop_loss_alert_history() -> dict:
    if os.path.exists(STOP_LOSS_ALERT_PATH):
        try:
            with open(STOP_LOSS_ALERT_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_stop_loss_alert_history(data: dict):
    try:
        with open(STOP_LOSS_ALERT_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"DEBUG: _save_stop_loss_alert_history failed: {e}")


def check_and_notify_stop_loss(
    code: str,
    name: str,
    current_price: float,
    stop_loss: float,
    tg_token: str = "",
    tg_chat_id: str = "",
) -> bool:
    """손절가 이탈 순간에만 1회 알림을 보내는 스마트 감지기

    - 정상 범위(현재가 > 손절가)에 있던 종목이 손절가 이하로 낮아지는 '이탈 순간'에 1회 발송
    - 이미 이탈된 상태가 유지되는 동안에는 이중 도배 알림 차단
    - 가격이 손절가 위로 회복되면 상태 리셋
    """
    if not stop_loss or stop_loss <= 0 or current_price <= 0:
        return False

    history = _load_stop_loss_alert_history()
    stock_info = history.get(code, {'status': 'NORMAL', 'last_alert_ts': ''})
    status = stock_info.get('status', 'NORMAL')

    is_currently_breached = current_price <= stop_loss

    # 1. 가격이 손절가 위로 회복된 경우 → 상태 리셋
    if not is_currently_breached:
        if status != 'NORMAL':
            history[code] = {'status': 'NORMAL', 'last_alert_ts': ''}
            _save_stop_loss_alert_history(history)
        return False

    # 2. 이탈 상태이나 이미 알림을 발송한 경우 → 추가 알림 차단 (도배 방지)
    if status == 'ALERTED':
        return False

    # 3. 신규 이탈 발생 (NORMAL -> ALERTED) → 텔레그램 알림 1회 즉시 전송
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    history[code] = {'status': 'ALERTED', 'last_alert_ts': now_str}
    _save_stop_loss_alert_history(history)

    if _TG_AVAILABLE and tg_token and tg_chat_id:
        loss_pct = ((current_price - stop_loss) / stop_loss) * 100
        text = (
            f"🚨 <b>[손절가 하향 이탈 경고]</b> {name} ({code})\n"
            f"━━━━━━━━━━━━━━\n"
            f"💰 현재가: <b>{current_price:,.0f}원</b>\n"
            f"🛑 설정 손절가: <b>{stop_loss:,.0f}원</b>\n"
            f"📉 이탈 폭: <b>{loss_pct:.2f}%</b>\n"
            f"⏰ 감지 시각: {datetime.now().strftime('%H:%M:%S')}\n"
            f"━━━━━━━━━━━━━━\n"
            f"⚠️ 이 알림은 손절 이탈 최초 1회만 발송되며, 주가 회복 전까지 중복 발송되지 않습니다."
        )
        try:
            return _send(tg_token, tg_chat_id, text)
        except Exception as e:
            print(f"DEBUG: 텔레그램 손절가 알림 전송 실패: {e}")

    return True


# ══════════════════════════════════════════════════════════════
# 트레일링 스탑 (추적 익절) 감지기
# ══════════════════════════════════════════════════════════════

TRAILING_STOP_PATH = "trailing_stop_history.json"

def _load_trailing_history() -> dict:
    if os.path.exists(TRAILING_STOP_PATH):
        try:
            with open(TRAILING_STOP_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_trailing_history(data: dict):
    try:
        with open(TRAILING_STOP_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"DEBUG: _save_trailing_history failed: {e}")


def check_and_notify_trailing_stop(
    code: str,
    name: str,
    current_price: float,
    entry_price: float,
    min_profit_pct: float = 4.0,   # 최소 +4% 이상 수익권 진입 시 활성화
    drop_pct: float = 2.0,         # 고점 대비 -2% 밀릴 때 발동
    tg_token: str = "",
    tg_chat_id: str = "",
) -> bool:
    """수익권(+4% 이상) 도달 후 최고점 대비 -2% 하락 시 트레일링 스탑 알림."""
    if not entry_price or entry_price <= 0 or current_price <= 0:
        return False

    history = _load_trailing_history()
    stock_info = history.get(code, {'highest_price': entry_price, 'alerted': False, 'entry_price': entry_price})
    
    # 평단가가 바뀌었으면 초기화
    if abs(stock_info.get('entry_price', 0) - entry_price) > 1:
        stock_info = {'highest_price': max(current_price, entry_price), 'alerted': False, 'entry_price': entry_price}

    highest = max(float(stock_info.get('highest_price', entry_price)), current_price)
    stock_info['highest_price'] = highest
    
    # 수익률 계산
    max_pnl_pct = ((highest - entry_price) / entry_price) * 100
    cur_pnl_pct = ((current_price - entry_price) / entry_price) * 100
    
    # +4% 이상 도달한 적이 없는 경우 리턴
    if max_pnl_pct < min_profit_pct:
        _save_trailing_history(history)
        return False

    # 최고점 대비 하락률 계산
    pullback_pct = ((highest - current_price) / highest) * 100
    
    # 최고점 갱신 시 알림 상태 리셋
    if current_price >= highest:
        stock_info['alerted'] = False
        _save_trailing_history(history)
        return False

    # 고점 대비 drop_pct 이상 밀렸고 아직 알림 전인 경우
    if pullback_pct >= drop_pct and not stock_info.get('alerted', False) and cur_pnl_pct > 0:
        stock_info['alerted'] = True
        _save_trailing_history(history)
        
        if _TG_AVAILABLE and tg_token and tg_chat_id:
            try:
                from telegram_notifier import notify_trailing_stop
                return notify_trailing_stop(
                    token=tg_token, chat_id=tg_chat_id,
                    ticker=code, name=name,
                    current_price=current_price,
                    entry_price=entry_price,
                    highest_price=highest,
                    drop_pct=pullback_pct
                )
            except Exception as e:
                print(f"DEBUG: 텔레그램 트레일링 스탑 알림 실패: {e}")

    _save_trailing_history(history)
    return False
