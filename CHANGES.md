# 수정 지시서 — 텔레그램 알림 개선

대상: `telegram_notifier.py` (11건) · `telegram_bot_daemon.py` (11건) · `app.py` (1건) + 새 파일 `notifier_fixes.py` 1개

> 이 문서의 모든 '찾을 문구 → 바꿀 문구'는 업로드해 주신 원본 파일에 **실제로 적용해서 검증**한 것입니다. 각 '찾을 문구'는 해당 파일에서 정확히 1곳에만 일치합니다.

## 0. 적용 방법 (셋 중 하나)

**방법 A — 파일 통째로 교체 (가장 간단)**: `patched/` 폴더의 3개 파일로 기존 파일을 덮어쓰고, `notifier_fixes.py` 를 같은 폴더에 추가합니다(이 방법은 CHANGES.md 가 필요 없습니다). ※ 안티그래비티 작업공간의 파일이 업로드해 주신 파일과 **동일할 때만** 사용하세요(다르면 방법 B).

**방법 B — 안티그래비티에 지시문으로 붙여넣기 (이 문서 하나면 충분)**: 이 `CHANGES.md` 전체를 붙여넣으면 됩니다. 1장에 새 파일 내용이, 2~4장에 '찾을 문구/바꿀 문구'가 모두 들어 있습니다.

**방법 C — 패치 파일**: `patched/*.patch` 를 `git apply telegram_notifier.py.patch` 처럼 적용합니다.

> **줄바꿈 안내**: 세 원본 파일은 윈도우식 줄바꿈(CRLF)입니다. 방법 A·C 의 파일은 CRLF 를 보존해 만들었고(원본 대비 실제 바뀐 줄만 diff 에 나타남), 방법 B 로 직접 수정할 때는 편집기가 줄바꿈을 LF 로 바꾸지 않도록 주의하세요. 새 파일 `notifier_fixes.py` 는 LF 이며 파이썬에서는 차이가 없습니다.

### 안티그래비티 붙여넣기용 프롬프트

```text
아래 지시서대로 파일 3개를 수정하고 새 파일 1개를 추가해줘.
규칙:
1) 각 수정은 '찾을 문구'가 해당 파일에서 정확히 한 번만 나오는지 먼저 확인하고, 한 번이면 '바꿀 문구'로 교체해.
2) 0번이거나 2번 이상 나오면 수정하지 말고 어떤 항목(ID)이 왜 안 되는지 알려줘.
3) 지시서에 없는 부분은 절대 건드리지 마. 들여쓰기와 공백은 그대로 유지하고, 원본 파일의 줄바꿈(CRLF)도 그대로 유지해. 비교할 때 CRLF/LF 차이는 무시해.
4) 먼저 이 문서 1번 항목의 코드 블록 전체를 notifier_fixes.py 라는 새 파일로, telegram_notifier.py 와 같은 폴더에 만들어줘(내용은 한 글자도 바꾸지 마).
5) 끝나면 세 파일에 대해 `python -m py_compile 파일명` 을 실행해 문법 오류가 없는지 확인해줘.
```

## 1. 새 파일: `notifier_fixes.py` (먼저 이 파일부터 만드세요)

`telegram_notifier.py` · `telegram_bot_daemon.py` 와 **같은 폴더**에 아래 코드 블록 전체를 `notifier_fixes.py` 라는 이름의 새 파일로 저장합니다. 이 파일이 없으면 2·3장 수정 후 두 파일이 import 오류로 실행되지 않습니다. GitHub/Streamlit Cloud 에 배포한다면 이 파일도 **함께 커밋**해야 합니다.

```python
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
```

## 2. `telegram_notifier.py` — 11건 (알림 카드 생성·발송 모듈)

파일 위에서 아래 순서(원본 줄 번호순)로 정렬했습니다. 줄 번호는 **수정 전 원본 기준**이며, 앞의 수정이 적용되면 밀리므로 줄 번호가 아니라 '찾을 문구'로 위치를 찾으세요.

### [N1] notifier_fixes 가져오기 (파일 상단 import)

- **위치**: 원본 12~15행
- **이유**: 새로 추가한 notifier_fixes.py 의 함수들을 사용하기 위한 import. 이 줄이 없으면 아래 수정 전부가 동작하지 않습니다.

**찾을 문구** (이 블록 전체)

```python
import requests
from datetime import datetime

# 텔레그램 Bot API 기본 URL
```

**바꿀 문구**

