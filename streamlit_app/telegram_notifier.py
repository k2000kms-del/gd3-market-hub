# -*- coding: utf-8 -*-
"""
telegram_notifier.py
-------------------
스캘핑/퀀트 신호 및 포트폴리오 관리 텔레그램 실시간 푸시 알림 모듈.
- 🎯 목표가 / 🛑 손절가 / 💵 권장 비중 가이드 탑재
- 🌟 퀀트 강력 매수 유망주 알림 지원
- 🚨 스마트 손절 경고 알림 지원
- ☀️ 장전(08:50) / 🌙 장마감(15:40) 정기 브리핑 지원
"""

import requests
from datetime import datetime

# 텔레그램 Bot API 기본 URL
_TG_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"


def is_allowed_notification_hours() -> bool:
    """KST 기준 현재 시각이 알림 전송 허용 시간(평일 08:00 ~ 20:00)에 해당하는지 판별"""
    try:
        import datetime as dt
        kst_tz = dt.timezone(dt.timedelta(hours=9))
        now = dt.datetime.now(kst_tz)
        
        # 주말(토: 5, 일: 6) 제외
        if now.weekday() >= 5:
            return False
            
        current_time = now.time()
        start_time = dt.time(8, 0, 0)
        end_time = dt.time(20, 0, 0)
        
        return start_time <= current_time <= end_time
    except Exception as e:
        print(f"DEBUG: is_allowed_notification_hours error: {e}")
        return True


DEFAULT_REPLY_KEYBOARD = {
    "keyboard": [
        [{"text": "💼 내 포트폴리오"}, {"text": "🔥 퀀트 TOP3 추천"}],
        [{"text": "📊 시장 에너지 진단"}, {"text": "❓ 명령어 도움말"}]
    ],
    "resize_keyboard": True,
    "is_persistent": True
}


def _send(token: str, chat_id: str, text: str, parse_mode: str = "HTML", reply_markup: dict = None, force_send: bool = False) -> bool:
    """Telegram Bot API 호출 공통 헬퍼 (원터치 키보드 버튼 기본 탑재)"""
    if not token or not chat_id:
        print("DEBUG: 텔레그램 토큰 또는 Chat ID가 설정되지 않아 알림을 건너뜁니다.")
        return False

    if not force_send and not is_allowed_notification_hours():
        print("DEBUG: 알림 허용 시간 외이므로 전송을 차단합니다.")
        return False

    try:
        url = _TG_API_BASE.format(token=token)
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
            "reply_markup": reply_markup if reply_markup is not None else DEFAULT_REPLY_KEYBOARD
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


def _send_photo(token: str, chat_id: str, photo_bytes: bytes, caption: str = "", parse_mode: str = "HTML", reply_markup: dict = None, force_send: bool = False) -> bool:
    """Telegram Bot API sendPhoto 호출 공통 헬퍼 (차트 이미지 전송)"""
    if not token or not chat_id:
        print("DEBUG: 텔레그램 토큰 또는 Chat ID가 설정되지 않아 알림을 건너뜁니다.")
        return False

    if not force_send and not is_allowed_notification_hours():
        print("DEBUG: 알림 허용 시간 외이므로 전송을 차단합니다.")
        return False

    if not photo_bytes:
        return _send(token, chat_id, caption, parse_mode=parse_mode, reply_markup=reply_markup, force_send=force_send)

    try:
        import json
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        data = {
            "chat_id": chat_id,
            "caption": caption[:1024],
            "parse_mode": parse_mode,
            "reply_markup": json.dumps(reply_markup if reply_markup is not None else DEFAULT_REPLY_KEYBOARD)
        }
        files = {
            "photo": ("chart.png", photo_bytes, "image/png")
        }
        res = requests.post(url, data=data, files=files, timeout=10)
        if res.status_code == 200:
            return True
        else:
            print(f"DEBUG: 텔레그램 사진 전송 실패 (status={res.status_code}): {res.text[:100]}")
            return _send(token, chat_id, caption, parse_mode=parse_mode, reply_markup=reply_markup, force_send=force_send)
    except Exception as e:
        print(f"DEBUG: 텔레그램 사진 전송 예외 발생: {e}")
        return _send(token, chat_id, caption, parse_mode=parse_mode, reply_markup=reply_markup, force_send=force_send)


