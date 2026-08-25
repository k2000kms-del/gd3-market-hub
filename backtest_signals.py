import pandas as pd
import numpy as np
import os
import json
from app import load_portfolio, get_minute_history, resample_to_5min, calculate_intraday_signals

def run_backtest_for_code(code, name, timeframe='1min'):
    # 분봉 로드 (2000봉)
    df_1min = get_minute_history(code, count=2000)
    if df_1min.empty or len(df_1min) < 50:
        return None
    
    if timeframe == '5min':
        df = resample_to_5min(df_1min)
    else:
        df = df_1min.copy()
        
    if df.empty or len(df) < 30:
        return None
        
    # 신호 계산 (가상 신규 진입을 위해 my_entry_price=0.0 으로 설정)
    df_sig = calculate_intraday_signals(df, my_entry_price=0.0, timeframe=timeframe, code=code)
    
    trades = []
    in_position = False
    entry_price = 0.0
    entry_time = None
    entry_type = None
    add_count = 0
    raw_entry_price = 0.0  # 물타기 전 최초 진입가
    
    for i in range(len(df_sig)):
        row = df_sig.iloc[i]
        close_val = float(row['Close'])
        time_val = row['DateTime']
        
        # 포지션 미보유 중 -> 진입 신호 감지
        if not in_position:
            if row.get('Buy_Signal') == True:
                in_position = True
                entry_price = close_val
                raw_entry_price = close_val
                entry_time = time_val
                entry_type = 'BUY'
                add_count = 0
            elif row.get('Fall_Signal') == True:
                in_position = True
                entry_price = close_val
                raw_entry_price = close_val
                entry_time = time_val
                entry_type = 'FALL_BUY'
                add_count = 0
        # 포지션 보유 중 -> 추가 매수 또는 청산 신호 감지
        else:
            # 추가 매수
            if row.get('Add_Signal') == True and add_count == 0:
                entry_price = (entry_price + close_val) / 2
                add_count = 1
                
            # 청산
            if row.get('Exit_Signal') == True:
                pnl = ((close_val - entry_price) / entry_price) * 100
                trades.append({
                    'code': code,
                    'name': name,
                    'entry_time': entry_time,
                    'entry_type': entry_type,
                    'entry_price': raw_entry_price,
                    'final_avg_price': entry_price,
                    'added_water': add_count > 0,
                    'exit_time': time_val,
                    'exit_price': close_val,
                    'pnl_pct': pnl
                })
                in_position = False
                entry_price = 0.0
                entry_time = None
                entry_type = None
                add_count = 0
                
    return trades

def main():
    portfolio = load_portfolio()
    if not portfolio:
        print("Portfolio is empty or could not be loaded.")
        return
        
    for tf in ['1min', '5min']:
        print(f"\n==================================================")
        print(f"Backtesting Timeframe: {tf} (Recent ~5 Business Days Minute Data)")
        print(f"==================================================")
        
        all_trades = []
        summary_rows = []
        
        for code, info in portfolio.items():
            name = info.get('name', code)
            trades = run_backtest_for_code(code, name, timeframe=tf)
            
            if trades is None:
                continue
                
            all_trades.extend(trades)
            
            if len(trades) > 0:
                pnls = [t['pnl_pct'] for t in trades]
                win_count = sum(1 for p in pnls if p > 0)
                win_rate = (win_count / len(trades)) * 100
                avg_pnl = np.mean(pnls)
                cum_pnl = np.sum(pnls)
                max_win = np.max(pnls)
                max_loss = np.min(pnls)
            else:
                win_rate = 0.0
                avg_pnl = 0.0
                cum_pnl = 0.0
                max_win = 0.0
                max_loss = 0.0
                
            summary_rows.append({
                'Stock': name,
                'Trades': len(trades),
                'WinRate': f"{win_rate:.1f}%",
                'AvgPnL': f"{avg_pnl:+.2f}%",
                'CumPnL': f"{cum_pnl:+.2f}%",
                'MaxWin': f"{max_win:+.2f}%",
                'MaxLoss': f"{max_loss:+.2f}%"
            })
            
        # 종목별 결과 출력
        df_summary = pd.DataFrame(summary_rows)
        if not df_summary.empty:
            print(df_summary.to_string(index=False))
        else:
            print("No signals or trades occurred.")
            
        # 전체 종합 통계
        if all_trades:
            total_trades = len(all_trades)
            all_pnls = [t['pnl_pct'] for t in all_trades]
            total_wins = sum(1 for p in all_pnls if p > 0)
            total_win_rate = (total_wins / total_trades) * 100
            total_avg_pnl = np.mean(all_pnls)
            total_cum_pnl = np.sum(all_pnls)
            total_max_win = np.max(all_pnls)
            total_max_loss = np.min(all_pnls)
            
            print(f"\nSummary for {tf}:")
            print(f" - Total Trades : {total_trades}")
            print(f" - Win Rate    : {total_win_rate:.1f}%")
            print(f" - Avg PnL     : {total_avg_pnl:+.2f}%")
            print(f" - Cum PnL     : {total_cum_pnl:+.2f}%")
            print(f" - Max Win     : {total_max_win:+.2f}%")
            print(f" - Max Loss    : {total_max_loss:+.2f}%")
        else:
            print(f"\nSummary for {tf}: No trades occurred.")

if __name__ == '__main__':
    main()
