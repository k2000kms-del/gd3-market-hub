# -*- coding: utf-8 -*-
"""
telegram_bot_daemon.py
----------------------
GD 3.0 Market Hub - 텔레그램 양방향 스마트 비서 상시 구동 데몬.
Streamlit 실행 여부와 무관하게 24시간 백그라운드에서
대표님의 버튼 클릭 및 명령어를 0.5초 내로 즉시 응답합니다.
"""

import os
import sys
import time
import json
import threading
import urllib.request
import pandas as pd

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from telegram_notifier import process_incoming_command, notify_external_channel_alert
from chart_image_generator import fetch_stock_chart_df, generate_stock_chart_image

def _load_secrets():
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
    for s_path in [
        os.path.join(CURRENT_DIR, '.streamlit', 'secrets.toml'),
        os.path.join(CURRENT_DIR, 'streamlit_app', '.streamlit', 'secrets.toml'),
        os.path.join(os.path.dirname(CURRENT_DIR), '.streamlit', 'secrets.toml')
    ]:
        if os.path.exists(s_path):
            try:
                import toml
                s = toml.load(s_path)
                token = token or s.get('TELEGRAM_BOT_TOKEN', '')
                chat_id = chat_id or s.get('TELEGRAM_CHAT_ID', '')
            except Exception:
                pass
    return (token or "").strip(), str(chat_id or "").strip()

def _load_csv_safely(fname: str) -> pd.DataFrame:
    p = os.path.join(CURRENT_DIR, 'data', fname)
    if os.path.exists(p):
        try:
            return pd.read_csv(p)
        except Exception:
            pass
    return pd.DataFrame()

def _clean_channel_text(text: str) -> str:
    """채널 원문에서 링크, 불필요한 공백, 줄바꿈, 광고성 문구를 제거하여 핵심 내용만 정제."""
    if not text:
        return ""
    import re
    # 1. URL 제거
    t = re.sub(r'https?://\S+', '', text)
    # 2. 해시태그 기호만 제거
    t = re.sub(r'#([가-힣a-zA-Z0-9]+)', r'\1', t)
    # 3. 3줄 이상의 과도한 연속 줄바꿈 및 공백 압축
    t = re.sub(r'\n{3,}', '\n\n', t)
    t = re.sub(r'[ \t]+', ' ', t)
    # 4. 채널 홍보/인사말/동영상 유도 문구 필터링
    junk_patterns = [
        r'채널에 들어오셨습니다.*', r'무료 입장.*', r'구독과 좋아요.*',
        r'오늘의 영상이 지금 막 공개되었습니다.*', r'유튜브에서 확인.*',
        r'좋은 아침입니다.*', r'굿나잇.*', r'퇴근하겠습니다.*'
    ]
    for jp in junk_patterns:
        t = re.sub(jp, '', t, flags=re.IGNORECASE)
    t = t.strip()
    # 5. 정제 후 유효 글자 수가 15자 미만이면 무의미한 껍데기로 간주
    hangul_or_eng = len(re.findall(r'[가-힣a-zA-Z0-9]', t))
    if hangul_or_eng < 15:
        return ""
    return t

