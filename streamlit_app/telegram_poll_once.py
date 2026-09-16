# -*- coding: utf-8 -*-
"""
telegram_poll_once.py
---------------------
GitHub Actions에서 호출되는 경량 텔레그램 폴링 스크립트.
최대 POLL_DURATION_SEC 초 동안 getUpdates 루프를 실행하고 종료합니다.
last_update_id를 data/last_update_id.json에 저장/복원하여
다음 Actions 실행 시 이어받아 메시지 중복 처리를 방지합니다.
"""
import os
import sys
import json
import time
import urllib.request
from datetime import datetime, timezone, timedelta

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 한 번 실행 시 폴링할 최대 초 (5분 주기 cron에서 여유 있게 160초)
POLL_DURATION_SEC = 160
LONG_POLL_TIMEOUT = 5
LOOP_INTERVAL = 1.0
KST = timezone(timedelta(hours=9))
STATE_FILE = os.path.join(BASE_DIR, 'data', 'last_update_id.json')


def _load_last_update_id():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return int(json.load(f).get('last_update_id', 0))
        except Exception:
            pass
    return 0


def _save_last_update_id(uid):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump({'last_update_id': uid, 'saved_at': datetime.now(KST).isoformat()}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"last_update_id 저장 실패: {e}")


def _load_secrets():
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not token:
        for s_path in [
            os.path.join(BASE_DIR, '.streamlit', 'secrets.toml'),
            os.path.join(BASE_DIR, 'streamlit_app', '.streamlit', 'secrets.toml'),
        ]:
            if os.path.exists(s_path):
                try:
                    import toml
                    s = toml.load(s_path)
                    token = token or s.get('TELEGRAM_BOT_TOKEN', '')
                    chat_id = chat_id or str(s.get('TELEGRAM_CHAT_ID', ''))
                    if token:
                        break
                except Exception:
                    pass
    return (token or '').strip(), str(chat_id or '').strip()


def _build_context_fn():
    import pandas as pd

    def _load_csv(fname):
        p = os.path.join(BASE_DIR, 'data', fname)
        if os.path.exists(p):
            try:
                return pd.read_csv(p)
            except Exception:
                pass
        return pd.DataFrame()

    def context_fn(query_type, code=None, **kwargs):
        try:
            if query_type == 'portfolio':
                port_path = os.path.join(BASE_DIR, 'data', 'portfolio.json')
                port = {}
                if os.path.exists(port_path):
                    with open(port_path, 'r', encoding='utf-8') as f:
                        port = json.load(f)
                df_m = _load_csv('df_full_market.csv')
                holdings = []
                for code_k, info in port.items():
                    avg = float(info.get('avg_price', 0))
                    qty = int(info.get('quantity', 0))
                    name = str(info.get('name', code_k))
                    cur_price = avg
                    if not df_m.empty and 'Code' in df_m.columns and 'Close' in df_m.columns:
                        row = df_m[df_m['Code'].astype(str).str.zfill(6) == str(code_k).zfill(6)]
                        if not row.empty:
                            cur_price = float(row.iloc[0]['Close'])
                    pnl_pct = ((cur_price - avg) / avg * 100) if avg > 0 else 0.0
                    holdings.append({'code': code_k, 'name': name, 'avg_price': avg,
                                     'quantity': qty, 'current_price': cur_price, 'pnl_pct': pnl_pct})
                return {'holdings': holdings, 'total_count': len(holdings)}

            elif query_type == 'quant':
                df_q = _load_csv('df_quant_results.csv')
                rows = []
                if not df_q.empty:
                    sc_col = 'Calibrated_Score' if 'Calibrated_Score' in df_q.columns else 'Total_Score'
                    for _, r in df_q.sort_values(sc_col, ascending=False).head(10).iterrows():
                        rows.append({'name': str(r.get('Name', '')),
                                     'code': str(r.get('Code', '')).split('.')[0].strip().zfill(6),
                                     'score': float(r.get(sc_col, 0))})
                return {'quant_rows': rows}

            elif query_type == 'market':
                df_m = _load_csv('df_market_summary.csv')
                ks_c = 2560.0
                if not df_m.empty and 'Close' in df_m.columns:
                    ks_c = float(df_m.iloc[0]['Close'])
                return {'kospi_close': ks_c, 'kospi_chg': 0.0,
                        'b_ma5': 12.0, 'b_status': '수급 안정', 'stock_ratio': 70, 'cash_ratio': 30}
        except Exception as ex:
            print(f"context_fn 오류: {ex}")
        return {}

    return context_fn


def run_poll_loop(token, default_chat_id):
    from telegram_notifier import process_incoming_command

    last_update_id = _load_last_update_id()
    context_fn = _build_context_fn()
    start_time = time.time()
    processed_count = 0

    print(f"[Poll Loop 시작] last_update_id={last_update_id}, 최대 {POLL_DURATION_SEC}초 실행")

    while (time.time() - start_time) < POLL_DURATION_SEC:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates?offset={last_update_id + 1}&timeout={LONG_POLL_TIMEOUT}"
            req = urllib.request.Request(url, headers={'User-Agent': 'GD3-CloudBot/1.0'})
            with urllib.request.urlopen(req, timeout=LONG_POLL_TIMEOUT + 5) as resp:
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
                                    ack_url = f"https://api.telegram.org/bot{token}/answerCallbackQuery?callback_query_id={cb_id}"
                                    urllib.request.urlopen(urllib.request.Request(ack_url, headers={'User-Agent': 'GD3-CloudBot/1.0'}), timeout=3)
                                except Exception:
                                    pass
                        if text and sender_id:
                            print(f"[{datetime.now(KST).strftime('%H:%M:%S')}] 수신 [{sender_id}]: {text[:80]}")
                            try:
                                process_incoming_command(token=token, chat_id=sender_id,
                                                         cmd_text=text, context_fn=context_fn)
                                processed_count += 1
                            except Exception as cmd_err:
                                print(f"명령 처리 오류: {cmd_err}")
        except Exception as e:
            err_str = str(e)
            print(f"[{datetime.now(KST).strftime('%H:%M:%S')}] 폴링 대기/오류: {err_str}")
            if "409" in err_str:
                print("💡 [상호 양보] 로컬 PC 데몬이 활성화되어 실시간 응답 중입니다. 클라우드 러너는 역할을 양보하고 정상 조기 종료합니다.")
                break
            time.sleep(2)
            continue
        time.sleep(LOOP_INTERVAL)

    elapsed = time.time() - start_time
    print(f"[Poll Loop 종료] 실행시간={elapsed:.0f}초, 처리={processed_count}건, last_update_id={last_update_id}")
    return last_update_id


if __name__ == '__main__':
    now_kst = datetime.now(KST)
    print('=' * 60)
    print(f"[GitHub Actions] 텔레그램 폴링 시작: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} KST")
    print('=' * 60)
    token, chat_id = _load_secrets()
    if not token:
        print("TELEGRAM_BOT_TOKEN 미설정. GitHub Secrets 확인 필요.")
        sys.exit(1)
    print(f"Bot Token: {token[:10]}...{token[-5:]}")
    print(f"Master Chat ID: {chat_id}")
    last_uid = run_poll_loop(token, chat_id)
    _save_last_update_id(last_uid)
    print(f"last_update_id={last_uid} 저장 완료")
    print('=' * 60)
    print("텔레그램 폴링 완료. Actions 종료.")
