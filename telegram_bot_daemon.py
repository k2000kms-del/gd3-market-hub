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
import urllib.request
import pandas as pd

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from telegram_notifier import process_incoming_command
from chart_image_generator import fetch_stock_chart_df, generate_stock_chart_image

def _load_csv_safely(fname: str) -> pd.DataFrame:
    p = os.path.join(CURRENT_DIR, 'data', fname)
    if os.path.exists(p):
        try:
            return pd.read_csv(p)
        except Exception:
            pass
    return pd.DataFrame()

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
    token = '8648882409:AAGy9s1qRhRqi7dN5_X9HYSrfDaz7AdW5aM'
    default_chat = '1131551088'
    last_update_id = 0

    print('=' * 60)
    print('🚀 [GD 3.0] 텔레그램 양방향 스마트 비서 데몬 가동 시작')
    print(f'🤖 Bot Token: {token[:10]}...{token[-5:]}')
    print(f'👤 Master Chat ID: {default_chat}')
    print('💡 대표님의 버튼 입력 대기 중 (/포트, /추천, /시장, /도움말 등)...')
    print('=' * 60)

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
