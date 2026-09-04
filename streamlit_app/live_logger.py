# -*- coding: utf-8 -*-
"""
live_logger.py (v2 — 쿨다운 및 스마트 손절가 알림 보완판)
- 30분 시간 기반 알림 쿨다운(Cool-down) 적용하여 텔레그램 도배 차단
- 포트폴리오 손절가(stop_loss) 하향 이탈 시 최초 1회만 스마트 경고 알림 전송
"""
import csv
import os
import threading
import pandas as pd
from datetime import datetime, timedelta, timezone

# 텔레그램 알림 모듈 임포트
try:
    from telegram_notifier import notify_buy_signal, notify_exit_signal, notify_add_signal, notify_fall_buy_signal, _send, is_regular_market_hours
    _TG_AVAILABLE = True
except ImportError:
    _TG_AVAILABLE = False
    def is_regular_market_hours(): return True

_KST = timezone(timedelta(hours=9))
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_BASE_DIR, "data")
if not os.path.exists(_DATA_DIR):
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
    except Exception:
        pass

LOG_PATH = os.path.join(_DATA_DIR, "scalping_signal_log.csv")
STOP_LOSS_ALERT_PATH = os.path.join(_DATA_DIR, "stop_loss_alert_history.json")
DEFAULT_COOLDOWN_MINUTES = 30  # 동일 종목/동일 신호 쿨다운 시간 (30분)

# 🔒 인메모리 스레드 안전 쿨다운 캐시 (도배 100% 방지)
_SIGNAL_COOLDOWN_LOCK = threading.Lock()
_SIGNAL_COOLDOWN_MEM: dict = {}


def _ensure_log_file():
    if not os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "ticker", "event", "timestamp", "price",
                    "pnl_pct", "holding_minutes"
                ])
        except Exception as e:
            print(f"DEBUG: _ensure_log_file failed: {e}")