```python
import requests
from datetime import datetime
from notifier_fixes import (
    is_duplicate_ko, is_crypto_junk, merge_state, kst_now_str,
    strip_cjk_lines, smart_truncate, esc, sanitize_ai_html,
    build_quant_section, card_header, extract_first_url,
    source_keyboard, merge_keyboards,
)

# 텔레그램 Bot API 기본 URL
```

### [N2] 코인 필터 오탐 수정 (_clean_channel_text)

- **위치**: 원본 993~1006행
- **이유**: 부분문자열 비교('eth','sol','hype')라서 Ethernet·Solar·hyperscaler 같은 정상 뉴스가 통째로 삭제되던 문제. 영문은 단어 경계로 비교하도록 교체.

**찾을 문구** (이 블록 전체)

```python
    # 5. 코인/가상자산/크립토/단순 선물 메모 100% 원천 차단 (국내/해외 주식 전용)
    crypto_junk = [
        '하이퍼리퀴드', 'hype', '비트코인', 'btc', '이더리움', 'eth', '솔라나', 'sol',
        '업비트', '빗썸', '바이낸스', '코인', '가상자산', '가상화폐', '에어드랍',
        '선물 일봉', '선물 숏', '선물 롱', '숏 포지션', '롱 포지션', '크립토',
        'nft', 'meme', '민팅', '지갑 주소'
    ]
    t_lower = t.lower()
    for cj in crypto_junk:
        if cj in t_lower:
            return ""

    t = t.strip()
    # 6. 정제 후 순수 본문 길이가 35자 미만이면 의미 없는 단편/공백/1줄 메모로 간주
```

**바꿀 문구**

```python
    # 5. 코인/가상자산/크립토/단순 선물 메모 100% 원천 차단 (국내/해외 주식 전용)
    #    [수정] 부분문자열 오탐(Ethernet, Solar 등) 방지 → notifier_fixes.is_crypto_junk 사용
    if is_crypto_junk(t):
        return ""

    t = t.strip()
    # 6. 정제 후 순수 본문 길이가 35자 미만이면 의미 없는 단편/공백/1줄 메모로 간주
```

### [N3] notify_external_channel_alert 인자 추가 (post_meta)

- **위치**: 원본 3004~3009행
- **이유**: 수집기(daemon)가 원문 시각·전달 출처·링크 정보를 넘길 수 있도록 post_meta 인자 추가. 기본값 None 이라 기존 호출은 그대로 동작합니다.

**찾을 문구** (이 블록 전체)

```python
    matched_stock: dict = None,
    token: str = None,
    chat_id: str = None
) -> bool:
    """
    외부 텔레그램 채널(예: elite_instructor)의 단타/속보 메시지를 포착하고
```

**바꿀 문구**

```python
    matched_stock: dict = None,
    token: str = None,
    chat_id: str = None,
    post_meta: dict = None
) -> bool:
    """
    외부 텔레그램 채널(예: elite_instructor)의 단타/속보 메시지를 포착하고
```

### [N4] 중복으로 붙여넣어진 상태 로드 블록 1개 삭제

- **위치**: 원본 3015~3044행
- **이유**: 같은 블록이 연달아 두 번 들어 있었습니다(복붙 실수). 한 번만 남기고 삭제. 동작 변화 없음.

**찾을 문구** (이 블록 전체)

```python
    # ── [30분 이내 동일/유사 속보 중복 발송 차단 2중 방어] ──
    base_dir = os.path.dirname(os.path.abspath(__file__))
    state_file = os.path.join(base_dir, 'data', 'last_briefing_state.json')
    if not os.path.exists(state_file):
        state_file = os.path.join(base_dir, 'streamlit_app', 'data', 'last_briefing_state.json')

    now_ts = time.time()
    b_state = {}
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                b_state = json.load(f)
        except Exception:
            b_state = {}

    # ── [30분 이내 동일/유사 속보 중복 발송 차단 2중 방어] ──
    base_dir = os.path.dirname(os.path.abspath(__file__))
    state_file = os.path.join(base_dir, 'data', 'last_briefing_state.json')
    if not os.path.exists(state_file):
        state_file = os.path.join(base_dir, 'streamlit_app', 'data', 'last_briefing_state.json')

    now_ts = time.time()
    b_state = {}
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                b_state = json.load(f)
        except Exception:
            b_state = {}

```

**바꿀 문구**

```python
    # ── [30분 이내 동일/유사 속보 중복 발송 차단 2중 방어] ──
    base_dir = os.path.dirname(os.path.abspath(__file__))
    state_file = os.path.join(base_dir, 'data', 'last_briefing_state.json')
    if not os.path.exists(state_file):
        state_file = os.path.join(base_dir, 'streamlit_app', 'data', 'last_briefing_state.json')

    now_ts = time.time()
    b_state = {}
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                b_state = json.load(f)
        except Exception:
            b_state = {}

```

