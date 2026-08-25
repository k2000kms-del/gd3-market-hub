# -*- coding: utf-8 -*-
"""
GD 3.0 Market Hub - 독립형 24시간 상시 가동 텔레그램 봇 데몬
브라우저 대시보드 접속 여부와 완전히 무관하게 백그라운드에서 상시 대기하며,
대표님의 텔레그램 명령어 및 원터치 버튼 요청에 0.5초 이내로 즉각 응답합니다.
"""

import sys, os, time, json, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from telegram_notifier import process_incoming_command

# 컨텍스트 제공 함수
def _daemon_get_context(query_type, code=None, **kwargs):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        if query_type == 'portfolio':
            pf_path = os.path.join(base_dir, 'data', 'my_portfolio.json')
            m_path = os.path.join(base_dir, 'data', 'df_full_market.csv')
            if os.path.exists(pf_path):
                with open(pf_path, encoding='utf-8') as f:
                    port = json.load(f)
                df_m = pd.read_csv(m_path, dtype={'Code': str}) if os.path.exists(m_path) else pd.DataFrame()
                items, tot_eval, tot_entry = [], 0, 0
                for c, info in port.items():
                    ep = float(info.get('entry_price', 0))
                    qty = float(info.get('qty', 0))
                    cur_p = ep
                    if not df_m.empty and 'Code' in df_m.columns:
                        m = df_m[df_m['Code'].astype(str).str.zfill(6) == str(c).zfill(6)]
                        if not m.empty:
                            cur_p = float(m.iloc[0]['Close'])
                    pnl = ((cur_p - ep) / ep * 100) if ep > 0 else 0
                    tot_entry += ep * qty
                    tot_eval += cur_p * qty
                    items.append({'name': info.get('name', c), 'cur_price': cur_p, 'pnl_pct': pnl})
                tot_pnl = tot_eval - tot_entry
                tot_pct = (tot_pnl / tot_entry * 100) if tot_entry > 0 else 0
                return {'items': items, 'tot_eval': tot_eval, 'tot_pnl': tot_pnl, 'tot_pct': tot_pct}

        elif query_type == 'quant_top':
            q_path = os.path.join(base_dir, 'data', 'df_quant_final.csv')
            m_path = os.path.join(base_dir, 'data', 'df_full_market.csv')
            if os.path.exists(q_path):
                df_q = pd.read_csv(q_path, dtype={'Code': str})
                df_m = pd.read_csv(m_path, dtype={'Code': str}) if os.path.exists(m_path) else pd.DataFrame()
                
                # ── 대시보드와 100% 동일한 z-score Calibration ──
                if 'Total_Score' in df_q.columns:
                    mean_score = df_q['Total_Score'].mean()
                    std_score = df_q['Total_Score'].std()
                    if std_score > 0:
                        df_q['Total_Score_Adj'] = ((df_q['Total_Score'] - mean_score) / std_score * 25.0 + 50.0).clip(0.0, 100.0).round(1)
                    else:
                        df_q['Total_Score_Adj'] = df_q['Total_Score']
                
                # ETF / 스팩 제외 필터링
                keywords = ['KODEX', 'TIGER', 'ACE', 'KBSTAR', 'SOL', 'ARIRANG', 'HANARO', 'KOSEF', 'PLUS', 'TIMEFOLIO', '스팩', 'ETN', '선물', '인버스', '레버리지']
                pattern = '|'.join(keywords)
                mask = ~df_q['Name'].astype(str).str.contains(pattern, case=False, regex=True)
                df_q = df_q[mask].copy()

                df_q['Code'] = df_q['Code'].astype(str).str.split('.').str[0].str.zfill(6)
                if not df_m.empty and 'Code' in df_m.columns:
                    df_q = df_q.drop(columns=['Close', 'ChagesRatio', 'Amount'], errors='ignore')
                    df_q = df_q.merge(df_m[['Code', 'Close', 'ChagesRatio', 'Amount']], on='Code', how='left')

                top = df_q.sort_values('Total_Score_Adj', ascending=False).head(3)
                res = []
                for _, r in top.iterrows():
                    res.append({
                        'code': str(r['Code']).zfill(6),
                        'name': str(r.get('Name', '')),
                        'score': float(r.get('Total_Score_Adj', r.get('Total_Score', 0))),
                        'price': float(r.get('Close', 0)),
                        'chg': float(r.get('ChagesRatio', 0))
                    })
                return res

        elif query_type == 'stock_chart':
            target_code = code or kwargs.get('code', '')
            if target_code:
                import FinanceDataReader as fdr
                from datetime import datetime, timedelta
                start_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
                try:
                    df = fdr.DataReader(target_code, start=start_date)
                    if not df.empty:
                        df.reset_index(inplace=True)
                        df.rename(columns={'Date': 'DateTime'}, inplace=True)
                        return df
                except Exception as e:
                    print(f"DEBUG: FDR error for {target_code}: {e}")

        elif query_type == 'market':
            b_data = {}
            try:
                from backend.services import get_bollinger_market_energy
                b_data = get_bollinger_market_energy() or {}
            except Exception:
                pass
            return {
                'kospi_close': 2650.0,
                'b_ma5': b_data.get('ma5', 0),
                'b_status': b_data.get('energy_status', '보통'),
                'stock_ratio': 70,
                'cash_ratio': 30
            }
    except Exception as ex:
        print(f"DEBUG: _daemon_get_context error: {ex}")
    return None


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    secrets_path = os.path.join(base_dir, '.streamlit', 'secrets.toml')
    token = ""
    if os.path.exists(secrets_path):
        with open(secrets_path, encoding='utf-8') as f:
            for l in f:
                if 'TELEGRAM_BOT_TOKEN' in l and '=' in l:
                    token = l.split('=', 1)[1].strip().strip('"').strip("'")

    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN이 설정되지 않았습니다.")
        return

    print("🚀 [GD 3.0 텔레그램 상시 대기 봇 데몬] 가동 시작...")
    last_update_id = 0

    while True:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates?offset={last_update_id + 1}&timeout=10"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get('ok') and data.get('result'):
                    for upd in data['result']:
                        upd_id = upd.get('update_id', 0)
                        last_update_id = max(last_update_id, upd_id)
                        msg = upd.get('message', {})
                        chat = msg.get('chat', {})
                        sender_id = str(chat.get('id', ''))
                        text = msg.get('text', '')

                        if text and sender_id:
                            print(f"📥 수신 [{sender_id}]: {text}")
                            process_incoming_command(
                                token=token,
                                chat_id=sender_id,
                                cmd_text=text,
                                context_fn=_daemon_get_context
                            )
        except Exception as e:
            time.sleep(1)
        time.sleep(0.5)

if __name__ == '__main__':
    main()