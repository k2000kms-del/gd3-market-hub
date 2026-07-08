# -*- coding: utf-8 -*-
"""
telegram_notifier.py
-------------------
스캘핑 신호 발생 시 텔레그램 봇으로 실시간 푸시 알림을 전송하는 모듈.
requests 라이브러리만 사용하므로 별도 패키지 설치 불필요.
"""

import requests
from datetime import datetime

# 텔레그램 Bot API 기본 URL
_TG_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"

# ─────────────────────────────────────────────────────────────
# 내부 헬퍼 함수
# ─────────────────────────────────────────────────────────────

def is_krx_market_hours() -> bool:
    """KST 기준 현재 시각이 KRX 정규장 운영 시간(평일 09:00 ~ 15:30)에 해당하는지 판별"""
    try:
        import datetime as dt
        # 내장 timezone을 활용하여 KST(UTC+9) 타임존 객체 생성
        kst_tz = dt.timezone(dt.timedelta(hours=9))
        now = dt.datetime.now(kst_tz)
        
        # 주말(토: 5, 일: 6) 제외
        if now.weekday() >= 5:
            return False
            
        current_time = now.time()
        start_time = dt.time(9, 0, 0)
        end_time = dt.time(15, 30, 0)
        
        return start_time <= current_time <= end_time
    except Exception as e:
        print(f"DEBUG: is_krx_market_hours error: {e}")
        return True # 예외 발생 시 알림 유실 방지용 폴백