### [N5] 중복 판정 강화 (한글 재작성 기사까지 차단)

- **위치**: 원본 3049~3050행
- **이유**: 기존 공백 단위 자카드는 조사 때문에 같은 뉴스를 다르게 쓴 글을 못 잡습니다(실측 유사도 0.05). 새 판정을 먼저 적용하고 기존 판정도 그대로 유지(OR).

**찾을 문구** (이 블록 전체)

```python
    if _is_duplicate_content(raw_message, existing_texts, threshold=0.55):
        print(f"[{time.strftime('%H:%M:%S')}] ⏭️ [중복 방지] {channel_name} 유사 속보 이미 발송됨 (30분 중복 스킵): {raw_message[:40]}...")
```

**바꿀 문구**

```python
    if is_duplicate_ko(raw_message, existing_texts) or _is_duplicate_content(raw_message, existing_texts, threshold=0.55):
        print(f"[{time.strftime('%H:%M:%S')}] ⏭️ [중복 방지] {channel_name} 유사 속보 이미 발송됨 (30분 중복 스킵): {raw_message[:40]}...")
```

### [N6] 가짜 퀀트점수·방어선 제거 + 현재가 실시간화

- **위치**: 원본 3082~3094행
- **이유**: daemon 이 넘기던 quant_score=85.0(고정), support_price=현재가×0.97(계산식 아님)이 그대로 '퀀트점수·방어선'으로 표시되던 문제. 값이 없으면 표시하지 않고, 현재가는 네이버 실시간 시세로 덮어쓰며 출처(실시간/스냅샷)를 표기합니다.

**찾을 문구** (이 블록 전체)

```python
        cur_p = matched_stock.get('price', 0)
        chg_r = matched_stock.get('change_ratio', 0.0)
        q_score = matched_stock.get('quant_score', 80)
        jumping_status = matched_stock.get('jumping_status', '채널 포착')
        support_p = matched_stock.get('support_price', cur_p * 0.97)
        sign = "▲+" if chg_r >= 0 else "▼"
        pnl_icon = "🟢" if chg_r >= 0 else "🔴"
        quant_section = (
            f"\n📊 <b>GD 퀀트 진단</b>\n"
            f"  종목: <b>{name}</b> ({code})\n"
            f"  현재가: <b>{cur_p:,.0f}원</b> {pnl_icon} {sign}{chg_r:.2f}%\n"
            f"  퀀트점수: <b>{q_score:.0f}점</b>  |  방어선: <b>{support_p:,.0f}원</b>"
        )
```

**바꿀 문구**

```python
        cur_p = matched_stock.get('price', 0)
        chg_r = matched_stock.get('change_ratio', 0.0)
        q_score = matched_stock.get('quant_score')               # [수정] 계산된 값이 없으면 None (기본값 80 제거)
        jumping_status = matched_stock.get('jumping_status', '채널 포착')
        support_p = matched_stock.get('support_price') or None   # [수정] 현재가×0.97 가짜 방어선 제거
        _rt = fetch_realtime_stock_info(code)                    # [수정] CSV 스냅샷 대신 실시간 시세로 덮어쓰기
        if _rt:
            cur_p, chg_r = _rt['price'], _rt['chg']
        quant_section = build_quant_section(name, code, cur_p, chg_r, q_score, support_p,
                                            '실시간' if _rt else '스냅샷')
```

### [N7] 중국어 병기 줄 제거 (속보 본문 정제)

- **위치**: 원본 3097~3099행
- **이유**: 원문에 섞여 오는 중국어 줄(한글 없이 한자만 있는 줄)이 카드에 그대로 노출되던 문제.

**찾을 문구** (이 블록 전체)

```python
    clean_raw = _clean_channel_text(raw_message)
    if len(clean_raw) < 20:
        return False
```

**바꿀 문구**

```python
    clean_raw = strip_cjk_lines(_clean_channel_text(raw_message))   # [수정] 중국어 병기 줄 제거
    if len(clean_raw) < 20:
        return False
```

### [N8] 카드 본문 개선 (KST 헤더·원문시각, 문장 단위 자르기, AI 서식 정리, 원문 버튼)

