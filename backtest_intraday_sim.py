# -*- coding: utf-8 -*-
"""
backtest_intraday_sim.py
일봉 데이터로 가상 분봉(1분/5분) 생성 → 분봉 신호 백테스트
"""
import warnings; warnings.filterwarnings('ignore')
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import numpy as np
import pandas as pd
import FinanceDataReader as fdr
from itertools import product
from datetime import datetime, timedelta

FEE_RT = 0.00015 + 0.00015 + 0.002   # 왕복 ~0.23%

TEST_STOCKS = {
    '005930': '삼성전자',
    '000660': 'SK하이닉스',
    '035420': 'NAVER',
    '051910': 'LG화학',
    '005490': 'POSCO홀딩스',
    '035720': '카카오',
    '003550': 'LG',
    '028260': '삼성물산',
    '012330': '현대모비스',
    '068270': '셀트리온',
}

# ── 일봉 → 가상 분봉 생성 ──────────────────────────────────────
def daily_to_min_bars(df_daily: pd.DataFrame, bars_per_day: int = 78) -> pd.DataFrame:
    """
    일봉 1개 → bars_per_day개 가상 분봉 생성.
    - 1분봉: bars_per_day=78 (09:00~15:30 → 390분, 5봉 단위 = 78)
    - 5분봉: bars_per_day=78 그대로 (이미 5분봉 단위)
    경로(패턴): Open → 중간진동 → Close, High/Low는 Brownian 노이즈로 배치
    """
    rows = []
    for dt, row in df_daily.iterrows():
        o, h, l, c, vol = row['Open'], row['High'], row['Low'], row['Close'], row['Volume']
        prices = np.linspace(o, c, bars_per_day)
        # 노이즈 추가 (일중 변동성 반영)
        noise_scale = (h - l) * 0.08
        noise = np.random.randn(bars_per_day) * noise_scale
        prices = prices + noise
        prices = np.clip(prices, l, h)
        prices[-1] = c   # 마지막 봉은 정확히 종가

        # 가상 고가/저가
        highs = prices + np.abs(np.random.randn(bars_per_day)) * noise_scale * 0.5
        lows  = prices - np.abs(np.random.randn(bars_per_day)) * noise_scale * 0.5
        # 전체 High/Low를 일봉 범위 내로 제한
        highs = np.minimum(highs, h)
        lows  = np.maximum(lows, l)

        # 거래량 배분 (U자형: 장 초반·후반에 몰림)
        u = np.linspace(0, np.pi, bars_per_day)
        vol_weights = 1.5 - np.cos(u) * 0.5
        vol_weights /= vol_weights.sum()
        vols = (vol * vol_weights).astype(int)

        for j in range(bars_per_day):
            rows.append({
                'DateTime': pd.Timestamp(dt) + pd.Timedelta(minutes=j*5 + 30),
                'Open': prices[max(0,j-1)],
                'High': highs[j],
                'Low':  lows[j],
                'Close': prices[j],
                'Volume': max(vols[j], 1),
                'Date': dt.date() if hasattr(dt, 'date') else dt
            })
    return pd.DataFrame(rows)

def to_5min(df1: pd.DataFrame) -> pd.DataFrame:
    """1분봉 단위 → 5봉 묶어서 5분봉 (이미 5분봉이면 바로 사용)"""
    # 시뮬레이션 분봉은 이미 5분 단위이므로 그대로 반환
    return df1

# ── 지표 계산 ──────────────────────────────────────────────────
def calc_rsi(s, p=14):
    d=s.diff(); g=d.clip(lower=0).rolling(p).mean()
    l=(-d.clip(upper=0)).rolling(p).mean()
    return 100 - 100/(1+g/l.replace(0,np.nan))

def calc_atr(df, p=7):
    h,l,c=df['High'],df['Low'],df['Close']; pc=c.shift(1)
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    return tr.rolling(p).mean()

def calc_vwap(df):
    tp=(df['High']+df['Low']+df['Close'])/3
    tpv=tp*df['Volume']
    return tpv.groupby(df['Date']).cumsum() / df['Volume'].groupby(df['Date']).cumsum()

def summarize(trades, params):
    if not trades:
        return {**params,'trades':0,'win_rate':0,'avg_pnl':0,
                'profit_factor':0,'total_pnl':0,'avg_hold':0}
    df=pd.DataFrame(trades)
    w=df[df['pnl']>0]; lo=df[df['pnl']<=0]
    gp=w['pnl'].sum(); gl=lo['pnl'].abs().sum()
    pf=gp/gl if gl>0 else 9.99
    return {**params,'trades':len(df),
            'win_rate':round(len(w)/len(df)*100,1),
            'avg_pnl':round(df['pnl'].mean(),3),
            'profit_factor':round(pf,2),
            'total_pnl':round(df['pnl'].sum(),2),
            'avg_hold':round(df['hold'].mean(),1)}

