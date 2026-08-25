import os
import pandas as pd

def find_top_stocks():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    q_file = os.path.join(base_dir, 'data', 'df_quant_final.csv')
    
    if os.path.exists(q_file):
        df_q = pd.read_csv(q_file)
        # 보정 점수 계산 모사
        mean_score = df_q['Total_Score'].mean()
        std_score = df_q['Total_Score'].std()
        if std_score > 0:
            df_q['Total_Score_Adj'] = df_q['Total_Score'].apply(lambda x: round(min(100.0, max(0.0, ((x - mean_score) / std_score * 25.0) + 50.0)), 1))
        else:
            df_q['Total_Score_Adj'] = df_q['Total_Score']
            
        df_top = df_q[df_q['Total_Score_Adj'] >= 60.0].sort_values('Total_Score_Adj', ascending=False)
        print(f"보정 퀀트 점수가 60점 이상인 종목 개수: {len(df_top)}개")
        print("\n=== 점수 상위 종목 목록 (Top 10) ===")
        for idx, row in df_top.head(10).iterrows():
            print(f"종목명: {row['Name']}, 코드: {row['Code']}, 보정점수: {row['Total_Score_Adj']}점")
    else:
        print("df_quant_final.csv 파일 없음")

if __name__ == "__main__":
    find_top_stocks()