- **위치**: 원본 3139~3152행
- **이유**: ① 헤더 시각이 UTC 로 9시간 어긋나던 것을 원문 시각(KST)+경과시간으로 표시 ② 원문이 문장 중간에서 잘리던 것을 문장 끝에서 자름 ③ 원문의 <,& 문자 이스케이프 ④ AI 분석의 **굵게** 별표·깨진 태그 정리 ⑤ '텔레그램 원문/기사 원문' 버튼 추가(종목 버튼과 병합). 원문 시각을 못 받은 경우 '수집 HH:MM'으로 표시합니다.

**찾을 문구** (이 블록 전체)

```python
    now_time_str = time.strftime('%m/%d %H:%M')
    header_icon = "🚨" if matched_stock else "📡"
    text = (
        f"{header_icon} <b>[{ch_display}] 속보</b>  <i>{now_time_str}</i>\n"
        f"{'─' * 20}\n"
        f"<i>{clean_raw[:300]}</i>\n"
        f"{'─' * 20}\n"
        f"💡 <b>GD AI 분석:</b>\n{ai_analysis}\n"
        f"{quant_section}"
        f"{'─' * 20}\n"
        f"⚠️ <i>속보성 급등락 뇌동매매 금지 · 원칙 매매 준수</i>"
    )

    markup = make_stock_action_keyboard(code, name) if code else None
```

**바꿀 문구**

```python
    pm = post_meta or {}
    header_icon = "🚨" if matched_stock else "📡"
    _label = ch_display + (f" ← {pm['forwarded_from']}" if pm.get('forwarded_from') else "")
    text = (
        f"{card_header(header_icon, _label, pm.get('time_iso', ''))}\n"
        f"{'─' * 20}\n"
        f"<i>{esc(smart_truncate(clean_raw, 300))}</i>\n"
        f"{'─' * 20}\n"
        f"💡 <b>GD AI 분석:</b>\n{sanitize_ai_html(ai_analysis)}\n"
        f"{quant_section}"
        f"{'─' * 20}\n"
        f"⚠️ <i>속보성 급등락 뇌동매매 금지 · 원칙 매매 준수</i>"
    )

    _urls = pm.get('urls') or []
    _src_kb = source_keyboard(pm.get('channel') or channel_name, pm.get('post_id', ''),
                              _urls[0] if _urls else extract_first_url(raw_message))
    markup = merge_keyboards(make_stock_action_keyboard(code, name) if code else None, _src_kb)
```

### [N9] 상태 파일 저장을 '일부 키만 갱신'으로 변경

- **위치**: 원본 3168~3175행
- **이유**: 함수 시작 시점의 오래된 b_state 전체를 되덮어쓰면 그 사이 다른 스레드(예: 앱의 모닝브리핑 보상 로직)가 기록한 값이 지워질 수 있어, 최신 파일을 읽어 recent_urgent_alerts 키만 갱신(원자적 저장)합니다.

**찾을 문구** (이 블록 전체)

```python
        b_state['recent_urgent_alerts'] = recent_urgent[-20:]
        try:
            with open(state_file, 'w', encoding='utf-8') as f:
                json.dump(b_state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    return sent_ok
```

**바꿀 문구**

```python
        merge_state(state_file, {'recent_urgent_alerts': recent_urgent[-20:]})   # [수정] 해당 키만 갱신

    return sent_ok
```

### [N10] 정의되지 않은 함수 호출 수정 (send_aggregated_channel_briefing)

- **위치**: 원본 3216~3217행
- **이유**: _get_bot_token(), _get_chat_id() 는 이 파일 어디에도 정의돼 있지 않아 token/chat_id 인자 없이 호출되면 NameError 가 납니다. 같은 파일에 있는 _get_default_credentials() 로 교체.

**찾을 문구** (이 블록 전체)

```python
    token = token or _get_bot_token()
    chat_id = chat_id or _get_chat_id()
```

**바꿀 문구**

```python
    _d_tok, _d_chat = _get_default_credentials()   # [수정] 미정의 _get_bot_token/_get_chat_id 대체
    token = token or _d_tok
    chat_id = chat_id or _d_chat
```

### [N11] 취합 브리핑: AI 서식 정리 + KST 시각

- **위치**: 원본 3305~3309행
- **이유**: 취합 브리핑도 AI 출력의 마크다운 별표·깨진 태그를 정리하고, 헤더 시각을 KST 로 표시합니다.

**찾을 문구** (이 블록 전체)

```python
    # 4. 수치 및 핵심 키워드 2차 자동 시각 강조 (HTML 마크업)
    summary_body = _highlight_market_keywords(summary_body)

    now_time_str = time.strftime('%m/%d %H:%M')
    final_msg = (
```