# ─────────────────────────────────────────────────────────────
# 1. 실시간 매매 신호 (목표가/손절가/비중 탑재)
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
    target_price: float = None,
    stop_price: float = None,
    allocation_pct: str = "10~15%",
) -> bool:
    """매수 신호 발생 시 액션 가이드 포함 텔레그램 알림 전송."""
    time_str = timestamp.strftime("%H:%M")
    
    tgt = target_price or (price * 1.035)
    stp = stop_price or (price * 0.975)
    tgt_pct = ((tgt - price) / price) * 100
    stp_pct = ((stp - price) / price) * 100

    extra_lines = ""
    if rsi is not None:
        extra_lines += f"\n├ RSI(14): <b>{rsi:.1f}</b>"
    if vwap is not None:
        extra_lines += f"\n└ VWAP: <b>{vwap:,.0f}원</b>"

    text = (
        f"🟢 <b>[실시간 매수 신호]</b> {name} ({ticker})\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 매수가: <b>{price:,.0f}원</b> (발생: {time_str}){extra_lines}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>1차 목표가</b>: <b>{tgt:,.0f}원</b> (+{tgt_pct:.1f}%)\n"
        f"🛑 <b>스마트 손절가</b>: <b>{stp:,.0f}원</b> ({stp_pct:.1f}%)\n"
        f"💵 <b>권장 비중</b>: <b>{allocation_pct}</b> 이내 분할 매수\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<i>⚡ GD 3.0 Market Hub 실시간 퀀트 신호</i>"
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
    """매도/청산 신호 발생 시 알림 전송."""
    time_str = timestamp.strftime("%H:%M")

    pnl_line = ""
    if pnl_pct is not None:
        pnl_emoji = "🎉" if pnl_pct >= 0 else "🛑"
        pnl_sign = "+" if pnl_pct >= 0 else ""
        pnl_line = f"\n├ 실현 손익률: <b>{pnl_sign}{pnl_pct:.2f}%</b> {pnl_emoji}"

    hold_line = ""
    if holding_minutes is not None:
        hold_line = f"\n└ 보유 시간: <b>{holding_minutes:.1f}분</b>"

    text = (
        f"🔴 <b>[포지션 청산/익절 신호]</b> {name} ({ticker})\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 현재가: <b>{price:,.0f}원</b> (시각: {time_str}){pnl_line}{hold_line}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>대응 가이드</b>: 수익 보존 및 리스크 관리를 위해 전량 또는 분할 매도를 권장합니다.\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<i>⚡ GD 3.0 Market Hub 실시간 신호</i>"
    )
    return _send(token, chat_id, text)


def notify_add_signal(
    token: str,
    chat_id: str,
    ticker: str,
    name: str,
    price: float,
    timestamp: datetime,
    rsi: float = None,
    vwap: float = None,
) -> bool:
    """스마트 추가 매수(물타기/불타기) 신호 알림."""
    time_str = timestamp.strftime("%H:%M")
    text = (
        f"🟠 <b>[스마트 추가 매수]</b> {name} ({ticker})\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 추가 매수가: <b>{price:,.0f}원</b> ({time_str})\n"
        f"📊 지표: RSI {rsi:.1f} / VWAP 지지 확인\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <b>가이드</b>: 평단가 조정을 위한 1차 동일 수량 분할 추가 매수 구간입니다.\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<i>⚡ GD 3.0 Market Hub</i>"
    )
    return _send(token, chat_id, text)


def notify_fall_buy_signal(
    token: str,
    chat_id: str,
    ticker: str,
    name: str,
    price: float,
    timestamp: datetime,
    rsi: float = None,
    vwap: float = None,
) -> bool:
    """낙폭과대 반등 매수 신호 알림."""
    time_str = timestamp.strftime("%H:%M")
    text = (
        f"🔵 <b>[낙폭과대 반등 매수]</b> {name} ({ticker})\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 매수가: <b>{price:,.0f}원</b> ({time_str})\n"
        f"📊 RSI: <b>{rsi:.1f}</b> (과매도 30 탈출 확인)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>가이드</b>: 단기 과매도 되돌림 파동 목표 (단기 +2~4% 목표)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<i>⚡ GD 3.0 Market Hub</i>"
    )
    return _send(token, chat_id, text)


# ─────────────────────────────────────────────────────────────
# 2. 🌟 퀀트 강력 매수 포착 알림 (점수 80점 이상 유망주)
# ─────────────────────────────────────────────────────────────

def notify_quant_top_pick(
    token: str,
    chat_id: str,
    ticker: str,
    name: str,
    score: float,
    price: float,
    chg_rate: float,
    supply_desc: str = "",
    target_price: float = None,
    stop_price: float = None,
) -> bool:
    """당일 퀀트 80점 이상 강력 매수 종목 포착 알림."""
    tgt = target_price or (price * 1.05)
    stp = stop_price or (price * 0.97)
    
    text = (
        f"🌟 <b>[퀀트 강력매수 포착 (TOP)]</b> {name} ({ticker})\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>퀀트 점수</b>: <b>{score:.1f}점</b> (Strong Buy)\n"
        f"💰 <b>현재가</b>: <b>{price:,.0f}원</b> ({chg_rate:+.2f}%)\n"
        f"📊 <b>수급 특징</b>: {supply_desc or '외국인/기관 동반 순매수 유입'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>1차 목표가</b>: <b>{tgt:,.0f}원</b> (+{((tgt-price)/price)*100:.1f}%)\n"
        f"🛑 <b>추천 손절가</b>: <b>{stp:,.0f}원</b> ({((stp-price)/price)*100:.1f}%)\n"
        f"💵 <b>권장 비중</b>: 포트폴리오 내 <b>15%</b> 이내\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<i>🏆 GD 3.0 퀀트 모멘텀 알고리즘</i>"
    )
    return _send(token, chat_id, text)


# ─────────────────────────────────────────────────────────────
# 3. 🚨 스마트 손절 경고 알림
# ─────────────────────────────────────────────────────────────

def notify_smart_stop_loss(
    token: str,
    chat_id: str,
    ticker: str,
    name: str,
    current_price: float,
    entry_price: float,
    stop_price: float,
) -> bool:
    """보유 종목 손절가 하향 이탈 시 스마트 경고 알림."""
    pnl_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
    text = (
        f"🚨 <b>[손절선 이탈 긴급 경고]</b> {name} ({ticker})\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 현재가: <b>{current_price:,.0f}원</b> (수익률: <b>{pnl_pct:.2f}%</b>)\n"
        f"🛑 설정 손절가: <b>{stop_price:,.0f}원</b> (하향 이탈 감지)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <b>대응 지침</b>: 추가 하락 방어를 위해 <b>즉시 손절 또는 50% 분할 매도</b>를 강력 권장합니다.\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<i>🛡️ GD 3.0 스마트 리스크 가디언</i>"
    )
    return _send(token, chat_id, text)


# ─────────────────────────────────────────────────────────────
# 4. ☀️ 장전(08:50) / 🌙 장마감(15:40) 정기 브리핑
# ─────────────────────────────────────────────────────────────

def notify_morning_briefing(
    token: str,
    chat_id: str,
    market_regime: str,
    cash_ratio: float,
    stock_ratio: float,
    bollinger_ma5: float,
    bollinger_status: str,
    top_quant_names: list,
) -> bool:
    """장 시작 전(08:50) 시장 전략 및 퀀트 브리핑."""
    top_str = ", ".join(top_quant_names[:4]) if top_quant_names else "집계 중"
    text = (
        f"☀️ <b>[GD 3.0 장전 시장 전략 브리핑]</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>시장 국면</b>: {market_regime}\n"
        f"⚡ <b>볼린저 에너지</b>: <b>{bollinger_status}</b> (5일평균 {bollinger_ma5:.1f}개 돌파)\n"
        f"💵 <b>오늘 권장 비중</b>: 주식 <b>{stock_ratio:.0f}%</b> / 현금 <b>{cash_ratio:.0f}%</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔥 <b>오늘의 퀀트 관심 TOP</b>: <b>{top_str}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<i>성공적인 투자를 응원합니다! 오늘도 원칙 매매 화이팅입니다!</i>"
    )
    return _send(token, chat_id, text)


def notify_closing_briefing(
    token: str,
    chat_id: str,
    total_eval: float,
    total_pnl: float,
    total_pct: float,
    port_count: int,
) -> bool:
    """장 마감(15:40) 포트폴리오 결산 브리핑."""
    pnl_sign = "+" if total_pnl >= 0 else ""
    pnl_emoji = "🎉" if total_pnl >= 0 else "📉"
    text = (
        f"🌙 <b>[GD 3.0 장마감 포트폴리오 결산]</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💼 <b>보유 종목 수</b>: <b>{port_count}개 종목</b>\n"
        f"💰 <b>총 평가금액</b>: <b>{total_eval:,.0f}원</b>\n"
        f"📊 <b>총 평가손익</b>: <b>{pnl_sign}{total_pnl:,.0f}원</b> ({pnl_sign}{total_pct:.2f}%) {pnl_emoji}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<i>오늘 하루도 수고 많으셨습니다. 편안한 저녁 되세요!</i>"
    )
    return _send(token, chat_id, text)


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
    """일봉 기준 골든크로스 매수 시그널 알림."""
    tgt = price * 1.05
    stp = price * 0.97
    extra_lines = ""
    if rsi is not None:
        extra_lines += f"\n├ RSI(14): <b>{rsi:.1f}</b>"
    if ma5 is not None and ma20 is not None:
        extra_lines += f"\n├ MA10: <b>{ma5:,.0f}원</b> / MA20: <b>{ma20:,.0f}원</b>"
    if vol_ratio is not None:
        extra_lines += f"\n└ 거래량: <b>{vol_ratio:.1f}배</b> 폭증"
    if signal_reason:
        extra_lines += f"\n\n📋 <i>{signal_reason}</i>"

    text = (
        f"📈 <b>[일봉 골든크로스 매수]</b> {name} ({ticker})\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 종가: <b>{price:,.0f}원</b> (기준일: {date}){extra_lines}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>스윙 목표가</b>: <b>{tgt:,.0f}원</b> (+5.0%)\n"
        f"🛑 <b>추천 손절가</b>: <b>{stp:,.0f}원</b> (-3.0%)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<i>⚡ GD 3.0 Market Hub</i>"
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
    """일봉 기준 데드크로스/과매수 매도 시그널 알림."""
    extra_lines = ""
    if entry_price and entry_price > 0:
        pnl = (price - entry_price) / entry_price * 100
        pnl_emoji = "📈" if pnl >= 0 else "📉"
        pnl_sign = "+" if pnl >= 0 else ""
        extra_lines += f"\n├ 평단가: <b>{entry_price:,.0f}원</b>"
        extra_lines += f"\n├ 수익률: <b>{pnl_sign}{pnl:.2f}%</b> {pnl_emoji}"

    if rsi is not None:
        extra_lines += f"\n├ RSI(14): <b>{rsi:.1f}</b>"
    if signal_reason:
        extra_lines += f"\n\n📋 <i>{signal_reason}</i>"

    text = (
        f"📉 <b>[일봉 매도/경고 신호]</b> {name} ({ticker})\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 당일 종가: <b>{price:,.0f}원</b> (기준일: {date}){extra_lines}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <b>대응 가이드</b>: 추세 약화 또는 과열 구간이므로 차익실현/손실방어를 권장합니다.\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<i>⚡ GD 3.0 Market Hub</i>"
    )
    return _send(token, chat_id, text)


# ─────────────────────────────────────────────────────────────
# 5. 🎯 트레일링 스탑 (동적 익절선) & 🚨 시장 급락 방어 알림
# ─────────────────────────────────────────────────────────────

def notify_trailing_stop(
    token: str,
    chat_id: str,
    ticker: str,
    name: str,
    current_price: float,
    entry_price: float,
    highest_price: float,
    drop_pct: float = 2.0,
) -> bool:
    """최고점 대비 일정 비율 하락 시 이익 보존을 위한 트레일링 스탑 알림."""
    pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
    text = (
        f"🎯 <b>[트레일링 스탑(추적 익절) 발동]</b> {name} ({ticker})\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>현재가</b>: <b>{current_price:,.0f}원</b> (확보 손익률: <b>+{pnl_pct:.2f}%</b>)\n"
        f"🏔️ <b>최고 도달가</b>: <b>{highest_price:,.0f}원</b> (고점 대비 -{drop_pct:.1f}% 이탈)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏆 <b>대응 전략</b>: 상승 추세 후 고점 되돌림이 발생했으므로 <b>전량 또는 50% 분할 익절</b>을 통해 확정 수익을 챙기세요!\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<i>⚡ GD 3.0 트레일링 가디언</i>"
    )
    return _send(token, chat_id, text)


def notify_market_crash_warning(
    token: str,
    chat_id: str,
    kospi_change_pct: float,
    reason: str = "지수 급락",
) -> bool:
    """시장 급락(-1.5% 이상) 시 신규 매수 차단 및 현금 확보 긴급 경고."""
    text = (
        f"🚨 <b>[시장 급락 비상 경고 (서킷 가디언)]</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📉 <b>KOSPI 변동률</b>: <b>{kospi_change_pct:+.2f}% 급락</b>\n"
        f"⚠️ <b>원인/상태</b>: {reason}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ <b>자동 시스템 조치</b>:\n"
        f"1. 모든 신규 매수 신호 알림을 <b>일시 차단</b>합니다.\n"
        f"2. 손실 방어를 위해 <b>현금 비중 70% 이상</b> 확보를 강력 권고합니다.\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<i>🛡️ GD 3.0 마켓 리스크 컨트롤러</i>"
    )
    return _send(token, chat_id, text)


# ─────────────────────────────────────────────────────────────
# 6. 🤖 텔레그램 양방향 대화형 비서 (명령어 처리기)
# ─────────────────────────────────────────────────────────────

def process_incoming_command(token: str, chat_id: str, cmd_text: str, context_fn) -> bool:
    """사용자가 보낸 텔레그램 메시지 또는 원터치 버튼 탭을 파싱하고 즉시 응답."""
    clean_cmd = cmd_text.strip().replace('/', '').lower()
    
    # 1. 퀀트 추천 (우선 매칭: '추천', '퀀트', 'quant', 'top3', 'top')
    if any(k in clean_cmd for k in ['추천', '퀀트', 'quant', 'top3', 'top']) or clean_cmd == 'q':
        # 퀀트 TOP 3 추천
        top_stocks = context_fn('quant_top') or []
        lines = []
        for rank, s in enumerate(top_stocks[:3], 1):
            lines.append(
                f"<b>{rank}위. {s['name']} ({s['code']})</b>\n"
                f"├ 🎯 퀀트 점수: <b>{s['score']:.1f}점</b>\n"
                f"├ 💰 현재가: {s['price']:,}원 ({s['chg']:+.2f}%)\n"
                f"└ 🎯 1차 목표가: <b>{int(s['price']*1.05):,}원</b> (+5.0%)"
            )
        recom_str = "\n\n".join(lines) if lines else "현재 추천 종목을 집계 중입니다."
        reply = (
            f"🌟 <b>[실시간 퀀트 TOP 3 추천주]</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{recom_str}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<i>💡 1위 추천 종목의 실시간 캔들 차트가 함께 첨부되었습니다.</i>"
        )
        
        # 1위 종목 차트 이미지 생성 시도
        chart_bytes = None
        if top_stocks:
            try:
                top1 = top_stocks[0]
                chart_df = context_fn('stock_chart', code=top1['code'])
                if chart_df is not None and not chart_df.empty:
                    from chart_image_generator import generate_stock_chart_image
                    chart_bytes = generate_stock_chart_image(
                        code=top1['code'],
                        name=top1['name'],
                        df=chart_df,
                        score=top1.get('score'),
                        target_price=top1.get('price', 0) * 1.05,
                        stop_loss=top1.get('price', 0) * 0.97
                    )
            except Exception as _ce:
                print(f"DEBUG: Quant chart gen error: {_ce}")

        if chart_bytes:
            return _send_photo(token, chat_id, chart_bytes, caption=reply, force_send=True)
        return _send(token, chat_id, reply, force_send=True)

    # 2. 포트폴리오 현황 ('포트', 'portfolio', '보유')
    elif any(k in clean_cmd for k in ['포트', 'portfolio', '보유']) or clean_cmd == 'p':
        ctx = context_fn('portfolio') or {}
        items = ctx.get('items', [])
        tot_eval = ctx.get('tot_eval', 0)
        tot_pnl = ctx.get('tot_pnl', 0)
        tot_pct = ctx.get('tot_pct', 0)
        pnl_sign = "+" if tot_pnl >= 0 else ""
        
        lines = []
        for it in items[:8]:
            p_sign = "+" if it['pnl_pct'] >= 0 else ""
            lines.append(f"• <b>{it['name']}</b>: {it['cur_price']:,}원 ({p_sign}{it['pnl_pct']:.1f}%)")
            
        stock_list_str = "\n".join(lines) if lines else "등록된 종목 없음"
        
        reply = (
            f"💼 <b>[내 실시간 포트폴리오 현황]</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 총 평가액: <b>{tot_eval:,.0f}원</b>\n"
            f"📊 총 손익: <b>{pnl_sign}{tot_pnl:,.0f}원</b> ({pnl_sign}{tot_pct:.2f}%)\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{stock_list_str}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<i>💡 하단 원터치 버튼을 누르시면 즉시 갱신됩니다.</i>"
        )
        return _send(token, chat_id, reply, force_send=True)

    # 3. 시장 에너지 진단 ('시장', 'market', '에너지', '코스피')
    elif any(k in clean_cmd for k in ['시장', 'market', '에너지', '코스피', '지수']) or clean_cmd == 'm':
        mkt = context_fn('market') or {}
        reply = (
            f"📊 <b>[실시간 시장 & 자산배분 브리핑]</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📈 <b>KOSPI</b>: {mkt.get('kospi_close', 0):,.2f}pt\n"
            f"⚡ <b>볼린저 돌파 5MA</b>: <b>{mkt.get('b_ma5', 0):.1f}개</b> ({mkt.get('b_status', '보통')})\n"
            f"💵 <b>현재 권장 비중</b>: 주식 <b>{mkt.get('stock_ratio', 50):.0f}%</b> / 현금 <b>{mkt.get('cash_ratio', 50):.0f}%</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<i>💡 하단 원터치 버튼을 누르시면 즉시 갱신됩니다.</i>"
        )
        return _send(token, chat_id, reply, force_send=True)

    # 4. 도움말 ('도움말', 'help', 'start', '시작', '안내')
    elif any(k in clean_cmd for k in ['도움말', 'help', 'start', '시작', '안내']) or clean_cmd == 'h':
        reply = (
            f"🤖 <b>[GD 3.0 텔레그램 스마트 비서]</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"대표님, 아래 <b>하단 고정 버튼</b>을 누르시면 0.5초 만에 즉시 확인하실 수 있습니다:\n\n"
            f"• <b>[💼 내 포트폴리오]</b> : 보유종목 실시간 손익\n"
            f"• <b>[🔥 퀀트 TOP3 추천]</b> : 80점 이상 유망 종목\n"
            f"• <b>[📊 시장 에너지 진단]</b> : KOSPI 국면 & 권장 비중\n"
            f"• <b>[❓ 명령어 도움말]</b> : 비서 메뉴얼\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<i>💬 궁금하신 종목 질문(예: '삼성전자 목표가?')을 입력하셔도 AI가 답변합니다!</i>"
        )
        return _send(token, chat_id, reply, force_send=True)

    return False
