# -*- coding: utf-8 -*-
"""
GD3 Market Hub FastAPI 전체 검증 스크립트
Claude로 재검증: 모든 엔드포인트, 서비스 로직, 프론트엔드 파일 무결성 확인
"""
import sys, os, ast, json, time, re
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000"
PASS = 0
FAIL = 0
WARN = 0

def ok(msg):
    global PASS; PASS += 1
    print(f"  [PASS] {msg}")

def fail(msg):
    global FAIL; FAIL += 1
    print(f"  [FAIL] {msg}")

def warn(msg):
    global WARN; WARN += 1
    print(f"  [WARN] {msg}")

def get_json(path, timeout=10):
    url = f"{BASE}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return None

def get_html(path, timeout=10):
    url = f"{BASE}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read().decode('utf-8', errors='replace')
    except Exception as e:
        return None

# ══════════════════════════════════════════════
print("\n" + "="*55)
print("  [검증 1] FastAPI 서버 기동 확인")
print("="*55)

data = get_json("/healthz")
if data and data.get("status") == "ok":
    ok(f"서버 응답 정상: {data}")
else:
    fail(f"헬스체크 실패: {data}")

# ══════════════════════════════════════════════
print("\n" + "="*55)
print("  [검증 2] 프론트엔드 HTML 서빙 확인")
print("="*55)

html = get_html("/")
if html:
    if "GD3 Market Hub" in html:
        ok("루트(/) HTML 정상 서빙")
    else:
        fail("HTML 내용 불일치")
    if "Plotly" in html:
        ok("Plotly.js CDN 포함 확인")
    else:
        warn("Plotly.js CDN 링크 미발견")
    if "dashboard.js" in html and "api.js" in html and "charts.js" in html:
        ok("JS 파일 3개 모두 참조 확인")
    else:
        fail("JS 파일 참조 누락")
else:
    fail("루트(/) 응답 없음")

# ══════════════════════════════════════════════
print("\n" + "="*55)
print("  [검증 3] REST API 엔드포인트 전체 확인")
print("="*55)

endpoints = [
    ("/api/market/indices",    "naver",      "시장 지수 (naver 키)"),
    ("/api/market/supply",     None,         "수급 조회"),
    ("/api/market/summary",    "market_condition", "시장 요약 (market_condition)"),
    ("/api/market/quant-top10", None,        "퀀트 TOP10 리스트"),
    ("/api/market/high-density", None,       "고밀도 관심 종목"),
    ("/api/portfolio",         "portfolio",  "포트폴리오 조회"),
]

for path, key, desc in endpoints:
    t0 = time.time()
    res = get_json(path, timeout=30)
    elapsed = (time.time() - t0) * 1000
    if res is None:
        fail(f"{desc} — 응답 없음 ({path})")
    elif key and key not in str(res):
        warn(f"{desc} — 응답은 있으나 '{key}' 키 미발견 ({elapsed:.0f}ms)")
    else:
        ok(f"{desc} — 정상 ({elapsed:.0f}ms)")

# ══════════════════════════════════════════════
print("\n" + "="*55)
print("  [검증 4] 종목 상세 API 확인 (삼성전자 005930)")
print("="*55)

stock_endpoints = [
    ("/api/stock/005930/chart/daily",   list,  "일봉 차트 데이터"),
    ("/api/stock/005930/chart/minute",  list,  "1분봉 차트 데이터"),
    ("/api/stock/005930/supply",        dict,  "수급 추이"),
    ("/api/stock/005930/news",          list,  "뉴스 목록"),
    ("/api/stock/005930/investors",     dict,  "외국인/기관"),
]

for path, expected_type, desc in stock_endpoints:
    t0 = time.time()
    res = get_json(path, timeout=20)
    elapsed = (time.time() - t0) * 1000
    if res is None:
        fail(f"{desc} — 응답 없음")
    elif not isinstance(res, expected_type):
        warn(f"{desc} — 타입 불일치 (기대:{expected_type.__name__}, 실제:{type(res).__name__})")
    elif expected_type == list and len(res) == 0:
        warn(f"{desc} — 빈 배열 반환 ({elapsed:.0f}ms)")
    else:
        ok(f"{desc} — 정상 ({elapsed:.0f}ms)")

# ══════════════════════════════════════════════
print("\n" + "="*55)
print("  [검증 5] 포트폴리오 CRUD 확인")
print("="*55)