**바꿀 문구**

```python
    # 4. 수치 및 핵심 키워드 2차 자동 시각 강조 (HTML 마크업)
    summary_body = sanitize_ai_html(summary_body)          # [추가] **굵게**·깨진 태그 정리
    summary_body = _highlight_market_keywords(summary_body)

    now_time_str = kst_now_str()                           # [수정] UTC → KST
    final_msg = (
```

## 3. `telegram_bot_daemon.py` — 11건 (외부 채널 수집기)

파일 위에서 아래 순서(원본 줄 번호순)로 정렬했습니다. 줄 번호는 **수정 전 원본 기준**이며, 앞의 수정이 적용되면 밀리므로 줄 번호가 아니라 '찾을 문구'로 위치를 찾으세요.

### [D1] notifier_fixes 가져오기 (파일 상단 import)

- **위치**: 원본 30~31행
- **이유**: 새 함수들을 사용하기 위한 import. telegram_notifier import 바로 아래에 추가.

**찾을 문구** (이 블록 전체)

```python
from chart_image_generator import fetch_stock_chart_df, generate_stock_chart_image

```

**바꿀 문구**

```python
from chart_image_generator import fetch_stock_chart_df, generate_stock_chart_image
from notifier_fixes import (
    is_crypto_junk, is_duplicate_ko, stock_mentioned, lag_info,
    heartbeat_start, heartbeat_tick,
)

```

### [D2] 코인 필터 오탐 수정 (_clean_channel_text)

- **위치**: 원본 81~94행
- **이유**: notifier 의 N2 와 같은 문제(Ethernet/Solar 뉴스 삭제). 이 파일에도 복사본이 따로 있어 같이 수정해야 합니다.

**찾을 문구** (이 블록 전체)

```python
    # 5. 코인/가상자산/크립토/단순 선물 메모 100% 원천 차단 (국내/해외 주식 전용)
    crypto_junk = [
        '하이퍼리퀴드', 'hype', '비트코인', 'btc', '이더리움', 'eth', '솔라나', 'sol',
        '업비트', '빗썸', '바이낸스', '코인', '가상자산', '가상화폐', '에어드랍',
        '선물 일봉', '선물 숏', '선물 롱', '숏 포지션', '롱 포지션', '크립토',
        'nft', 'meme', '민팅', '지갑 주소'
    ]
    t_lower = t.lower()
    for cj in crypto_junk:
        if cj in t_lower:
            return ""

    t = t.strip()
    # 6. 정제 후 유효 글자 수가 35자 미만이면
```

**바꿀 문구**

```python
    # 5. 코인/가상자산/크립토/단순 선물 메모 100% 원천 차단 (국내/해외 주식 전용)
    #    [수정] 부분문자열 오탐(Ethernet, Solar 등) 방지 → notifier_fixes.is_crypto_junk 사용
    if is_crypto_junk(t):
        return ""

    t = t.strip()
    # 6. 정제 후 유효 글자 수가 35자 미만이면
```

### [D3] 중복 판정 강화 (_is_duplicate_content 맨 앞에 추가)

- **위치**: 원본 110~111행
- **이유**: 한글 재작성 기사까지 잡는 판정을 먼저 적용하고, 기존 판정 로직은 그대로 이어서 실행합니다(기존보다 느슨해지지 않음).

**찾을 문구** (이 블록 전체)

```python
    """새로운 텍스트가 기존 텍스트 목록과 핵심 내용이 중복(유사도 threshold 이상)되는지 정밀 판별."""
    norm_new = _normalize_text_for_dedup(new_text)
```

**바꿀 문구**

```python
    """새로운 텍스트가 기존 텍스트 목록과 핵심 내용이 중복(유사도 threshold 이상)되는지 정밀 판별."""
    if is_duplicate_ko(new_text, existing_texts):   # [추가] 한글 재작성 기사 중복 판정
        return True
    norm_new = _normalize_text_for_dedup(new_text)
```

### [D9] 스캐너 하트비트 (생존 진단 로그)

- **위치**: 원본 221~226행
- **이유**: 앱이 잠들었다 깨어나는지 증거를 남깁니다. 기동할 때 '직전 하트비트 N분 전'이 로그에 찍히므로, 공백이 길면 그 시간 동안 스캐너가 멈춰 있었다는 뜻입니다.

**찾을 문구** (이 블록 전체)

```python
    briefing_buffer = []
    buffer_first_added_ts = None

    while True:
        try:
            briefing_state = {}
```

**바꿀 문구**

