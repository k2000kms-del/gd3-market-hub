import pandas as pd
from app import load_portfolio, get_stock_history

def main():
    portfolio = load_portfolio()
    for code, info in portfolio.items():
        name = info.get('name', code)
        df_daily = get_stock_history(code)
        if df_daily.empty or len(df_daily) < 5:
            print(f"{name}: No Daily Data")
            continue
            
        df_daily = df_daily.copy()
        df_daily['MA5_Daily'] = df_daily['Close'].rolling(5).mean()
        last_close = df_daily['Close'].iloc[-1]
        last_ma5 = df_daily['MA5_Daily'].iloc[-1]
        is_bullish = last_close >= last_ma5
        print(f"{name}: Close={last_close}, MA5={last_ma5:.1f}, Bullish={is_bullish}")

if __name__ == '__main__':
    main()