def bt_intra(df_raw, p):
    df=df_raw.copy()
    if df.empty or len(df)<30: return summarize([],p)
    df['VWAP']=calc_vwap(df)
    df['RSI']=calc_rsi(df['Close'])
    df['MA5']=df['Close'].rolling(5).mean()
    df['MA20']=df['Close'].rolling(20).mean()
    df['VolMA']=df['Volume'].rolling(10).mean().shift(1)
    df['VR']=df['Volume']/df['VolMA'].replace(0,np.nan)
    df['ATR']=calc_atr(df)
    df.dropna(inplace=True)
    if len(df)<20: return summarize([],p)

    trades=[]; in_pos=False; ep=0; ei=0; tsl=0
    for i in range(1,len(df)):
        cv=df.iloc[i]; pv=df.iloc[i-1]
        if not in_pos:
            cr=p['rl']<=cv['RSI']<=p['rh']
            vr=cv['VR']>=p['vm']
            vw=(cv['Close']>cv['VWAP']) if p['uv'] else True
            ma=(cv['MA5']>cv['MA20'])  if p['um'] else True
            if cr and vr and vw and ma:
                ep=cv['Close']*(1+FEE_RT/2)
                tsl=cv['Close']-p['am']*cv['ATR']
                in_pos=True; ei=i
        else:
            cl=cv['Close']
            ns=cl-p['am']*cv['ATR']; tsl=max(tsl,ns)
            pnl=(cl-ep)/ep*100
            hs=cl<=tsl; ht=pnl>=p['tp']
            htime=(i-ei)>=p['tc']
            hdead=(p['um'] and cv['MA5']<cv['MA20'] and pv['MA5']>=pv['MA20'])
            if hs or ht or htime or hdead:
                xp=cl*(1-FEE_RT/2); net=(xp-ep)/ep*100
                r='sl' if hs else('tp' if ht else('time' if htime else'dead'))
                trades.append({'pnl':net,'hold':i-ei,'reason':r})
                in_pos=False
    return summarize(trades,p)

# ── 그리드 ──────────────────────────────────────────────────────
INTRA_GRID=list(product(
    [(35,65),(40,60),(30,70),(35,70),(40,70)],  # (rl,rh) RSI 범위
    [1.5,2.0,2.5],                               # vm 거래량 배율
    [1.2,1.5,2.0],                               # am ATR 승수
    [0.5,0.7,1.0,1.5],                           # tp% 익절
    [15,25,40],                                   # tc 시간컷오프 봉수
    [True,False],                                 # uv VWAP 사용
    [True,False],                                 # um MA 사용
))
print(f"분봉 그리드 총 {len(INTRA_GRID)}개 조합")

if __name__=='__main__':
    print("="*70)
    print("  분봉 시뮬레이션 백테스트 (일봉 → 가상 5분봉)")
    print(f"  {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("="*70)

    start=(datetime.now()-timedelta(days=365)).strftime('%Y-%m-%d')
    res1=[]; res5=[]

    for code,name in TEST_STOCKS.items():
        print(f"  -> {name}({code}) 일봉 수집 중...")
        df_d=fdr.DataReader(code,start)
        if df_d.empty: print("    [SKIP]"); continue

        # 가상 5분봉 생성
        np.random.seed(42)
        df_sim = daily_to_min_bars(df_d, bars_per_day=78)  # 78개 = 1일치 5분봉
        # 1분봉: 5분봉을 1분 단위로 확장은 불가하므로 5분봉만 사용
        # (= 5분봉 백테스트)
        print(f"    가상 5분봉: {len(df_sim)}개 생성")

        for combo in INTRA_GRID:
            rl_rh,vm,am,tp,tc,uv,um = combo
            p=dict(rl=rl_rh[0],rh=rl_rh[1],vm=vm,am=am,tp=tp,tc=tc,uv=uv,um=um)
            r5=bt_intra(df_sim,p)
            r5['code']=code; r5['name']=name
            res5.append(r5)

        print(f"    완료!")

    grp=['rl','rh','vm','am','tp','tc','uv','um']
    df_r=pd.DataFrame(res5)
    if df_r.empty or 'trades' not in df_r.columns:
        print("결과 없음"); exit()

    df_r2=df_r[df_r['trades']>=5]
    if df_r2.empty:
        print("유효 거래 없음 (>=5)"); df_r2=df_r[df_r['trades']>=3]

    agg=df_r2.groupby(grp).agg(
        trades=('trades','mean'), win_rate=('win_rate','mean'),
        avg_pnl=('avg_pnl','mean'), profit_factor=('profit_factor','mean'),
        total_pnl=('total_pnl','mean')
    ).reset_index().round(2)
    agg.sort_values('profit_factor',ascending=False,inplace=True)
    agg.to_csv('backtest_intraday_sim_result.csv',index=False,encoding='utf-8-sig')

    print("\n[5분봉(시뮬레이션) TOP 10 - Profit Factor 기준]")
    print(agg.head(10).to_string(index=False))

    best=agg.iloc[0]
    print("\n"+"="*70)
    print("  최적 분봉 파라미터")
    print("="*70)
    print(f"  RSI 범위     : {int(best['rl'])} ~ {int(best['rh'])}")
    print(f"  거래량 배율  : {best['vm']}x")
    print(f"  ATR 승수     : {best['am']}x")
    print(f"  익절 목표    : {best['tp']}%")
    print(f"  시간 컷오프  : {int(best['tc'])}봉")
    print(f"  VWAP 조건    : {bool(best['uv'])}")
    print(f"  MA 조건      : {bool(best['um'])}")
    print(f"  평균 승률    : {best['win_rate']}%")
    print(f"  Profit Factor: {best['profit_factor']}")
    print("="*70)