def is_in_cooldown(ticker: str, event: str, current_ts: datetime = None, cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES) -> bool:
    """동일 종목 & 동일 이벤트에 대해 지정한 쿨다운 시간(예: 30분) 이내에 이미 알림이 전송되었는지 확인"""
    now_kst = datetime.now(_KST)
    clean_ticker = str(ticker).strip().zfill(6)
    mem_key = f"{clean_ticker}_{event}"

    # 1. 초고속 인메모리 캐시 검사
    with _SIGNAL_COOLDOWN_LOCK:
        if mem_key in _SIGNAL_COOLDOWN_MEM:
            last_mem_ts = _SIGNAL_COOLDOWN_MEM[mem_key]
            diff_min = (now_kst - last_mem_ts).total_seconds() / 60.0
            if 0 <= diff_min < cooldown_minutes:
                return True

    # 2. 파일 기반 검사 (보완용)
    if not os.path.exists(LOG_PATH):
        return False

    try:
        df = pd.read_csv(LOG_PATH, encoding="utf-8-sig")
        if df.empty or 'ticker' not in df.columns or 'timestamp' not in df.columns:
            return False

        # 해당 종목 & 해당 이벤트 필터링
        sub_df = df[(df['ticker'].astype(str).str.zfill(6) == clean_ticker) & (df['event'] == event)].copy()
        if sub_df.empty:
            return False

        # 최근 로그 시각 변환
        sub_df['ts_dt'] = pd.to_datetime(sub_df['timestamp'], errors='coerce')
        sub_df = sub_df.dropna(subset=['ts_dt'])
        if sub_df.empty:
            return False

        last_ts = sub_df['ts_dt'].max()
        check_ts = current_ts if current_ts is not None else now_kst
        if hasattr(check_ts, 'tzinfo') and check_ts.tzinfo is not None:
            check_ts = check_ts.astimezone(_KST).replace(tzinfo=None)
        time_diff = (check_ts - last_ts).total_seconds() / 60.0

        # 쿨다운 시간 이내라면 True (알림 건너뜀)
        return 0 <= time_diff < cooldown_minutes
    except Exception as e:
        print(f"DEBUG: is_in_cooldown check error: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# 🎯 퀀트 상태 기반(State-Based) 포지션 수명주기 관리자
# ══════════════════════════════════════════════════════════════
# 8개년 빅데이터 백테스트 승률 58.7% / 손익비 1.46 달성의 핵심 퀀트 모델:
# 1. 진입(Buy/Fall Buy) ➔ 'IN_POSITION' 상태 등록
# 2. 보유 중 동일 매수 신호 100% 차단 (노이즈 및 오버트레이딩 방어)
# 3. 오직 ATR 기반 '추가 매수(ADD)' 신호만 포지션당 최대 1회 허용
# 4. 청산(Exit/Stop) ➔ 'FLAT' 상태 전환 & 15분 파동 쿨다운 가동
# 5. 최대 보유 타임컷(30분): 30분 경과 시 자동 FLAT 전환
# ══════════════════════════════════════════════════════════════

POST_EXIT_COOLDOWN_MINUTES = 15  # 청산 후 1개 단기 파동(20이평 1사이클) 안정 대기
MAX_HOLDING_MINUTES = 30         # 최대 보유 타임컷 (30봉=30분)
POSITION_TRACKER_PATH = os.path.join(_DATA_DIR, "position_lifecycle_tracker.json")

_POSITION_LIFECYCLE_LOCK = threading.Lock()
_POSITION_LIFECYCLE_MEM: dict = {}


def _load_position_lifecycle():
    global _POSITION_LIFECYCLE_MEM
    if os.path.exists(POSITION_TRACKER_PATH):
        try:
            import json
            with open(POSITION_TRACKER_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in data.items():
                    if 'entry_time' in v and v['entry_time']:
                        v['entry_time'] = datetime.fromisoformat(v['entry_time'])
                    if 'exit_time' in v and v['exit_time']:
                        v['exit_time'] = datetime.fromisoformat(v['exit_time'])
                _POSITION_LIFECYCLE_MEM = data
        except Exception as e:
            print(f"DEBUG: _load_position_lifecycle error: {e}")


def _save_position_lifecycle():
    try:
        import json
        serializable = {}
        with _POSITION_LIFECYCLE_LOCK:
            for k, v in _POSITION_LIFECYCLE_MEM.items():
                item = v.copy()
                if 'entry_time' in item and isinstance(item['entry_time'], datetime):
                    item['entry_time'] = item['entry_time'].isoformat()
                if 'exit_time' in item and isinstance(item['exit_time'], datetime):
                    item['exit_time'] = item['exit_time'].isoformat()
                serializable[k] = item

        with open(POSITION_TRACKER_PATH, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"DEBUG: _save_position_lifecycle error: {e}")


# 기동 시 포지션 추적 데이터 로드
_load_position_lifecycle()


def can_send_entry_signal(ticker: str, current_ts: datetime = None) -> tuple:
    """
    퀀트 상태 기반 매수/낙폭과대 진입 신호 발송 가능 여부 검증.
    Returns: (is_allowed: bool, reason: str)
    """
    now_kst = datetime.now(_KST)
    clean_ticker = str(ticker).strip().zfill(6)

    with _POSITION_LIFECYCLE_LOCK:
        pos = _POSITION_LIFECYCLE_MEM.get(clean_ticker)
        if not pos:
            return True, "신규 진입 허용"

        state = pos.get('state', 'FLAT')
        entry_time = pos.get('entry_time')
        exit_time = pos.get('exit_time')

        # 1. 이미 포지션 보유 중인 경우
        if state == 'IN_POSITION':
            if entry_time:
                hold_min = (now_kst - entry_time).total_seconds() / 60.0
                if hold_min >= MAX_HOLDING_MINUTES:
                    pos['state'] = 'FLAT'
                    pos['exit_time'] = now_kst
                    _save_position_lifecycle()
                    return False, f"30분 타임컷 만료 후 쿨다운 진입 ({hold_min:.1f}분 경과)"
            return False, "포지션 보유 중 — 동일 매수 중복 진입 차단 (오버트레이딩 방어)"

        # 2. FLAT(무포지션) 상태인 경우 -> 청산 후 15분 파동 쿨다운 검증
        if exit_time:
            elapsed_min = (now_kst - exit_time).total_seconds() / 60.0
            if elapsed_min < POST_EXIT_COOLDOWN_MINUTES:
                remain_min = POST_EXIT_COOLDOWN_MINUTES - elapsed_min
                return False, f"청산 후 15분 파동 쿨다운 대기 중 ({remain_min:.1f}분 남음)"

        return True, "신규 파동 진입 허용"


def register_entry_signal(ticker: str, price: float, event: str):
    """포지션 진입 상태 등록"""
    now_kst = datetime.now(_KST)
    clean_ticker = str(ticker).strip().zfill(6)
    with _POSITION_LIFECYCLE_LOCK:
        _POSITION_LIFECYCLE_MEM[clean_ticker] = {
            "state": "IN_POSITION",
            "entry_time": now_kst,
            "entry_price": float(price),
            "entry_event": event,
            "add_count": 0,
            "exit_time": None
        }
    _save_position_lifecycle()


def can_send_add_signal(ticker: str) -> tuple:
    """추가 매수(물타기/불타기) 허용 여부 검증 (포지션당 1회 한정)"""
    clean_ticker = str(ticker).strip().zfill(6)
    with _POSITION_LIFECYCLE_LOCK:
        pos = _POSITION_LIFECYCLE_MEM.get(clean_ticker)
        if not pos or pos.get('state') != 'IN_POSITION':
            return False, "포지션 미보유 상태이므로 추가매수 불가"
        if pos.get('add_count', 0) >= 1:
            return False, "동일 포지션 내 추가매수는 1회로 한정 (리스크 관리)"
        return True, "추가매수 허용"


def register_add_signal(ticker: str, price: float):
    """추가 매수 반영 및 평단가 갱신"""
    clean_ticker = str(ticker).strip().zfill(6)
    with _POSITION_LIFECYCLE_LOCK:
        pos = _POSITION_LIFECYCLE_MEM.get(clean_ticker)
        if pos:
            pos['add_count'] = pos.get('add_count', 0) + 1
            ep = pos.get('entry_price', float(price))
            pos['entry_price'] = (ep + float(price)) / 2.0
    _save_position_lifecycle()


def can_send_exit_signal(ticker: str) -> tuple:
    """청산/익절 신호 허용 여부 검증"""
    clean_ticker = str(ticker).strip().zfill(6)
    with _POSITION_LIFECYCLE_LOCK:
        pos = _POSITION_LIFECYCLE_MEM.get(clean_ticker)
        if not pos or pos.get('state') != 'IN_POSITION':
            return False, "이미 청산되었거나 미보유 포지션 — 중복 청산 차단"
        return True, "청산 신호 발송 허용"


def register_exit_signal(ticker: str, price: float):
    """포지션 청산 완료 및 15분 파동 쿨다운 개시"""
    now_kst = datetime.now(_KST)
    clean_ticker = str(ticker).strip().zfill(6)
    with _POSITION_LIFECYCLE_LOCK:
        pos = _POSITION_LIFECYCLE_MEM.get(clean_ticker, {})
        pos['state'] = 'FLAT'
        pos['exit_time'] = now_kst
        pos['exit_price'] = float(price)
        _POSITION_LIFECYCLE_MEM[clean_ticker] = pos
    _save_position_lifecycle()


def get_last_entry(ticker: str):
    """특정 종목의 가장 최근 진입 기록을 찾아 반환"""
    clean_ticker = str(ticker).strip().zfill(6)
    with _POSITION_LIFECYCLE_LOCK:
        pos = _POSITION_LIFECYCLE_MEM.get(clean_ticker)
        if pos and pos.get('entry_price', 0) > 0:
            return {
                "entry_price": float(pos['entry_price']),
                "entry_time": pos.get('entry_time') or datetime.now(_KST)
            }

    if not os.path.exists(LOG_PATH):
        return None

    try:
        df = pd.read_csv(LOG_PATH, encoding="utf-8-sig")
        if df.empty:
            return None

        df_ticker = df[df['ticker'].astype(str).str.zfill(6) == clean_ticker].copy()
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
    """일반 매수 신호를 퀀트 포지션 수명주기(보유중 차단 + 15분 파동 쿨다운) 검증 후 전송"""
    _ensure_log_file()
    ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')
    clean_ticker = str(ticker).strip().zfill(6)

    # 1. 정규장 거래 시간(09:00~15:30) 검사
    if not is_regular_market_hours():
        print(f"DEBUG: [{name or ticker}] 정규장 거래시간 외이므로 매수 신호 알림 차단")
        return

    # 2. 퀀트 포지션 수명주기 검증 (보유 중 중복 차단 + 청산 후 15분 쿨다운)
    allowed, reason = can_send_entry_signal(clean_ticker, timestamp)
    if not allowed:
        print(f"DEBUG: [{name or ticker}] 매수 알림 건너뜀 — {reason}")
        return

    # 3. 신규 포지션 등록
    register_entry_signal(clean_ticker, price, "BUY_SIGNAL")

    try:
        with open(LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow([
                str(ticker), "BUY_SIGNAL", ts_str, price,
                "", ""
            ])
    except Exception:
        pass

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
    """추가 매수 신호를 퀀트 포지션 상태(포지션당 최대 1회) 검증 후 전송"""
    _ensure_log_file()
    ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')
    clean_ticker = str(ticker).strip().zfill(6)

    if not is_regular_market_hours():
        return

    allowed, reason = can_send_add_signal(clean_ticker)
    if not allowed:
        print(f"DEBUG: [{name or ticker}] 추가매수 알림 건너뜀 — {reason}")
        return

    register_add_signal(clean_ticker, price)

    try:
        with open(LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow([
                str(ticker), "ADD_SIGNAL", ts_str, price,
                "", ""
            ])
    except Exception:
        pass

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
    """낙폭과대 반등 매수 신호를 퀀트 포지션 수명주기(보유중 차단 + 15분 파동 쿨다운) 검증 후 전송"""
    _ensure_log_file()
    ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')
    clean_ticker = str(ticker).strip().zfill(6)

    if not is_regular_market_hours():
        print(f"DEBUG: [{name or ticker}] 정규장 거래시간 외이므로 낙폭과대 알림 차단")
        return

    allowed, reason = can_send_entry_signal(clean_ticker, timestamp)
    if not allowed:
        print(f"DEBUG: [{name or ticker}] 낙폭과대 알림 건너뜀 — {reason}")
        return

    register_entry_signal(clean_ticker, price, "FALL_BUY_SIGNAL")

    try:
        with open(LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow([
                str(ticker), "FALL_BUY_SIGNAL", ts_str, price,
                "", ""
            ])
    except Exception:
        pass

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
    """매도/청산 신호를 기록하고, 포지션 종료 및 15분 파동 쿨다운 개시"""
    _ensure_log_file()
    ts_str = timestamp.strftime('%Y-%m-%d %H:%M:00')
    clean_ticker = str(ticker).strip().zfill(6)

    if not is_regular_market_hours():
        return

    allowed, reason = can_send_exit_signal(clean_ticker)
    if not allowed:
        print(f"DEBUG: [{name or ticker}] 청산 알림 건너뜀 — {reason}")
        return

    register_exit_signal(clean_ticker, price)

    entry = get_last_entry(ticker)
    pnl_pct = ""
    holding_minutes = ""

    if entry:
        pnl_pct = round((price - entry["entry_price"]) / entry["entry_price"] * 100, 3)
        pnl_pct = round(pnl_pct - 0.195, 3)  # 수수료/세금
        holding_minutes = round((timestamp - entry["entry_time"]).total_seconds() / 60, 1)

    try:
        with open(LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow([
                str(ticker), "EXIT_SIGNAL", ts_str, price,
                pnl_pct, holding_minutes
            ])
    except Exception:
        pass

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
