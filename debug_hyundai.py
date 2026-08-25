import os
import pandas as pd
import numpy as np
import FinanceDataReader as fdr

def run_debug():
    print("=== 현대차 시그널 디버깅 ===")
    
    # 1. 퀀트 점수 파일 확인
    base_dir = os.path.dirname(os.path.abspath(__file__))
    q_file = os.path.join(base_dir, 'data', 'df_quant_final.csv')
    
    t_score_adj = 60.0
    if os.path.exists(q_file):
        df_q = pd.read_csv(q_file)
        df_q['Code'] = df_q['Code'].astype(str).str.split('.').str[0].str.zfill(6)
        q_match = df_q[df_q['Code'] == '005380']
        if not q_match.empty:
            print(f"현대차 수량 매칭 성공! 원래 컬럼들: {q_match.columns.tolist()}")
            # 보정 점수 계산 모사
            mean_score = df_q['Total_Score'].mean()
            std_score = df_q['Total_Score'].std()
            raw_score = float(q_match.iloc[0]['Total_Score'])
            if std_score > 0:
                t_score_adj = round(min(100.0, max(0.0, ((raw_score - mean_score) / std_score * 25.0) + 50.0)), 1)
            else:
                t_score_adj = raw_score
            print(f"현대차 원점수: {raw_score}, 보정 퀀트 점수: {t_score_adj}")
        else:
            print("df_quant_final.csv 내에 현대차(005380) 코드가 존재하지 않습니다.")
    else:
        print("df_quant_final.csv 파일이 존재하지 않습니다.")
        
    # 2. 일봉 캔들 데이터 로딩 및 계산
    df_candle = fdr.DataReader('005380')
    if df_candle.empty:
        print("현대차 데이터 로딩 실패")
        return
        
    df_candle = df_candle.copy()
    close = df_candle['Close'].values
    high = df_candle['High'].values
    low = df_candle['Low'].values
    
    # ATR 계산
    tr = np.maximum(high[1:] - low[1:], np.maximum(abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1])))
    tr = np.insert(tr, 0, high[0] - low[0])
    df_candle['ATR'] = pd.Series(tr, index=df_candle.index).rolling(14).mean()
    df_candle['MA5'] = df_candle['Close'].rolling(5).mean()
    
    # 캔들 속성
    body = abs(close - df_candle['Open'].values)
    high_shadow = high - np.maximum(close, df_candle['Open'].values)
    low_shadow = np.minimum(close, df_candle['Open'].values) - low
    is_pinbar = (high_shadow > (body * 2.0)) & (close < df_candle['Open'].values)
    is_vol_spike = df_candle['Volume'] > df_candle['Volume'].rolling(20).mean() * 2.5
    
    adjusted_high = np.where(is_pinbar & is_vol_spike, df_candle['Close'], df_candle['High'])
    df_candle['Adj_Highest_High'] = pd.Series(adjusted_high, index=df_candle.index).rolling(20).max()
    
    # 리스크 가속
    ret_5d = df_candle['Close'].pct_change(5) * 100.0
    vol_ratio = df_candle['Volume'] / df_candle['Volume'].rolling(20).mean()
    risk_accelerate = (ret_5d < -7.0) | ((ret_5d < -3.0) & (vol_ratio > 2.0))
    atr_multiplier = np.where(risk_accelerate, 1.0, 2.5)
    
    # 매수/매도 판정
    dynamic_trigger_sl = df_candle['Adj_Highest_High'] - atr_multiplier * df_candle['ATR']
    exit_signal_list = []
    buy_signal_list = []
    in_position = True
    entry_price = df_candle['Close'].iloc[0]
    max_price_since_entry = entry_price
    days_in_position = 0
    
    for i in range(len(df_candle)):
        close_val = df_candle['Close'].iloc[i]
        open_val = df_candle['Open'].iloc[i]
        trigger_sl = dynamic_trigger_sl.iloc[i]
        ma5_val = df_candle['MA5'].iloc[i]
        prev_sl = dynamic_trigger_sl.iloc[i-1] if i > 0 else trigger_sl
        
        if pd.isna(trigger_sl) or pd.isna(ma5_val):
            exit_signal_list.append(False)
            buy_signal_list.append(False)
            continue
            
        if in_position:
            buy_signal_list.append(False)
            days_in_position += 1
            max_price_since_entry = max(max_price_since_entry, close_val)
            if max_price_since_entry >= entry_price * 1.10:
                trigger_sl = max(trigger_sl, entry_price * 1.01)
                
            if open_val < prev_sl:
                exit_signal_list.append(True)
                in_position = False
                days_in_position = 0
            elif days_in_position >= 5 and abs((close_val - entry_price) / entry_price) <= 0.02:
                exit_signal_list.append(True)
                in_position = False
                days_in_position = 0
            elif close_val < trigger_sl:
                exit_signal_list.append(True)
                in_position = False
                days_in_position = 0
            else:
                exit_signal_list.append(False)
        else:
            exit_signal_list.append(False)
            # 미보유 상태: MA5 상향 돌파 + 퀀트 점수가 60점 이상일 때만 매수 진입
            if close_val > ma5_val and (t_score_adj >= 60.0):
                buy_signal_list.append(True)
                in_position = True
                entry_price = close_val
                max_price_since_entry = close_val
                days_in_position = 0
            else:
                buy_signal_list.append(False)
                
    df_candle['Exit_Signal'] = exit_signal_list
    df_candle['Buy_Signal'] = buy_signal_list
    
    # 최근 90거래일 잘라서 신호 발생 수 세어보기
    df_recent = df_candle.tail(90)
    buys = df_recent['Buy_Signal'].sum()
    exits = df_recent['Exit_Signal'].sum()
    print(f"최근 90거래일 동안의 신호 발생 수 - 매수: {buys}회, 매도: {exits}회")
    
    print("\n--- 최근 90거래일 신호 발생 날짜 목록 ---")
    for idx, row in df_recent.iterrows():
        if row['Buy_Signal'] or row['Exit_Signal']:
            sig_type = "매수 🟢" if row['Buy_Signal'] else "매도 🔴"
            print(f"날짜: {idx.strftime('%Y-%m-%d')}, 신호: {sig_type}, 종가: {row['Close']:.0f}원, MA5: {row['MA5']:.0f}원")

if __name__ == "__main__":
    run_debug()
