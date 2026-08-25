import pandas as pd
import numpy as np
import FinanceDataReader as fdr

# gd3_market_hub/data/df_quant_final.csv 에서 코드를 가져와서 FinanceDataReader로 조회
df_quant = pd.read_csv("data/df_quant_final.csv")
codes = df_quant['Code'].unique()

print(f"Total codes to search: {len(codes)}")
found = []

for raw_code in codes:
    code = str(raw_code).split('.')[0].zfill(6)
    try:
        df = fdr.DataReader(code, "2026-02-01", "2026-06-23")
        if df.empty:
            continue
        
        # 2월 26일~28일 부근의 고가가 650,000원~700,000원 사이이고,
        # 3월 3일~5일 부근의 종가/저가가 490,000원~515,000원 사이인 종목 탐색
        df_target_feb = df.loc["2026-02-25":"2026-03-02"]
        df_target_mar = df.loc["2026-03-02":"2026-03-06"]
        
        if not df_target_feb.empty and not df_target_mar.empty:
            max_feb_high = df_target_feb['High'].max()
            min_mar_close = df_target_mar['Close'].min()
            
            # 오차 범위를 넉넉하게 잡음
            if 650000 <= max_feb_high <= 720000 and 480000 <= min_mar_close <= 520000:
                print(f"Candidate found: {code}, Max Feb High: {max_feb_high}, Min Mar Close: {min_mar_close}")
                # 종목 정보 찾기
                found.append(code)
    except Exception as e:
        pass

print("Search complete.")
