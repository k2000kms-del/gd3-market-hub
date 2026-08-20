"""
GD 3.0 Market Hub - 독립형 텔레그램 양방향 비서 데몬
브라우저 접속 여부와 상관없이 24시간 상시 가동되어,
대표님의 버튼 터치 및 명령어에 0.3초 내로 즉각 답변합니다.
"""

import os
import sys
import time
import json
import requests
import toml
import pandas as pd
from datetime import datetime, timezone, timedelta

_KST = timezone(timedelta(hours=9))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)

# streamlit_app 폴더를 최우선 검색 경로로 설정
sys.path.insert(0, BASE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)

from telegram_notifier import process_incoming_command, _send, _send_photo
from chart_image_generator import generate_stock_chart_image

def _load_secrets():
    sec_path = os.path.join(BASE_DIR, '.streamlit', 'secrets.toml')
    if os.path.exists(sec_path):
        try:
            return toml.load(sec_path)
        except Exception:
            pass
    return {}

def _load_csv(filename):
    fpath = os.path.join(BASE_DIR, 'data', filename)
    if os.path.exists(fpath):
        try:
            return pd.read_csv(fpath, dtype={'Code': str})
        except Exception:
            pass
    return pd.DataFrame()

def _load_portfolio():
    fpath = os.path.join(BASE_DIR, 'data', 'my_portfolio.json')
    if os.path.exists(fpath):
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def get_context(query_type, code=None):
    try:
        if query_type == 'stock_chart' and code:
            import FinanceDataReader as fdr
            try:
                df_c = fdr.DataReader(str(code).zfill(6))
                if not df_c.empty:
                    df_c = df_c.reset_index()
                    df_c.rename(columns={'index': 'Date'}, inplace=True)
                    return df_c.tail(35)
            except Exception as e:
                print(f"DEBUG: FDR fetch error for {code}: {e}")
            return pd.DataFrame()

        elif query_type == 'portfolio':
            port = _load_portfolio() or {}
            df_m = _load_csv('df_full_market.csv')
            items = []
            tot_eval = 0
            tot_entry = 0
            for c_code, info in port.items():
                ep = float(info.get('entry_price', 0))
                qty = float(info.get('qty', 0))
                cur_p = ep
                if not df_m.empty and 'Code' in df_m.columns:
                    match = df_m[df_m['Code'].astype(str).str.zfill(6) == str(c_code).zfill(6)]
                    if not match.empty:
                        cur_p = float(match.iloc[0]['Close'])
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
            df_q = _load_csv('df_quant_final.csv')
            if df_q.empty:
                return []
            score_col = 'Total_Score_Adj' if 'Total_Score_Adj' in df_q.columns else ('Total_Score' if 'Total_Score' in df_q.columns else None)
            if not score_col:
                return []
            top = df_q.sort_values(score_col, ascending=False).head(3)
            results = []
            for _, r in top.iterrows():
                results.append({
                    'code': str(r['Code']).zfill(6),
                    'name': str(r.get('Name', '')),
                    'score': float(r[score_col]),
                    'price': float(r.get('Close', 0)),
                    'chg': float(r.get('ChagesRatio', 0))
                })
            return results

        elif query_type == 'market':
            b_data = {}
            try:
                from backend.services import get_bollinger_market_energy
                b_data = get_bollinger_market_energy() or {}
            except Exception:
                pass
            return {
                'kospi_close': 2680.0,
                'kospi_chg': 0.0,
                'b_ma5': b_data.get('ma5', 0),
                'b_status': b_data.get('energy_status', '보통'),
                'stock_ratio': 70,
                'cash_ratio': 30
            }
    except Exception as ex:
        print(f"DEBUG: get_context error: {ex}")
    return {}

def main():
    print("🚀 [GD 3.0] 독립형 텔레그램 양방향 비서 데몬 가동 시작...")
    last_update_id = 0

    while True:
        try:
            secrets = _load_secrets()
            token = secrets.get('TELEGRAM_BOT_TOKEN', os.environ.get('TELEGRAM_BOT_TOKEN', ''))
            chat_id = str(secrets.get('TELEGRAM_CHAT_ID', os.environ.get('TELEGRAM_CHAT_ID', '')))

            if not token:
                print("⚠️ TELEGRAM_BOT_TOKEN 누락. 5초 후 재시도...")
                time.sleep(5)
                continue

            url = f"https://api.telegram.org/bot{token}/getUpdates"
            params = {
                "offset": last_update_id + 1,
                "timeout": 5
            }

            try:
                res = requests.get(url, params=params, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    if data.get('ok') and data.get('result'):
                        for upd in data['result']:
                            upd_id = upd.get('update_id', 0)
                            last_update_id = max(last_update_id, upd_id)
                            msg = upd.get('message', {})
                            c = msg.get('chat', {})
                            sender_id = str(c.get('id', ''))
                            text = msg.get('text', '')

                            if text:
                                print(f"📩 [{datetime.now(_KST).strftime('%H:%M:%S')}] 텔레그램 명령 수신 from {sender_id}: {text}")
                                ok = process_incoming_command(
                                    token=token,
                                    chat_id=sender_id,
                                    cmd_text=text,
                                    context_fn=get_context
                                )
                                print(f"  ↳ 응답 전송 결과: {ok}")
                elif res.status_code == 409:
                    time.sleep(2)
            except requests.RequestException:
                time.sleep(1)

        except Exception as e:
            print(f"❌ 데몬 루프 예외: {e}")
            time.sleep(2)

if __name__ == '__main__':
    main()