```python
    briefing_buffer = []
    buffer_first_added_ts = None

    _hb_path = os.path.join(CURRENT_DIR, 'data', 'scanner_heartbeat.txt')   # [추가] 스캐너 생존 진단
    heartbeat_start(_hb_path)

    while True:
        heartbeat_tick(_hb_path)                                              # [추가]
        try:
            briefing_state = {}
```

### [D6] 원문 메타(시각·전달출처·링크) 추출 + 지연(stale) 판정

- **위치**: 원본 280~282행
- **이유**: 각 글의 원문 작성 시각·전달(forward) 출처·링크를 읽어 post_meta 로 만들고, 원문이 90분 넘게 지난 글(앱이 잠들었다 깨어난 뒤 밀린 글)인지 판정합니다.

**찾을 문구** (이 블록 전체)

```python
                        raw_text = text_el.get_text('\n').strip() if text_el else ''

                        # 1. 텍스트 정제 (링크, 공백, 줄바꿈, 인사말 제거)
```

**바꿀 문구**

```python
                        raw_text = text_el.get_text('\n').strip() if text_el else ''

                        # [추가] 원문 메타(원문 시각·전달 출처·링크)와 지연(stale) 판정
                        _t_el = m_item.find('time')
                        _fw_el = m_item.find(class_='tgme_widget_message_forwarded_from_name')
                        post_meta = {
                            'channel': p_id.split('/')[0],
                            'post_id': p_id.split('/')[-1],
                            'time_iso': (_t_el.get('datetime') if _t_el else '') or '',
                            'forwarded_from': _fw_el.get_text(strip=True) if _fw_el else '',
                            'urls': [a.get('href') for a in (text_el.find_all('a') if text_el else [])
                                     if (a.get('href') or '').startswith('http')],
                        }
                        _, _lag_min = lag_info(post_meta['time_iso'])
                        is_stale = (_lag_min is not None and _lag_min > 90)   # 90분 넘은 글은 '속보' 대신 취합 버퍼로

                        # 1. 텍스트 정제 (링크, 공백, 줄바꿈, 인사말 제거)
```

### [D4] 종목 매칭: 본문에 실제로 언급된 종목만 채택

