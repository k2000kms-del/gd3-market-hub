import pandas as pd
from app import load_portfolio, get_minute_history, resample_to_5min, calculate_intraday_signals

def main():
    portfolio = load_portfolio()
    for tf in ['1min', '5min']:
        print(f"\n=== {tf} RAW SIGNAL COUNT ===")
        for code, info in portfolio.items():
            name = info.get('name', code)
            df_1min = get_minute_history(code, count=2000)
            if df_1min.empty:
                print(f"{name}: No Data")
                continue
            
            if tf == '5min':
                df = resample_to_5min(df_1min)
            else:
                df = df_1min.copy()
                
            df_sig = calculate_intraday_signals(df, my_entry_price=0.0, timeframe=tf, code=code)
            
            buy_cnt = df_sig['Buy_Signal'].sum() if 'Buy_Signal' in df_sig.columns else 0
            fall_cnt = df_sig['Fall_Signal'].sum() if 'Fall_Signal' in df_sig.columns else 0
            exit_cnt = df_sig['Exit_Signal'].sum() if 'Exit_Signal' in df_sig.columns else 0
            add_cnt = df_sig['Add_Signal'].sum() if 'Add_Signal' in df_sig.columns else 0
            
            print(f" {name}: Buy={buy_cnt}, Fall={fall_cnt}, Exit={exit_cnt}, Add={add_cnt}")

if __name__ == '__main__':
    main()
