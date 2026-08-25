# -*- coding: utf-8 -*-
"""
GD3 Market Hub app.py 미완료 버그 일괄 수정 스크립트
수정 항목:
  1. daily_chg UnboundLocalError (else 분기에 daily_chg = 0.0 추가)
  2. JS setTimeout 이중 실행 제거 (st_autorefresh로 일원화)
  3. _clean_sup / _format_sup 전역 이동 (루프 내 중첩 정의 제거)
  4. ETF 필터 apply(lambda) -> str.contains(regex) 벡터화
  5. fetch_stock_realtime_investors ThreadPoolExecutor 병렬화
"""

import re

with open('app.py', encoding='utf-8') as f:
    src = f.read()

original = src
changes = []

# ─────────────────────────────────────────────────────────────
# [수정 1] daily_chg UnboundLocalError
# else 분기에 daily_chg = 0.0 누락 → 추가
# ─────────────────────────────────────────────────────────────
OLD1 = """        else:
            last_close = df_candle['Close'].iloc[-1]
            chg_str = ''
            chg_color = '#cccccc'"""

NEW1 = """        else:
            last_close = df_candle['Close'].iloc[-1]
            daily_chg = 0.0  # 데이터 1개뿐일 때 미정의 방지 (UnboundLocalError 예방)
            chg_str = ''
            chg_color = '#cccccc'"""

if OLD1 in src:
    src = src.replace(OLD1, NEW1, 1)
    changes.append('✅ [1] daily_chg = 0.0 else 분기 추가')
else:
    changes.append('⚠️  [1] daily_chg 패턴 미발견 - 이미 수정됐거나 코드 변경됨')

# ─────────────────────────────────────────────────────────────
# [수정 2] JS setTimeout 이중 실행 제거
# st_autorefresh가 이미 처리하므로 JS 60초 타이머 제거
# ─────────────────────────────────────────────────────────────
OLD2 = """        // 1. 60초 자동 새로고침 (5초 스캘핑 모드 활성화 시 2중 새로고침 충돌 방지)
        var isAutoRefresh5s = {\"true\" if st.session_state.get('auto_refresh_enabled', False) else \"false\"};
        if (!isAutoRefresh5s) {
            setTimeout(function() {
                try {
                    parentWin.postMessage({type: 'streamlit:rerun'}, '*');
                } catch(e) {}
            }, 60000);
        }"""

NEW2 = """        // 1. 자동 새로고침은 Python st_autorefresh에서 일괄 관리 (이중 실행 방지)"""

if OLD2 in src:
    src = src.replace(OLD2, NEW2, 1)
    changes.append('✅ [2] JS setTimeout 60초 타이머 제거 완료')
else:
    changes.append('⚠️  [2] setTimeout 패턴 미발견 - 이미 수정됐거나 코드 변경됨')

# ─────────────────────────────────────────────────────────────
# [수정 3] _format_sup / _clean_sup 루프 내 중첩 정의 → 전역 이동
# 현재 위치: df_summary 처리 루프 바로 위 (들여쓰기 내부)
# 전역 이동 후 해당 위치 제거
# ─────────────────────────────────────────────────────────────
OLD3 = """                # ── 수급 값 포매팅 헬퍼 함수 (루프 외부에 1회만 정의) ──
                def _format_sup(val_str):
                    \"\"\"네이버 수급 문자열을 '+1,234' 형태로 정규화\"\"\"
                    v = str(val_str).strip().replace(',', '')
                    try:
                        f_val = float(v)
                        return f\"{f_val:+.0f}\" if f_val != 0 else \"0\"
                    except Exception:
                        return val_str

                def _clean_sup(val_str):
                    \"\"\"네이버 수급 문자열을 정수(억원)로 변환\"\"\"
                    try:
                        return int(str(val_str).replace(',', '').replace('+', '').strip())
                    except Exception:
                        return 0"""

NEW3 = """                # _format_sup / _clean_sup → 모듈 전역 함수로 이동됨 (중복 정의 제거)"""

if OLD3 in src:
    src = src.replace(OLD3, NEW3, 1)
    changes.append('✅ [3-a] 루프 내 _format_sup/_clean_sup 중첩 정의 제거')
else:
    changes.append('⚠️  [3-a] _format_sup/_clean_sup 루프 내 패턴 미발견')

# 전역 함수가 없으면 import 섹션 아래에 추가
GLOBAL_FUNCS = """
def _format_sup(val_str):
    \"\"\"네이버 수급 문자열을 '+1,234' 형태로 정규화\"\"\"
    v = str(val_str).strip().replace(',', '')
    try:
        f_val = float(v)
        return f\"{f_val:+.0f}\" if f_val != 0 else \"0\"
    except Exception:
        return val_str

def _clean_sup(val_str):
    \"\"\"네이버 수급 문자열을 정수(억원)로 변환\"\"\"
    try:
        return int(str(val_str).replace(',', '').replace('+', '').strip())
    except Exception:
        return 0

"""

# 이미 전역에 존재하는지 확인 (def _format_sup 가 모듈 레벨에 있는지)
lines = src.splitlines()
global_format_sup = False
for i, line in enumerate(lines):
    if 'def _format_sup' in line and not line.startswith(' ') and not line.startswith('\t'):
        global_format_sup = True
        break

if not global_format_sup:
    # GITHUB_RAW_BASE 정의 바로 위에 삽입
    INSERT_AFTER = "from concurrent.futures import ThreadPoolExecutor, as_completed"
    if INSERT_AFTER in src:
        src = src.replace(INSERT_AFTER, INSERT_AFTER + '\n' + GLOBAL_FUNCS, 1)
        changes.append('✅ [3-b] _format_sup/_clean_sup 전역 함수 추가')
    else:
        changes.append('⚠️  [3-b] 삽입 위치 미발견')