- **위치**: 원본 289~291행
- **이유**: 해시태그만 달린 종목(예: 본문은 '테스트 부품' 얘기인데 #테스 태그만 붙은 경우)도 종목 알림으로 처리되던 문제. 태그를 제외한 본문에 종목명이 단어로 등장할 때만 매칭하고, 아니면 다음 태그를 확인합니다.

**찾을 문구** (이 블록 전체)

```python
                            hashtags = re.findall(r'#([가-힣a-zA-Z0-9]+)', raw_text)
                            for tag in hashtags:
                                row_tag = df_m_srch[df_m_srch['Name'].astype(str) == tag]
```

**바꿀 문구**

```python
                            hashtags = re.findall(r'#([가-힣a-zA-Z0-9]+)', raw_text)
                            body_wo_tags = re.sub(r'#\S+', '', raw_text)   # [추가] 태그를 뺀 본문
                            for tag in hashtags:
                                if not stock_mentioned(body_wo_tags, tag):  # [추가] 태그만 달린 종목은 제외
                                    continue
                                row_tag = df_m_srch[df_m_srch['Name'].astype(str) == tag]
```

### [D5] 가짜 퀀트점수·방어선 제거

- **위치**: 원본 301~305행
- **이유**: 'quant_score': 85.0 은 모든 종목에 똑같이 들어가는 고정값, 'support_price': s_cp * 0.97 은 지지선이 아니라 현재가의 97% 일 뿐입니다. 계산한 값이 아니므로 제거(다른 곳에서 사용하지 않음을 확인함).

**찾을 문구** (이 블록 전체)

```python
                                        'change_ratio': s_cr,
                                        'quant_score': 85.0,
                                        'jumping_status': '외부 채널 핵심 종목 포착 🟢',
                                        'support_price': s_cp * 0.97
                                    }
```

**바꿀 문구**

```python
                                        'change_ratio': s_cr,
                                        'jumping_status': '외부 채널 핵심 종목 포착 🟢'
                                        # [삭제] 'quant_score': 85.0 (고정값), 'support_price': s_cp * 0.97 (계산식 아님)
                                    }
```

### [D7] 오래된 글은 개별 속보에서 제외 (is_urgent 조건 추가)

- **위치**: 원본 336~338행
- **이유**: 90분 넘은 글은 개별 '속보' 카드로 보내지 않고 기존 취합 브리핑 버퍼로 보냅니다(밀린 글이 한꺼번에 개별 카드로 쏟아지는 것 방지).

**찾을 문구** (이 블록 전체)

```python
                            and len(clean_text) >= 40
                            and not channel_alert_sent  # 이번 배치에서 아직 발송 안 한 경우만
                        )
```

**바꿀 문구**

```python
                            and len(clean_text) >= 40
                            and not channel_alert_sent  # 이번 배치에서 아직 발송 안 한 경우만
                            and not is_stale            # [추가] 90분 넘은 글은 속보 대신 취합 버퍼로
                        )
```

### [D8] 알림 호출에 post_meta 전달

- **위치**: 원본 379~382행
- **이유**: D6 에서 만든 원문 메타를 notify_external_channel_alert(N3 에서 추가한 인자)에 넘깁니다.

**찾을 문구** (이 블록 전체)

```python
                                    matched_stock=matched_dict,
                                    token=token,
                                    chat_id=chat_id
                                )
```

**바꿀 문구**

```python
                                    matched_stock=matched_dict,
                                    token=token,
                                    chat_id=chat_id,
                                    post_meta=post_meta
                                )
```

### [D10] 삼켜지던 예외 로그화 (채널별)

- **위치**: 원본 413~414행
- **이유**: 채널 처리 중 오류가 `pass` 로 사라져 원인을 알 수 없었습니다. 로그로 남깁니다(동작은 동일하게 다음 채널로 진행).

**찾을 문구** (이 블록 전체)

```python
                except Exception as ch_err:
                    pass
```

**바꿀 문구**

```python
                except Exception as ch_err:
                    print(f"[scanner] {ch_name} 처리 오류: {ch_err!r}")   # [수정] 예외 삼킴 제거
```

### [D11] 삼켜지던 예외 로그화 (루프 전체)

- **위치**: 원본 487~490행
- **이유**: D10 과 같은 이유. 루프 전체의 예외도 로그로 남깁니다.

**찾을 문구** (이 블록 전체)

```python
        except Exception as scan_err:
            pass

        time.sleep(60) # 60초 주기 반복
```

**바꿀 문구**

```python
        except Exception as scan_err:
            print(f"[scanner] 루프 오류: {scan_err!r}")   # [수정] 예외 삼킴 제거

        time.sleep(60) # 60초 주기 반복
```

## 4. `app.py` — 1건 (스캐너 기동부)

파일 위에서 아래 순서(원본 줄 번호순)로 정렬했습니다. 줄 번호는 **수정 전 원본 기준**이며, 앞의 수정이 적용되면 밀리므로 줄 번호가 아니라 '찾을 문구'로 위치를 찾으세요.

### [A1] 스캐너 기동 함수: 실패 로그화 + 상시 데몬 분리 스위치

- **위치**: 원본 2499~2513행
- **이유**: ① import 실패 시 `pass` 로 스캐너가 아예 안 뜨는데도 흔적이 없던 문제를 로그로 남김 ② 환경변수/시크릿 STANDALONE_DAEMON=1 을 설정하면 텔레그램 리스너·외부채널 스캐너를 앱에서 띄우지 않습니다(별도 서버에서 상시 구동할 때 이중 폴링 방지용). 설정하지 않으면 기존 동작 그대로입니다.

**찾을 문구** (이 블록 전체)

```python
    t1 = threading.Thread(target=run_portfolio_background_scanner, daemon=True, name="PortfolioScannerDaemon")
    t1.start()
    
    t2 = threading.Thread(target=run_telegram_listener_daemon, args=(passed_token, passed_chat_id), daemon=True, name="TelegramListenerDaemon")
    t2.start()

    # 3. 외부 채널(엘리트강사/트레이딩스핀) 60초 주기 실시간 감시 스레드
    try:
        from telegram_bot_daemon import _run_external_channels_scanner
        t3 = threading.Thread(target=_run_external_channels_scanner, args=(passed_token, passed_chat_id), daemon=True, name="ExternalChannelsScannerDaemon")
        t3.start()
        return [t1, t2, t3]
    except Exception as _e3:
        pass

```

**바꿀 문구**

```python
    t1 = threading.Thread(target=run_portfolio_background_scanner, daemon=True, name="PortfolioScannerDaemon")
    t1.start()

    # [추가] 별도 상시 서버에서 daemon 을 돌릴 때: STANDALONE_DAEMON=1 이면 리스너/외부채널 스캐너는 앱에서 띄우지 않음
    if str(_get_secret("STANDALONE_DAEMON") or os.environ.get("STANDALONE_DAEMON", "")).strip() == "1":
        print("DEBUG: STANDALONE_DAEMON=1 → 텔레그램 리스너·외부채널 스캐너는 별도 상시 데몬이 담당")
        return [t1]

    t2 = threading.Thread(target=run_telegram_listener_daemon, args=(passed_token, passed_chat_id), daemon=True, name="TelegramListenerDaemon")
    t2.start()

    # 3. 외부 채널(엘리트강사/트레이딩스핀) 60초 주기 실시간 감시 스레드
    try:
        from telegram_bot_daemon import _run_external_channels_scanner
        t3 = threading.Thread(target=_run_external_channels_scanner, args=(passed_token, passed_chat_id), daemon=True, name="ExternalChannelsScannerDaemon")
        t3.start()
        return [t1, t2, t3]
    except Exception as _e3:
        print(f"DEBUG: 외부채널 스캐너 기동 실패: {_e3!r}")   # [수정] 예외 삼킴 제거

```

## 5. 적용 후 확인 (배포 후 로그·텔레그램에서)

1. **Streamlit Cloud → Manage app → Logs** 에서 `[scanner] 기동 … KST — 직전 하트비트 N분 전` 줄이 보여야 합니다. N 이 크거나 '이전 하트비트 없음'이면 그 시간 동안 스캐너가 멈춰 있었다는 증거입니다(앱 슬립/재시작).
2. 새 카드 헤더가 `원문 MM/DD HH:MM · N분 전` 형태여야 합니다. **`수집 HH:MM` 으로 나오면** 텔레그램 페이지에서 원문 시각을 읽지 못한 것이므로(아래 7번) 알려주세요.
3. 종목 박스에 `퀀트점수`·`방어선`이 사라지고 `종목 현황` + 현재가 뒤에 `(실시간)` 이 보여야 합니다.
4. 카드 하단에 `🔗 텔레그램 원문` / `📰 기사 원문` 버튼이 보여야 합니다.

## 6. 동작이 달라지는 점 (의도된 변경)

- 카드 헤더에서 `속보` 문구가 사라지고 `[채널 ← 전달 출처] 원문 시각 · 경과시간`으로 바뀝니다.
- 원문이 **90분 넘게 지난 글**은 개별 속보 카드 대신 기존 '취합 브리핑'으로 갑니다(앱이 잠들었다 깨어났을 때 밀린 글이 한꺼번에 개별 카드로 쏟아지는 것 방지).
- 해시태그만 달린 종목(본문에 종목명이 없는 경우)은 종목 알림으로 처리되지 않습니다.
- 중복 판정이 이전보다 엄격해집니다(한글 재작성 기사까지 차단). 정상 글이 걸러지는지 며칠 지켜봐 주세요.
- 퀀트점수·방어선은 **계산된 값이 없으면 표시하지 않습니다**(기존에는 모든 종목에 85점, 현재가×0.97이 표시됨).

## 7. 한계와 미검증 사항

- **모의 테스트만 했습니다.** 텔레그램/네이버/Gemini 호출은 가짜로 대체했고, 로직 흐름과 카드 모양만 검증했습니다.
- **`<time datetime>` 과 `forwarded_from_name` 셀렉터는 실제 t.me 페이지로 검증하지 못했습니다**(이 환경에서 t.me 접속 불가). 값이 비어 있으면 코드가 죽지는 않지만 헤더가 `수집 HH:MM` 으로 나오고 90분 지연 판정이 동작하지 않습니다.
- **임계값은 임의 값입니다**: 지연 90분(D6), 중복 판정 0.45(`notifier_fixes.py`).
- 실시간 가격(N6)의 등락률 부호는 기존 `fetch_realtime_stock_info` 동작을 그대로 신뢰합니다. 첫 카드에서 부호가 맞는지 확인하세요.
- 이 수정은 증상 완화입니다. 4~5시간 지연의 근본 원인은 스캐너가 Streamlit 앱 프로세스 안에서 돈다는 점(앱이 잠들면 멈춤)이며, `app.py` 의 A1 은 이를 분리할 때 쓰는 스위치(`STANDALONE_DAEMON=1`)만 추가합니다. 설정하지 않으면 기존과 동일하게 동작합니다.
- 하트비트 파일(`data/scanner_heartbeat.txt`)이 생기므로 Git 에 올리지 않으려면 `.gitignore` 에 추가하세요.
- 리포에 `telegram_notifier.py` 등이 `streamlit_app/` 폴더에도 따로 있다면, **실제로 앱이 import 하는 쪽**을 수정해야 합니다.