def _send(token: str, chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    """텔레그램 Bot API로 메시지를 전송하는 내부 함수.
    
    Returns:
        bool: 전송 성공 여부
    """
    if not token or not chat_id:
        print("DEBUG: 텔레그램 토큰 또는 Chat ID가 설정되지 않아 알림을 건너뜁니다.")
        return False

    # KRX 정규장 시간 외에는 알림 전송 차단
    if not is_krx_market_hours():
        print("DEBUG: 현재 시각이 KRX 정규장 시간(평일 09:00~15:30) 외의 시간대이므로 텔레그램 알림 전송을 차단합니다.")
        return False
    try:
        url = _TG_API_BASE.format(token=token)
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        res = requests.post(url, json=payload, timeout=5)
        if res.status_code == 200:
            return True
        else:
            print(f"DEBUG: 텔레그램 전송 실패 (status={res.status_code}): {res.text[:100]}")
            return False
    except Exception as e:
        print(f"DEBUG: 텔레그램 전송 예외 발생: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────

def notify_buy_signal(
    token: str,
    chat_id: str,
    ticker: str,
    name: str,
    price: float,
    timestamp: datetime,
    rsi: float = None,
    vwap: float = None,
) -> bool:
    """매수 신호(BUY_SIGNAL) 발생 시 텔레그램 알림 전송.
    
    Args:
        token:     텔레그램 봇 토큰 (secrets.toml 의 TELEGRAM_BOT_TOKEN)
        chat_id:   수신자 Chat ID (secrets.toml 의 TELEGRAM_CHAT_ID)
        ticker:    종목 코드 (예: '005930')
        name:      종목명 (예: '삼성전자')
        price:     신호 발생 시 종가
        timestamp: 신호 발생 시각 (datetime)
        rsi:       RSI 값 (선택)
        vwap:      VWAP 값 (선택)
    
    Returns:
        bool: 전송 성공 여부
    """
    time_str = timestamp.strftime("%H:%M")
    
    # 보조지표 줄 구성
    extra_lines = ""
    if rsi is not None:
        extra_lines += f"\n├ RSI(14): <b>{rsi:.1f}</b>"
    if vwap is not None:
        extra_lines += f"\n└ VWAP: <b>{vwap:,.0f}원</b>"

    text = (
        f"🟢 <b>[매수 신호]</b> {name} ({ticker})\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 현재가: <b>{price:,.0f}원</b>\n"
        f"⏰ 발생 시각: {time_str}"
        f"{extra_lines}\n"
        f"━━━━━━━━━━━━━━\n"
        f"<i>GD 3.0 Market Hub 스캘핑 신호</i>"
    )
    return _send(token, chat_id, text)


def notify_exit_signal(
    token: str,
    chat_id: str,
    ticker: str,
    name: str,
    price: float,
    timestamp: datetime,
    pnl_pct: float = None,
    holding_minutes: float = None,
) -> bool:
    """매도/청산 신호(EXIT_SIGNAL) 발생 시 텔레그램 알림 전송.
    
    Args:
        token:           텔레그램 봇 토큰
        chat_id:         수신자 Chat ID
        ticker:          종목 코드
        name:            종목명
        price:           신호 발생 시 종가
        timestamp:       신호 발생 시각
        pnl_pct:         실현 손익률 (%) — None이면 미계산
        holding_minutes: 보유 시간 (분) — None이면 미계산
    
    Returns:
        bool: 전송 성공 여부
    """
    time_str = timestamp.strftime("%H:%M")

    # 손익 라인
    if pnl_pct is not None:
        pnl_emoji = "📈" if pnl_pct >= 0 else "📉"
        pnl_sign  = "+" if pnl_pct >= 0 else ""
        pnl_line  = f"\n├ 손익률: <b>{pnl_sign}{pnl_pct:.3f}%</b> {pnl_emoji}"
    else:
        pnl_line  = ""

    # 보유시간 라인
    if holding_minutes is not None:
        hold_line = f"\n└ 보유 시간: <b>{holding_minutes:.1f}분</b>"
    else:
        hold_line = ""

    text = (
        f"🔴 <b>[청산 신호]</b> {name} ({ticker})\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 현재가: <b>{price:,.0f}원</b>\n"
        f"⏰ 발생 시각: {time_str}"
        f"{pnl_line}"
        f"{hold_line}\n"
        f"━━━━━━━━━━━━━━\n"
        f"<i>GD 3.0 Market Hub 스캘핑 신호</i>"
    )
    return _send(token, chat_id, text)


def notify_custom(token: str, chat_id: str, message: str) -> bool:
    """임의 텍스트 메시지를 텔레그램으로 전송.
    
    Args:
        token:   텔레그램 봇 토큰
        chat_id: 수신자 Chat ID
        message: 전송할 메시지 (HTML 태그 사용 가능)
    
    Returns:
        bool: 전송 성공 여부
    """
    return _send(token, chat_id, message)


def notify_daily_buy_signal(
    token: str,
    chat_id: str,
    ticker: str,
    name: str,
    price: float,
    date: str,
    rsi: float = None,
    ma5: float = None,
    ma20: float = None,
    vol_ratio: float = None,
    signal_reason: str = "",
) -> bool:
    """일봉 기준 매수 시그널 발생 시 텔레그램 알림 전송.

    Args:
        token:         텔레그램 봇 토큰
        chat_id:       수신자 Chat ID
        ticker:        종목 코드 (예: '005930')
        name:          종목명 (예: '삼성전자')
        price:         당일 종가
        date:          발생 날짜 문자열 (예: '2026-07-05')
        rsi:           RSI(14) 값 (선택)
        ma5:           5일 이동평균 (선택)
        ma20:          20일 이동평균 (선택)
        vol_ratio:     거래량 / 20일 평균 거래량 비율 (선택)
        signal_reason: 신호 발생 이유 요약 문자열 (선택)

    Returns:
        bool: 전송 성공 여부
    """
    extra_lines = ""
    if rsi is not None:
        extra_lines += f"\n├ RSI(14): <b>{rsi:.1f}</b>"
    if ma5 is not None and ma20 is not None:
        extra_lines += f"\n├ MA5: <b>{ma5:,.0f}원</b> / MA20: <b>{ma20:,.0f}원</b>"
    if vol_ratio is not None:
        extra_lines += f"\n└ 거래량 배율: <b>{vol_ratio:.1f}배</b> (20일 평균 대비)"
    if signal_reason:
        extra_lines += f"\n\n📋 <i>{signal_reason}</i>"

    text = (
        f"📈 <b>[일봉 매수신호]</b> {name} ({ticker})\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 당일 종가: <b>{price:,.0f}원</b>\n"
        f"📅 기준일: {date}"
        f"{extra_lines}\n"
        f"━━━━━━━━━━━━━━\n"
        f"<i>GD 3.0 Market Hub 일봉 시그널</i>"
    )
    return _send(token, chat_id, text)


def notify_daily_sell_signal(
    token: str,
    chat_id: str,
    ticker: str,
    name: str,
    price: float,
    date: str,
    entry_price: float = None,
    rsi: float = None,
    ma5: float = None,
    ma20: float = None,
    signal_reason: str = "",
) -> bool:
    """일봉 기준 매도 시그널 발생 시 텔레그램 알림 전송.

    Args:
        token:         텔레그램 봇 토큰
        chat_id:       수신자 Chat ID
        ticker:        종목 코드
        name:          종목명
        price:         당일 종가
        date:          발생 날짜 문자열
        entry_price:   포트폴리오 매수 평단가 (손익 표시용, 선택)
        rsi:           RSI(14) 값 (선택)
        ma5:           5일 이동평균 (선택)
        ma20:          20일 이동평균 (선택)
        signal_reason: 신호 발생 이유 요약 문자열 (선택)

    Returns:
        bool: 전송 성공 여부
    """
    extra_lines = ""

    # 수익률 계산 (평단가가 있는 경우)
    if entry_price and entry_price > 0:
        pnl = (price - entry_price) / entry_price * 100
        pnl_emoji = "📈" if pnl >= 0 else "📉"
        pnl_sign = "+" if pnl >= 0 else ""
        extra_lines += f"\n├ 평단가: <b>{entry_price:,.0f}원</b>"
        extra_lines += f"\n├ 수익률: <b>{pnl_sign}{pnl:.2f}%</b> {pnl_emoji}"

    if rsi is not None:
        extra_lines += f"\n├ RSI(14): <b>{rsi:.1f}</b>"
    if ma5 is not None and ma20 is not None:
        extra_lines += f"\n└ MA5: <b>{ma5:,.0f}원</b> / MA20: <b>{ma20:,.0f}원</b>"
    if signal_reason:
        extra_lines += f"\n\n📋 <i>{signal_reason}</i>"

    text = (
        f"📉 <b>[일봉 매도신호]</b> {name} ({ticker})\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 당일 종가: <b>{price:,.0f}원</b>\n"
        f"📅 기준일: {date}"
        f"{extra_lines}\n"
        f"━━━━━━━━━━━━━━\n"
        f"<i>GD 3.0 Market Hub 일봉 시그널</i>"
    )
    return _send(token, chat_id, text)