else:
    changes.append('✅ [3-b] _format_sup/_clean_sup 이미 전역에 존재')

# ─────────────────────────────────────────────────────────────
# [수정 4] ETF 필터 apply(lambda) → str.contains(regex) 벡터화
# ─────────────────────────────────────────────────────────────
OLD4 = """    is_fund = name_lower.apply(lambda x: any(kw in x for kw in EXCLUDE_KEYWORDS))
    if 'Sector' in df_out.columns:
        sector_lower = df_out['Sector'].fillna('').astype(str).str.lower()
        is_fund = is_fund | sector_lower.apply(lambda x: 'etf' in x or '수익증권' in x)"""

NEW4 = """    # [성능 최적화] apply(lambda+any) → str.contains 정규식 벡터 연산으로 교체 (수십 배 빠름)
    _etf_pattern = '|'.join(re.escape(kw) for kw in EXCLUDE_KEYWORDS)
    is_fund = name_lower.str.contains(_etf_pattern, regex=True, na=False)
    if 'Sector' in df_out.columns:
        sector_lower = df_out['Sector'].fillna('').astype(str).str.lower()
        is_fund = is_fund | sector_lower.str.contains(r'etf|수익증권', regex=True, na=False)"""

if OLD4 in src:
    src = src.replace(OLD4, NEW4, 1)
    changes.append('✅ [4] ETF 필터 벡터화 완료')
else:
    changes.append('⚠️  [4] ETF 필터 패턴 미발견 - 이미 수정됐거나 코드 변경됨')

# ─────────────────────────────────────────────────────────────
# [수정 5] fetch_stock_realtime_investors 직렬 → 병렬 처리
# ─────────────────────────────────────────────────────────────
OLD5 = """def fetch_stock_realtime_investors(code_list):
    \"\"\"네이버 금융 API로 개별 종목의 실시간 외국인/기관 수급(가집계) 조회\"\"\"
    res = {}
    headers = {\"User-Agent\": \"Mozilla/5.0\"}
    for code in code_list:
        try:
            # trend API를 활용하여 당일 최근 수급(실시간 가집계 포함) 획득
            url = f\"https://m.stock.naver.com/api/stock/{code}/trend?pageSize=1\"
            r = requests.get(url, headers=headers, timeout=1.5)
            if r.status_code == 200:
                data = r.json()
                if data and len(data) > 0:
                    item = data[0]
                    fgn = str(item.get(\"foreignerPureBuyQuant\", \"0\")).replace(',', '').replace('+', '')
                    org = str(item.get(\"organPureBuyQuant\", \"0\")).replace(',', '').replace('+', '')
                    res[code] = {
                        \"foreign\": int(fgn) if fgn.replace('-', '').isdigit() else 0,
                        \"institutional\": int(org) if org.replace('-', '').isdigit() else 0
                    }
        except Exception as e:
            print(f\"DEBUG: fetch_stock_realtime_investors {code} failed: {e}\")
    return res"""

NEW5 = """def fetch_stock_realtime_investors(code_list):
    \"\"\"네이버 금융 API로 개별 종목의 실시간 외국인/기관 수급(가집계) 조회 (병렬 처리)\"\"\"\
    res = {}
    if not code_list:
        return res
    headers = {\"User-Agent\": \"Mozilla/5.0\"}

    def _fetch_one(code):
        try:
            url = f\"https://m.stock.naver.com/api/stock/{code}/trend?pageSize=1\"
            r = requests.get(url, headers=headers, timeout=1.5)
            if r.status_code == 200:
                data = r.json()
                if data and len(data) > 0:
                    item = data[0]
                    fgn = str(item.get(\"foreignerPureBuyQuant\", \"0\")).replace(',', '').replace('+', '')
                    org = str(item.get(\"organPureBuyQuant\", \"0\")).replace(',', '').replace('+', '')
                    return code, {
                        \"foreign\": int(fgn) if fgn.replace('-', '').isdigit() else 0,
                        \"institutional\": int(org) if org.replace('-', '').isdigit() else 0
                    }
        except Exception as e:
            print(f\"DEBUG: fetch_stock_realtime_investors {code} failed: {e}\")
        return code, None

    # [성능 최적화] 직렬 for loop → ThreadPoolExecutor 병렬 처리 (최대 8개 동시)
    with ThreadPoolExecutor(max_workers=min(len(code_list), 8)) as executor:
        for code, data in executor.map(_fetch_one, code_list):
            if data is not None:
                res[code] = data
    return res"""

if OLD5 in src:
    src = src.replace(OLD5, NEW5, 1)
    changes.append('✅ [5] fetch_stock_realtime_investors 병렬화 완료')
else:
    changes.append('⚠️  [5] investors 함수 패턴 미발견 - 이미 수정됐거나 코드 변경됨')

# ─────────────────────────────────────────────────────────────
# 결과 출력
# ─────────────────────────────────────────────────────────────
print('\n'.join(changes))
print(f'\n총 변경 문자 수: {abs(len(src) - len(original))}')

# AST 파싱 검증
import ast
try:
    ast.parse(src)
    print('✅ AST PARSE SUCCESS')
except SyntaxError as e:
    print(f'❌ SyntaxError: {e}')
    exit(1)

with open('app.py', 'w', encoding='utf-8', newline='') as f:
    f.write(src)
print('✅ app.py 저장 완료')
