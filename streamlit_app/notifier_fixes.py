# -*- coding: utf-8 -*-
"""
notifier_fixes.py  (신규 파일 — telegram_notifier.py / telegram_bot_daemon.py 와 같은 폴더에 둘 것)

텔레그램 알림 품질 보정 함수 모음. 각 함수가 어디에서 쓰이는지:

  is_duplicate_ko       : 한글 재작성 기사까지 잡는 중복 판정            → notifier, daemon
  is_crypto_junk        : 'eth'/'sol' 부분문자열 오탐 없는 코인 필터       → notifier, daemon
  stock_mentioned       : 종목명이 본문에 '단어'로 등장하는지 판정          → daemon
  kst_now_str           : 서버(UTC)가 아닌 KST 시각 문자열                 → notifier
  strip_cjk_lines       : 한글 없이 한자만 있는 줄(중국어 병기) 제거        → notifier
  smart_truncate        : 문장/줄 끝에서 자르기 (기존 [:300] 대체)          → notifier
  esc                   : 원문을 텔레그램 HTML 모드에 안전하게 삽입          → notifier
  sanitize_ai_html      : LLM 출력의 **굵게**·불릿·깨진 태그 정리           → notifier
  build_quant_section   : 종목 박스 (계산된 값만 표시, 가격 출처 표기)      → notifier
  lag_info/card_header  : 원문 시각·경과시간 표시, 지연 판정                → notifier, daemon
  extract_first_url / source_keyboard / merge_keyboards : 원문 바로가기 버튼 → notifier
  merge_state           : 상태 파일 일부 키만 안전하게 갱신(원자적 저장)      → notifier
  heartbeat_start/tick  : 스캐너 생존 진단 로그                             → daemon

※ 임계값(BIGRAM_THR 등)은 소규모 샘플로만 맞춘 미검증 휴리스틱입니다. 실제 로그로 재튜닝하세요.
"""
import os, re, json, time, tempfile
import html as _html
from datetime import datetime, timezone, timedelta

_KST = timezone(timedelta(hours=9))

# ───────────────────────── 시각 ─────────────────────────
def kst_now_str(fmt: str = '%m/%d %H:%M') -> str:
    """서버가 UTC(Streamlit Cloud)여도 KST로 표시"""
    return datetime.now(_KST).strftime(fmt)

def parse_post_time(iso: str):
    """<time datetime="2026-10-09T06:44:00+00:00"> 류 ISO 문자열 → KST datetime (실패 시 None)"""
    try:
        s = (iso or '').strip().replace('Z', '+00:00')
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_KST)
    except Exception:
        return None