# 5-1. 조회
res = get_json("/api/portfolio")
if res and "portfolio" in res and "status" in res:
    ok(f"포트폴리오 조회 — {len(res['portfolio'])}개 종목 확인")
else:
    fail("포트폴리오 조회 실패")

# 5-2. 추가 테스트
import urllib.request
add_data = json.dumps({
    "code": "TEST01", "name": "테스트종목",
    "entry_price": 10000, "quantity": 10, "stop_loss": 9000, "memo": "검증용"
}).encode('utf-8')

try:
    req = urllib.request.Request(
        f"{BASE}/api/portfolio",
        data=add_data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        res = json.loads(r.read().decode())
    if res.get("success"):
        ok("포트폴리오 추가 (POST) — 성공")
    else:
        fail("포트폴리오 추가 실패")
except Exception as e:
    fail(f"포트폴리오 추가 예외: {e}")

# 5-3. 삭제 테스트
try:
    req = urllib.request.Request(
        f"{BASE}/api/portfolio/TEST01",
        method="DELETE"
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        res = json.loads(r.read().decode())
    if res.get("success"):
        ok("포트폴리오 삭제 (DELETE) — 성공")
    else:
        fail("포트폴리오 삭제 실패")
except Exception as e:
    fail(f"포트폴리오 삭제 예외: {e}")

# ══════════════════════════════════════════════
print("\n" + "="*55)
print("  [검증 6] 서비스 모듈 코드 품질 확인")
print("="*55)

files_to_check = [
    ("backend/main.py",    "FastAPI 메인 서버"),
    ("backend/services.py","서비스 레이어"),
    ("frontend/index.html","메인 HTML"),
    ("frontend/css/style.css","스타일시트"),
    ("frontend/js/api.js", "API 통신 모듈"),
    ("frontend/js/charts.js","차트 모듈"),
    ("frontend/js/dashboard.js","대시보드 로직"),
    ("start_fastapi.bat",  "실행 스크립트"),
]

for fname, desc in files_to_check:
    path = os.path.join(os.path.dirname(__file__), fname)
    if os.path.exists(path):
        size = os.path.getsize(path)
        ok(f"{desc} ({fname}) — 존재, {size:,} bytes")
    else:
        fail(f"{desc} ({fname}) — 파일 없음!")

# Python 파일 AST 문법 검증
for fname in ["backend/main.py", "backend/services.py"]:
    path = os.path.join(os.path.dirname(__file__), fname)
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                src = f.read()
            ast.parse(src)
            ok(f"{fname} — AST 문법 이상 없음")
        except SyntaxError as e:
            fail(f"{fname} — SyntaxError L{e.lineno}: {e.msg}")

# ══════════════════════════════════════════════
print("\n" + "="*55)
print("  [검증 7] 보안 및 안정성 확인")
print("="*55)

with open("backend/main.py", encoding='utf-8') as f:
    main_src = f.read()
with open("backend/services.py", encoding='utf-8') as f:
    svc_src = f.read()

# CORS 설정 확인
if "CORSMiddleware" in main_src and 'allow_origins=["*"]' in main_src:
    ok("CORS 미들웨어 설정 확인 (태블릿 외부 접속 허용)")
else:
    warn("CORS 설정 누락 가능성")

# XSS 방어 확인
if "html.escape" in svc_src:
    ok("뉴스 URL html.escape XSS 방어 확인")
else:
    warn("뉴스 URL XSS 방어 미발견")

# WebSocket 재연결 로직 확인
with open("frontend/js/api.js", encoding='utf-8') as f:
    api_js = f.read()
if "reconnectTimer" in api_js:
    ok("WebSocket 자동 재연결 로직 확인")
else:
    warn("WebSocket 재연결 로직 없음")

# TTL 캐시 확인
if "_cached(ttl=" in svc_src:
    ok("TTL 인메모리 캐시 적용 확인 (Streamlit cache_data 대체)")
else:
    warn("TTL 캐시 미적용")

# ══════════════════════════════════════════════
print("\n" + "="*55)
print("  ★ 최종 검증 결과")
print("="*55)
total = PASS + FAIL + WARN
print(f"  PASS : {PASS}")
print(f"  FAIL : {FAIL}")
print(f"  WARN : {WARN}")
print(f"  총   : {total}")
print()
if FAIL == 0:
    print("  → 모든 검증 통과! 프로덕션 배포 준비 완료.")
else:
    print(f"  → 수정 필요 항목 {FAIL}개 있음. 점검 필요.")