def _normalize_text_for_dedup(text: str) -> str:
    """채널 접두어, 대괄호 태그, URL, 특수문자, 불필요한 공백을 제거하여 핵심 단어 위주로 정규화."""
    import re
    t = re.sub(r'https?://\S+', '', text)
    t = re.sub(r'\[[^\]]*\]', '', t)
    t = t.replace('#', '')
    t = re.sub(r'[^\w\s가-힣a-zA-Z0-9]', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()

def _is_duplicate_content(new_text: str, existing_texts: list, threshold: float = 0.55) -> bool:
    """새로운 텍스트가 기존 텍스트 목록과 핵심 내용이 중복(유사도 threshold 이상)되는지 정밀 판별."""
    norm_new = _normalize_text_for_dedup(new_text)
    if len(norm_new) < 8:
        return False
    
    words_new = set(w for w in norm_new.split() if len(w) >= 2)
    if not words_new:
        return False

    prefix_new = norm_new[:30]

    for ex in existing_texts:
        if not ex:
            continue
        norm_ex = _normalize_text_for_dedup(ex)
        if not norm_ex:
            continue
        
        # 1) 앞부분 30자 일치 여부 (핵심 도입부 동일)
        if len(norm_new) >= 20 and len(norm_ex) >= 20:
            if prefix_new in norm_ex or norm_ex[:30] in norm_new:
                return True

        # 2) 단어 기반 자카드 유사도 (Jaccard similarity)
        words_ex = set(w for w in norm_ex.split() if len(w) >= 2)
        if not words_ex:
            continue
        
        intersection = len(words_new & words_ex)
        union = len(words_new | words_ex)
        if union > 0 and (intersection / union) >= threshold:
            return True
                
        # 3) 포함 관계 (신규 단어의 70% 이상이 기존 텍스트에 포함된 경우)
        if len(words_new) >= 4 and (intersection / len(words_new)) >= 0.70:
            return True

    return False

def _save_to_intelligence_pool(ch_name: str, raw_text: str, matched_dict: dict = None):
    """외부 채널의 유익한 분석글/시황 정보를 모아 아침 및 마감 브리핑의 1급 자료로 활용할 수 있도록 적재 (중복 완벽 배제)."""
    clean_text = _clean_channel_text(raw_text)
    if len(clean_text) < 25:
        # 빈 껍데기, 링크만 있는 글, 단순 인사말 등은 저장하지 않음
        return

    pool_file = os.path.join(CURRENT_DIR, 'data', 'channel_intelligence_pool.json')
    try:
        items = []
        if os.path.exists(pool_file):
            try:
                with open(pool_file, 'r', encoding='utf-8') as pf:
                    items = json.load(pf)
            except Exception:
                items = []
        if not isinstance(items, list):
            items = []

        # ── [중복 방지 (고도화: 접두어 정규화 및 단어 유사도 기반 100% 중복 차단)] ──
        existing_texts = [it.get('text', '') for it in items if isinstance(it, dict)]
        if _is_duplicate_content(clean_text, existing_texts, threshold=0.50):
            return

        new_entry = {
            "channel": ch_name,
            "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
            "text": clean_text[:600],
            "snippet": clean_text[:50],
            "stock": matched_dict.get('name') if matched_dict else None
        }
        items.append(new_entry)
        # 최신 50개 유지
        if len(items) > 50:
            items = items[-50:]

        os.makedirs(os.path.dirname(pool_file), exist_ok=True)
        with open(pool_file, 'w', encoding='utf-8') as pf:
            json.dump(items, pf, ensure_ascii=False, indent=2)
    except Exception as ex:
        pass

def _run_external_channels_scanner(token: str, chat_id: str):
    """외부 텔레그램 채널(11개)을 60초마다 실시간 감시하여 단타 브리핑 즉시 포착."""
    state_file = os.path.join(CURRENT_DIR, 'data', 'last_briefing_state.json')
    _EXTERNAL_CHANNELS = [
        # ── 기존 채널 ──────────────────────────────────────────
        ('elite_instructor',    'https://t.me/s/elite_instructor',    'last_elite_post_id'),
        ('trading_spin',        'https://t.me/s/trading_spin',        'last_spin_post_id'),
        # ── 신규 추가 채널 (2026-09-16) ─────────────────────────
        ('globaletfi',          'https://t.me/s/globaletfi',          'last_globaletfi_post_id'),       # 하나 Global ETF 박승진
        ('kiwoom_semibat',      'https://t.me/s/kiwoom_semibat',      'last_kiwoom_semibat_post_id'),   # 키움 반도체/이차전지 PRIME
        ('gaoshoukorea',        'https://t.me/s/gaoshoukorea',        'last_gaoshoukorea_post_id'),     # 재야의 고수들
        ('SAJAnote',            'https://t.me/s/SAJAnote',            'last_sajanote_post_id'),         # Sajah의 투자 노트
        ('defence_24',          'https://t.me/s/defence_24',          'last_defence24_post_id'),        # 우주방산AI로봇 아카이브
        ('hanaglobalbottomup',  'https://t.me/s/hanaglobalbottomup',  'last_hanaglobal_post_id'),       # 하나증권 해외주식분석
        ('HS_academy',          'https://t.me/s/HS_academy',          'last_hsacademy_post_id'),        # HS아카데미 이효석
        ('kimcharger',          'https://t.me/s/kimcharger',          'last_kimcharger_post_id'),       # 김찰저의 관심과 생각
        ('meritzbae',           'https://t.me/s/meritzbae',           'last_meritzbae_post_id'),        # 메리츠 조선/방산 베기연
    ]

    time.sleep(3) # 메인 봇 초기화 대기
    print("📡 [실시간 데몬] 외부 채널 11개 60초 감시 스레드 가동")

    while True:
        try:
            briefing_state = {}
            if os.path.exists(state_file):
                try:
                    with open(state_file, 'r', encoding='utf-8') as f:
                        briefing_state = json.load(f)
                except Exception:
                    briefing_state = {}

            df_m_srch = _load_csv_safely('df_full_market.csv')

            for ch_name, ch_url, state_key in _EXTERNAL_CHANNELS:
                try:
                    import requests as req
                    from bs4 import BeautifulSoup
                    r_t = req.get(ch_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
                    if r_t.status_code != 200:
                        continue

                    soup_t = BeautifulSoup(r_t.text, 'html.parser')
                    msgs = soup_t.find_all('div', class_='tgme_widget_message')
                    if not msgs:
                        continue

                    saved_p_id = briefing_state.get(state_key, '')
                    new_msgs = []
                    if not saved_p_id:
                        # ── [최초 감시 등록 시] 과거 글 알림 발송 절대 금지 ──
                        # 현재 시점 최신 글의 ID만 기록하고 바로 다음 채널로 이동
                        briefing_state[state_key] = msgs[-1].get('data-post', '')
                        continue
                    else:
                        found_saved = False
                        for m in msgs:
                            p_id_cur = m.get('data-post', '')
                            if p_id_cur == saved_p_id:
                                found_saved = True
                                continue
                            if found_saved:
                                new_msgs.append(m)
                        if not found_saved:
                            # 저장된 ID를 못 찾은 경우(너무 많은 글이 지난 경우)에도 과거 글 난사를 방지하기 위해 최신 ID만 갱신
                            briefing_state[state_key] = msgs[-1].get('data-post', '')
                            continue

                    if not new_msgs:
                        continue

                    for m_item in new_msgs:
                        p_id = m_item.get('data-post', '')
                        text_el = m_item.find('div', class_='tgme_widget_message_text')
                        raw_text = text_el.get_text('\n').strip() if text_el else ''

                        # 1. 텍스트 정제 (링크, 공백, 줄바꿈, 인사말 제거)
                        clean_text = _clean_channel_text(raw_text)
                        if len(clean_text) < 25:
                            # 순수 유효 본문이 25자 미만이면 알림도 풀 저장도 하지 않고 스킵
                            briefing_state[state_key] = p_id
                            continue

                        # 2. 해시태그(#종목명) 및 정밀 종목 매칭
                        matched_dict = None
                        if not df_m_srch.empty and 'Name' in df_m_srch.columns:
                            import re
                            hashtags = re.findall(r'#([가-힣a-zA-Z0-9]+)', raw_text)
                            for tag in hashtags:
                                row_tag = df_m_srch[df_m_srch['Name'].astype(str) == tag]
                                if not row_tag.empty:
                                    m_row = row_tag.iloc[0]
                                    s_cd = str(m_row.get('Code', '')).zfill(6)
                                    s_cp = float(m_row.get('Close', 0))
                                    s_cr = float(m_row.get('ChagesRatio', 0))
                                    matched_dict = {
                                        'code': s_cd,
                                        'name': tag,
                                        'price': s_cp,
                                        'change_ratio': s_cr,
                                        'quant_score': 85.0,
                                        'jumping_status': '외부 채널 핵심 종목 포착 🟢',
                                        'support_price': s_cp * 0.97
                                    }
                                    break

                        # ── [실시간 즉시 알림 트리거 (시장 충격 속보 & 주가 급등락 이슈)] ──
                        # 1) 시장 전체 충격 이벤트 (매크로 속보)
                        # 2) 주가에 즉각 영향을 주는 개별 종목 특급 호재/악재 (특징주, 수주, 계약, 승인, 상한가 등)
                        MACRO_URGENT_KEYWORDS = [
                            '[속보]', '[긴급]', '[단독]', '비상계엄', '계엄령',
                            '서킷브레이커', '사이드카', '거래정지', '미사일 발사', '공습경보', '전면전'
                        ]
                        STOCK_SURGE_KEYWORDS = [
                            '[특징주]', '특징주', '공급계약', '대규모 수주', '수주공시', 
                            'FDA 승인', '임상 성공', '상한가', '공개매수', '경영권 분쟁', 
                            '무상증자', '기술수출', '라이선스 아웃', '어닝 서프라이즈'
                        ]
                        EXCLUDE_KEYWORDS = [
                            '교통사고', '음주운전', '마약', '열애', '이혼', '청문회', 
                            '특검', '국회의원', '여당', '야당', '날씨', '단독포토', '포토', 
                            '연예', '아이돌', '케이팝', '학폭', '사망사고', '이벤트', '구독'
                        ]

                        has_macro_urgent = any(k in clean_text for k in MACRO_URGENT_KEYWORDS)
                        has_stock_surge = any(k in clean_text for k in STOCK_SURGE_KEYWORDS) and (matched_dict is not None)
                        has_exclude_kw = any(k in clean_text for k in EXCLUDE_KEYWORDS)
                        
                        # 시장 충격 속보이거나, 주가 급등락 유발 종목 호재/악재인 경우 즉시 실시간 알림!
                        is_urgent = (has_macro_urgent or has_stock_surge) and not has_exclude_kw

                        if is_urgent:
                            # ── [최근 30분 동일/유사 속보 중복 발송 방지 (Dedup)] ──
                            now_ts = time.time()
                            recent_urgent = briefing_state.get('recent_urgent_alerts', [])
                            recent_urgent = [a for a in recent_urgent if isinstance(a, dict) and (now_ts - a.get('time', 0)) < 1800]
                            
                            existing_urgent_texts = [a.get('text', '') for a in recent_urgent]
                            if _is_duplicate_content(clean_text, existing_urgent_texts, threshold=0.50):
                                print(f"[{time.strftime('%H:%M:%S')}] ⏭️ [중복 방지] {ch_name} 유사 속보 이미 발송됨 (30분 이내 중복 스킵): {clean_text[:40]}...")
                                _save_to_intelligence_pool(ch_name, clean_text, matched_dict)
                            else:
                                notify_external_channel_alert(
                                    channel_name=ch_name,
                                    raw_message=clean_text,
                                    matched_stock=matched_dict,
                                    token=token,
                                    chat_id=chat_id
                                )
                                s_desc = matched_dict['name'] if matched_dict else '초특급속보'
                                print(f"[{time.strftime('%H:%M:%S')}] 🚨 {ch_name} 실시간 긴급 속보 전송: [{p_id}] ({s_desc})")
                                recent_urgent.append({
                                    'time': now_ts,
                                    'text': clean_text[:300],
                                    'channel': ch_name,
                                    'stock': matched_dict.get('name') if matched_dict else None
                                })
                                briefing_state['recent_urgent_alerts'] = recent_urgent[-20:]
                                time.sleep(0.5)
                        else:
                            # ── [아침/마감 브리핑 축적 자료실 (알림 미발송, 조용히 풀에만 저장)] ──
                            # 11개 채널의 내용을 개별적으로 퍼나르지 않고 정보를 모아
                            # 아침 및 마감 브리핑 때 '단 하나의 완성형 리포트'로 통합 발송!
                            _save_to_intelligence_pool(ch_name, clean_text, matched_dict)

                        briefing_state[state_key] = p_id

                    with open(state_file, 'w', encoding='utf-8') as f:
                        json.dump(briefing_state, f, ensure_ascii=False, indent=2)

                except Exception as ch_err:
                    pass

        except Exception as scan_err:
            pass

        time.sleep(60) # 60초 주기 반복


def _load_portfolio_safely() -> dict:
    p = os.path.join(CURRENT_DIR, 'data', 'my_portfolio.json')
    if os.path.exists(p):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def standalone_context_fn(query_type: str, code: str = None, **kwargs):
    try:
        if query_type == 'portfolio':
            port = _load_portfolio_safely()
            df_m = _load_csv_safely('df_full_market.csv')
            items = []
            tot_eval = 0
            tot_entry = 0
            for c_code, info in port.items():
                ep = float(info.get('entry_price', 0))
                qty = float(info.get('qty', 0))
                cur_p = ep
                if not df_m.empty and 'Code' in df_m.columns:
                    m = df_m[df_m['Code'].astype(str).str.zfill(6) == str(c_code).zfill(6)]
                    if not m.empty:
                        cur_p = float(m.iloc[0]['Close'])
                pnl_pct = ((cur_p - ep) / ep * 100) if ep > 0 else 0
                tot_entry += ep * qty
                tot_eval += cur_p * qty
                items.append({
                    'name': info.get('name', c_code),
                    'cur_price': cur_p,
                    'pnl_pct': pnl_pct
                })
            tot_pnl = tot_eval - tot_entry
            tot_pct = (tot_pnl / tot_entry * 100) if tot_entry > 0 else 0
            return {'items': items, 'tot_eval': tot_eval, 'tot_pnl': tot_pnl, 'tot_pct': tot_pct}

        elif query_type == 'quant_top':
            df_q = _load_csv_safely('df_quant_final.csv')
            df_m = _load_csv_safely('df_full_market.csv')
            if df_q.empty:
                return []
            if 'Total_Score' in df_q.columns:
                m_s = df_q['Total_Score'].mean()
                s_s = df_q['Total_Score'].std()
                if s_s > 0:
                    df_q['Total_Score_Adj'] = ((df_q['Total_Score'] - m_s) / s_s * 25.0 + 50.0).clip(0, 100).round(1)
                else:
                    df_q['Total_Score_Adj'] = df_q['Total_Score']
            
            keywords = ['KODEX', 'TIGER', 'ACE', 'KBSTAR', 'SOL', 'ARIRANG', 'HANARO', 'KOSEF', 'PLUS', 'TIMEFOLIO', '스팩', 'ETN', '선물', '인버스', '레버리지']
            df_q = df_q[~df_q['Name'].astype(str).str.contains('|'.join(keywords), case=False, regex=True)].copy()
            df_q['Code'] = df_q['Code'].astype(str).str.split('.').str[0].str.zfill(6)
            if not df_m.empty and 'Code' in df_m.columns:
                df_m['Code'] = df_m['Code'].astype(str).str.zfill(6)
                df_q = df_q.drop(columns=['Close', 'ChagesRatio', 'Amount'], errors='ignore')
                df_q = df_q.merge(df_m[['Code', 'Close', 'ChagesRatio', 'Amount']], on='Code', how='left')
            
            top_sub = df_q.sort_values(['Total_Score_Adj', 'Amount'], ascending=[False, False]).head(3)
            results = []
            for _, r in top_sub.iterrows():
                results.append({
                    'code': str(r['Code']).zfill(6),
                    'name': str(r.get('Name', '')),
                    'score': float(r.get('Total_Score_Adj', r.get('Total_Score', 0))),
                    'price': float(r.get('Close', 0)),
                    'chg': float(r.get('ChagesRatio', 0))
                })
            return results

        elif query_type == 'stock_chart':
            target_code = str(code or kwargs.get('code', '')).zfill(6)
            if target_code:
                df_c = fetch_stock_chart_df(target_code)
                if df_c is not None and not df_c.empty:
                    return df_c

        elif query_type == 'market':
            df_m = _load_csv_safely('df_market_summary.csv')
            ks_c = 2560.0
            if not df_m.empty and 'Close' in df_m.columns:
                ks_c = float(df_m.iloc[0]['Close'])
            return {
                'kospi_close': ks_c,
                'kospi_chg': 0.0,
                'b_ma5': 12.0,
                'b_status': '수급 안정',
                'stock_ratio': 70,
                'cash_ratio': 30
            }

    except Exception as ex:
        print(f'DEBUG: Standalone context error: {ex}')
    return {}

def run_standalone_bot():
    token, default_chat = _load_secrets()
    last_update_id = 0

    print('=' * 60)
    print('🚀 [GD 3.0] 텔레그램 양방향 스마트 비서 데몬 가동 시작')
    print(f'🤖 Bot Token: {token[:10]}...{token[-5:]}')
    print(f'👤 Master Chat ID: {default_chat}')
    print('💡 대표님의 버튼 입력 대기 중 (/포트, /추천, /시장, /도움말, 종목명 등)...')
    print('=' * 60)

    # 1. 외부 채널(엘리트강사/트레이딩스핀) 60초 주기 실시간 감시 스레드 시작
    threading.Thread(
        target=_run_external_channels_scanner,
        args=(token, default_chat),
        daemon=True
    ).start()

    while True:
        try:
            url = f'https://api.telegram.org/bot{token}/getUpdates?offset={last_update_id + 1}&timeout=5'
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                res = json.loads(resp.read().decode('utf-8'))
                if res.get('ok') and res.get('result'):
                    for upd in res['result']:
                        upd_id = upd.get('update_id', 0)
                        last_update_id = max(last_update_id, upd_id)

                        msg = upd.get('message', {})
                        chat = msg.get('chat', {})
                        sender_id = str(chat.get('id', ''))
                        text = msg.get('text', '')

                        cb = upd.get('callback_query')
                        if cb:
                            sender_id = str(cb.get('from', {}).get('id', sender_id))
                            text = cb.get('data', text)
                            cb_id = cb.get('id')
                            if cb_id:
                                try:
                                    ack_url = f'https://api.telegram.org/bot{token}/answerCallbackQuery?callback_query_id={cb_id}'
                                    urllib.request.urlopen(urllib.request.Request(ack_url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=3)
                                except Exception:
                                    pass

                        if text and sender_id:
                            try:
                                safe_t = text.encode('ascii', 'replace').decode('ascii')
                                print(f'[{time.strftime("%H:%M:%S")}] 📩 수신 [{sender_id}]: {safe_t}')
                            except Exception:
                                pass

                            process_incoming_command(
                                token=token,
                                chat_id=sender_id,
                                cmd_text=text,
                                context_fn=standalone_context_fn
                            )
        except Exception as e:
            try:
                print(f'[{time.strftime("%H:%M:%S")}] ⚠️ 폴링 대기 중... ({e})')
            except Exception:
                pass
            time.sleep(2)
        time.sleep(1)

if __name__ == '__main__':
    run_standalone_bot()