def lag_info(post_iso: str, now=None):
    """(원문 KST 'MM/DD HH:MM', 발송까지 지연 분). 파싱 실패 시 ('', None)"""
    dt = parse_post_time(post_iso)
    if not dt:
        return '', None
    now = now or datetime.now(_KST)
    return dt.strftime('%m/%d %H:%M'), max(int((now - dt).total_seconds() // 60), 0)

def fmt_lag(lag_min) -> str:
    if lag_min is None:
        return ''
    return f"{lag_min}분 전" if lag_min < 60 else f"{lag_min // 60}시간 {lag_min % 60}분 전"

# ───────────────────────── 텍스트 정리 ─────────────────────────
def esc(text: str) -> str:
    """원문을 HTML 모드에 안전하게 삽입 (<, &, > 이스케이프)"""
    return _html.escape(text or '', quote=False)

_HAN = re.compile(r'[\u4e00-\u9fff]')
_HANGUL = re.compile(r'[가-힣]')

def strip_cjk_lines(text: str) -> str:
    """한글 없이 한자만 있는 줄(중국어 병기 원문) 제거. 한자 3자 미만이거나 한글이 있는 줄은 유지"""
    keep = [ln for ln in (text or '').split('\n')
            if not (len(_HAN.findall(ln)) >= 3 and not _HANGUL.search(ln))]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(keep)).strip()

def smart_truncate(text: str, limit: int = 300) -> str:
    """글자수 한도에서 문장/줄 끝에 맞춰 자름 (기존 [:300]은 문장 중간에서 끊김)"""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    ends = [cut.rfind(tok) + len(tok) for tok in ('\n', '다. ', '다.\n', '요. ', '. ') if cut.rfind(tok) != -1]
    end = max(ends) if ends else -1
    if end < limit * 0.5:
        end = cut.rfind(' ')
    if end <= 0:
        end = limit
    return cut[:end].rstrip() + ' …'

def sanitize_ai_html(text: str) -> str:
    """LLM 출력 정리: **굵게**→<b>, 마크다운 불릿→•, 허용 태그(b,i) 외 이스케이프, 태그 불균형 시 제거"""
    t = text or ''
    t = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', t, flags=re.S)
    t = re.sub(r'(?m)^\s*[\*\-]\s+', '• ', t)
    t = t.replace('*', '')
    t = re.sub(r'&(?!(?:amp|lt|gt|quot);)', '&amp;', t)
    t = re.sub(r'<(?!/?(?:b|i)>)', '&lt;', t)
    for tag in ('b', 'i'):
        if len(re.findall(rf'<{tag}>', t)) != len(re.findall(rf'</{tag}>', t)):
            t = re.sub(rf'</?{tag}>', '', t)
    return t.strip()

# ───────────────────────── 코인 필터 ─────────────────────────
_CRYPTO_KO = ['비트코인', '이더리움', '솔라나', '업비트', '빗썸', '바이낸스', '코인', '가상자산',
              '가상화폐', '에어드랍', '크립토', '민팅', '지갑 주소', '하이퍼리퀴드',
              '선물 일봉', '선물 숏', '선물 롱', '숏 포지션', '롱 포지션']
_CRYPTO_EN = re.compile(r'(?<![a-z])(btc|eth|sol|hype|nft|meme)(?![a-z])', re.I)   # 영문은 단어 경계

def is_crypto_junk(text: str) -> bool:
    low = (text or '').lower()
    return any(k in low for k in _CRYPTO_KO) or bool(_CRYPTO_EN.search(low))

# ───────────────────────── 중복 판정 ─────────────────────────
BIGRAM_THR = 0.45      # 두 글의 bigram 중첩(작은 쪽 기준) 임계값 — 미검증 휴리스틱
KEY_BONUS  = 0.10      # 영문/숫자 핵심토큰(HBM4, 112 등)이 겹치면 임계값을 이만큼 완화

def _norm(text: str) -> str:
    t = re.sub(r'https?://\S+', '', text or '')
    t = re.sub(r'\[[^\]]*\]', '', t)                 # [속보] 같은 태그 제거
    t = re.sub(r'[^0-9A-Za-z가-힣\s]', ' ', t)
    return re.sub(r'\s+', '', t).lower()             # 공백 제거 → 조사/띄어쓰기 차이 흡수

def _bigrams(s: str) -> set:
    return {s[i:i + 2] for i in range(len(s) - 1)}

_KEY = re.compile(r'[A-Za-z][A-Za-z0-9]+|\d+(?:[.,]\d+)*')
def _keys(text: str) -> set:
    return {k.lower() for k in _KEY.findall(text or '')}

def is_duplicate_ko(new_text: str, existing_texts: list, thr: float = BIGRAM_THR) -> bool:
    nn = _norm(new_text)
    if len(nn) < 10:
        return False
    bn, kn = _bigrams(nn), _keys(new_text)
    for ex in existing_texts:
        ne = _norm(ex)
        if len(ne) < 10:
            continue
        be = _bigrams(ne)
        overlap = len(bn & be) / max(1, min(len(bn), len(be)))
        bonus = KEY_BONUS if (kn & _keys(ex)) else 0.0
        if overlap >= (thr - bonus):
            return True
    return False

# ───────────────────────── 종목명 판정 ─────────────────────────
_JOSA = set('은는이가을를의에와과도로으만께서랑인엔')   # 종목명 뒤에 붙을 수 있는 조사(앞글자)

def stock_mentioned(text: str, name: str) -> bool:
    """
    본문에 종목명이 '단어로서' 등장하는지 판정.
    - 앞 글자가 한글/영숫자면 불인정 (복합어 일부)
    - 뒤 글자가 한글이면 조사일 때만 인정 ('테스트'의 '테스'는 불인정, '테스는'은 인정)
    ※ 약칭('하닉', '삼전')은 못 잡는 미검증 휴리스틱
    """
    if not name or not text:
        return False
    for m in re.finditer(re.escape(name), text):
        pre = text[m.start() - 1] if m.start() > 0 else ' '
        nxt = text[m.end()] if m.end() < len(text) else ' '
        if re.match(r'[가-힣A-Za-z0-9]', pre):
            continue
        if re.match(r'[가-힣]', nxt) and nxt not in _JOSA:
            continue
        return True
    return False

# ───────────────────────── 종목 카드 / 헤더 / 버튼 ─────────────────────────
def build_quant_section(name: str, code: str, cur_p: float, chg_r: float,
                        q_score=None, support_p=None, price_tag: str = '') -> str:
    """종목 박스. 퀀트점수/방어선은 '실제로 계산된 값이 있을 때만' 표시. 둘 다 없으면 제목을 '종목 현황'으로."""
    sign = "▲+" if chg_r >= 0 else "▼"
    icon = "🟢" if chg_r >= 0 else "🔴"
    tag = f" <i>({esc(price_tag)})</i>" if price_tag else ""
    parts = []
    if q_score is not None:
        parts.append(f"퀀트점수: <b>{q_score:.0f}점</b>")
    if support_p:
        parts.append(f"방어선: <b>{support_p:,.0f}원</b>")
    tail = ("\n  " + "  |  ".join(parts)) if parts else ""
    title = "GD 퀀트 진단" if parts else "종목 현황"
    return (f"\n📊 <b>{title}</b>\n"
            f"  종목: <b>{esc(name)}</b> ({code})\n"
            f"  현재가: <b>{cur_p:,.0f}원</b> {icon} {sign}{chg_r:.2f}%{tag}{tail}\n")   # 끝 \n → 구분선 붙음 방지

def card_header(icon: str, label: str, post_iso: str = '', now=None) -> str:
    """카드 헤더: 원문 시각(KST)+경과 표시. 원문 시각을 모르면 '수집 HH:MM'으로 명시"""
    post_kst, lag = lag_info(post_iso, now)
    when = f"원문 {post_kst} · {fmt_lag(lag)}" if post_kst else f"수집 {kst_now_str()}"
    return f"{icon} <b>[{esc(label)}]</b>  <i>{when}</i>"

def extract_first_url(text: str) -> str:
    m = re.search(r'https?://[^\s<>"\')]+', text or '')
    return m.group(0).rstrip('.,;') if m else ''

def source_keyboard(channel: str, post_id: str = '', article_url: str = '') -> dict:
    row = []
    if channel and post_id:
        row.append({"text": "🔗 텔레그램 원문", "url": f"https://t.me/{channel}/{post_id}"})
    if article_url:
        row.append({"text": "📰 기사 원문", "url": article_url})
    return {"inline_keyboard": [row]} if row else {}

def merge_keyboards(*kbs):
    rows = []
    for kb in kbs:
        if kb and kb.get('inline_keyboard'):
            rows.extend(kb['inline_keyboard'])
    return {"inline_keyboard": rows} if rows else None

# ───────────────────────── 상태 파일 ─────────────────────────
def load_state(path: str) -> dict:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(path: str, data: dict) -> bool:
    try:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)   # 폴더가 없어 조용히 실패하던 문제 방지
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or '.', suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)                                      # 원자적 교체
        return True
    except Exception as e:
        print(f"DEBUG: save_state 실패: {e}")
        return False

def merge_state(path: str, updates: dict) -> bool:
    """오래된 메모리 사본 전체를 덮어쓰지 않고, 최신 파일을 읽어 일부 키만 갱신"""
    st = load_state(path)
    st.update(updates)
    return save_state(path, st)

# ───────────────────────── 스캐너 생존 진단 ─────────────────────────
def heartbeat_start(path: str) -> None:
    """스캐너 기동 시 1회: 직전 하트비트와의 공백을 로그로 남김 → 앱 슬립/재시작 여부의 증거"""
    try:
        with open(path, 'r') as f:
            prev = float(f.read().strip())
        print(f"[scanner] 기동 {kst_now_str()} KST — 직전 하트비트 {int((time.time() - prev) // 60)}분 전")
    except Exception:
        print(f"[scanner] 기동 {kst_now_str()} KST — 이전 하트비트 없음(새 컨테이너 또는 최초 기동)")

def heartbeat_tick(path: str) -> None:
    """루프마다 현재 시각 기록 (실패해도 조용히 통과)"""
    try:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w') as f:
            f.write(str(time.time()))
    except Exception:
        pass