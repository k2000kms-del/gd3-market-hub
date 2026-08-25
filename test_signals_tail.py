import pandas as pd
from app import load_portfolio, get_minute_history, resample_to_5min, calculate_intraday_signals

def main():
    # SK하이닉스(000660)와 삼성전자(005930)에 대해 테스트
    targets = {'000660': 'SK하이닉스', '005930': '삼성전자'}
    
    for code, name in targets.items():
        print(f"\n==================== {name} ({code}) ====================")
        df_1min = get_minute_history(code, count=2000)
        
        # 1분봉 분석 (당일 필터링 후 꼬리)
        df_1min_sig = calculate_intraday_signals(df_1min, my_entry_price=0.0, timeframe='1min', code=code)
        latest_date_1m = df_1min_sig['DateTime'].dt.date.max()
        df_1min_tail = df_1min_sig[df_1min_sig['DateTime'].dt.date == latest_date_1m].copy().reset_index(drop=True)
        
        # 5분봉 분석 (최근 250봉 꼬리)
        df_5min = resample_to_5min(df_1min)
        df_5min_sig = calculate_intraday_signals(df_5min, my_entry_price=0.0, timeframe='5min', code=code)
        df_5min_tail = df_5min_sig.tail(250).copy().reset_index(drop=True)
        
        print("[1분봉 전체 신호 수]")
        print(" - Buy_Signal :", df_1min_sig['Buy_Signal'].sum())
        print(" - Fall_Signal:", df_1min_sig['Fall_Signal'].sum())
        print(" - Exit_Signal:", df_1min_sig['Exit_Signal'].sum())
        
        print("[1분봉 차트(당일 필터링 영역) 신호 수]")
        print(" - Buy_Signal :", df_1min_tail['Buy_Signal'].sum())
        print(" - Fall_Signal:", df_1min_tail['Fall_Signal'].sum())
        print(" - Exit_Signal:", df_1min_tail['Exit_Signal'].sum())
        
        print("[5분봉 전체 신호 수]")
        print(" - Buy_Signal :", df_5min_sig['Buy_Signal'].sum())
        print(" - Fall_Signal:", df_5min_sig['Fall_Signal'].sum())
        print(" - Exit_Signal:", df_5min_sig['Exit_Signal'].sum())
        
        print("[5분봉 차트(최근 250봉) 신호 수]")
        print(" - Buy_Signal :", df_5min_tail['Buy_Signal'].sum())
        print(" - Fall_Signal:", df_5min_tail['Fall_Signal'].sum())
        print(" - Exit_Signal:", df_5min_tail['Exit_Signal'].sum())

if __name__ == '__main__':
    main()
