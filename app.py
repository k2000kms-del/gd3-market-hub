# -*- coding: utf-8 -*-
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

st.set_page_config(
    page_title='GD 3.0 Market Hub',
    page_icon='📊',
    layout='wide',
    initial_sidebar_state='collapsed'
)

# ── 구글 드라이브 파일 ID (공개 파일 - 직접 하드코딩) ────────────
FILE_IDS = {
    'df_high_density.csv':    '1UQTyfpFD2xuK-fKlq2RqK2MvCqxXaAB3',
    'df_quant_final.csv':     '1eD7HHBnQ_7FYE5ZCpnjMgYcW_rmmAqjP',
    'df_full_market.csv':     '1RA1PkDChDuLpj6YkmTb6uGfS6Nhpleve',
    'df_market_summary.csv':  '17F5LJf4UcA0neVw60oRCP2qk7PugRAok',
    'df_supply_intraday.csv': '1sYEK6PsAoH1ybupVbtQKnL289LCwnhvc',
}

@st.cache_data(ttl=60)  # 60초마다 데이터 갱신
def load_data():
    """구글 드라이브 공개 URL에서 직접 CSV 읽기"""
    dfs = {}
    for fname, fid in FILE_IDS.items():
        if not fid:
            dfs[fname] = pd.DataFrame()
            continue
        try:
            url = f'https://drive.google.com/uc?export=download&id={fid}'
            if fname == 'df_market_summary.csv':
                # 인코딩 순차 시도: utf-8 → cp949 → latin-1 (어떤 인코딩이든 로드 성공 시 사용)
                loaded = False
                for enc in ['utf-8', 'cp949', 'euc-kr', 'latin-1']:
                    try:
                        dfs[fname] = pd.read_csv(url, encoding=enc)
                        loaded = True
                        break
                    except Exception:
                        continue
                if not loaded:
                    dfs[fname] = pd.DataFrame()
            else:
                dfs[fname] = pd.read_csv(url)
        except Exception:
            dfs[fname] = pd.DataFrame()
    return dfs

# ── 데이터 로드 ────────────────────────────────────────────────
with st.spinner('📡 데이터 불러오는 중...'):
    data = load_data()

df_hd       = data['df_high_density.csv']
df_q        = data['df_quant_final.csv']
df_m        = data['df_full_market.csv']
df_summary  = data['df_market_summary.csv']
df_intraday = data['df_supply_intraday.csv']

# ── df_full_market 수치 컬럼 전처리 ──────────────────────────
# 실제 컬럼: Code, Name, Market, Close, ChagesRatio, Volume 등
if not df_m.empty:
    for col in ['Close', 'ChagesRatio', 'Volume', 'Amount', 'Marcap']:
        if col in df_m.columns:
            df_m[col] = pd.to_numeric(df_m[col], errors='coerce').fillna(0)

# 모든 데이터프레임의 종목코드(Code) 규격화 (6자리 문자열 패딩)
for df_temp in [df_hd, df_q, df_m, df_summary, df_intraday]:
    if df_temp is not None and not df_temp.empty and 'Code' in df_temp.columns:
        df_temp['Code'] = df_temp['Code'].astype(str).str.split('.').str[0].str.zfill(6)

kr_scale = 'RdBu_r'

# ── 6분할 레이아웃 ────────────────────────────────────────────
fig = make_subplots(
    rows=2, cols=3,
    column_widths=[0.33, 0.33, 0.34],
    row_heights=[0.5, 0.5],
    vertical_spacing=0.08,
    horizontal_spacing=0.05,
    specs=[
        [{'type': 'treemap'}, {'type': 'treemap'}, {'type': 'treemap'}],
        [{'type': 'table'},   {'type': 'xy'},      {'type': 'treemap'}]
    ],
    subplot_titles=(
        '📊 실시간 수급(외/기/프)',
        '🎯 Quant Buy TOP 10',
        '🔥 거래대금 리더(15)',
        '📉 시장 요약 및 수급',
        '📈 코스피/코스닥 수급 현황',
        '🚀 상승률 리더(15)'
    )
)

# [Panel 1] 실시간 수급 (df_high_density 기반)
# 컬럼: Code, Foreign_Net, Institutional_Net, Personal_Net, Program_Net,
#        Volume_Power, Trade_Volume, Trade_Amount, Current_Price,
#        MA5_Disparity, MA20_Disparity, Name, Total_Combined_Net
if not df_hd.empty and 'Total_Combined_Net' in df_hd.columns:
    df1 = df_hd.sort_values('Total_Combined_Net', ascending=False).head(10).copy()
    df1['Code'] = df1['Code'].astype(str)

    # df_full_market에서 ChagesRatio 가져오기 (단, 이미 없으면 가져옴)
    if 'ChagesRatio' not in df1.columns:
        if not df_m.empty and 'Code' in df_m.columns and 'ChagesRatio' in df_m.columns:
            df1 = df1.merge(df_m[['Code', 'ChagesRatio']], on='Code', how='left')
        else:
            df1['ChagesRatio'] = 0.0

    df1['ChagesRatio'] = pd.to_numeric(df1['ChagesRatio'], errors='coerce').fillna(0)

    # 현재가 / 거래량 컬럼 찾기 (Current_Price가 없으면 Close, Trade_Volume이 없으면 Volume 사용)
    cp_col = 'Current_Price' if 'Current_Price' in df1.columns else ('Close' if 'Close' in df1.columns else 'Price')
    tv_col = 'Trade_Volume' if 'Trade_Volume' in df1.columns else ('Volume' if 'Volume' in df1.columns else 'Vol')

    df1['Current_Price_Val'] = pd.to_numeric(df1[cp_col] if cp_col in df1.columns else 0, errors='coerce').fillna(0) if cp_col in df1.columns else 0
    df1['Trade_Volume_Val']  = pd.to_numeric(df1[tv_col] if tv_col in df1.columns else 0, errors='coerce').fillna(0) if tv_col in df1.columns else 0
    df1['Foreign_Net']   = pd.to_numeric(df1['Foreign_Net'], errors='coerce').fillna(0) if 'Foreign_Net' in df1.columns else 0
    df1['Institutional_Net'] = pd.to_numeric(df1['Institutional_Net'], errors='coerce').fillna(0) if 'Institutional_Net' in df1.columns else 0
    df1['Disp'] = df1['ChagesRatio'].apply(lambda x: f"{x:+.2f}%")

    fig.add_trace(go.Treemap(
        labels=df1['Name'], parents=[''] * len(df1),
        values=df1['Total_Combined_Net'].abs() + 1,
        marker=dict(colors=df1['ChagesRatio'], colorscale=kr_scale, cmid=0),
        text=df1['Disp'],
        customdata=df1[['Current_Price_Val', 'Trade_Volume_Val', 'Foreign_Net', 'Institutional_Net', 'Code']].values,
        texttemplate='<b>%{label}</b><br>%{text}',
        hovertemplate=(
            '<b>%{label}</b> (%{customdata[4]})<br>'
            '현재가: %{customdata[0]:,}원<br>'
            '등락률: %{text}<br>'
            '거래량: %{customdata[1]:,}<br>'
            '외국인 순매수: %{customdata[2]:+,}주<br>'
            '기관 순매수: %{customdata[3]:+,}주'
            '<extra></extra>'
        )
    ), row=1, col=1)

# [Panel 2] Quant Buy TOP 10 (df_quant_final 기반)
# 컬럼: Name, Code, Total_Score (세부 점수 없음)
if not df_q.empty and 'Total_Score' in df_q.columns:
    df2 = df_q.sort_values('Total_Score', ascending=False).head(10).copy()
    df2['Code'] = df2['Code'].astype(str).str.split('.').str[0].str.zfill(6)

    # df_full_market에서 현재가/등락률 합치기 (최신 가격 반영 및 merge 충돌 방지)
    if not df_m.empty and 'Code' in df_m.columns:
        df2 = df2.drop(columns=['Close', 'ChagesRatio'], errors='ignore')
        df2 = df2.merge(df_m[['Code', 'Close', 'ChagesRatio']], on='Code', how='left')
    else:
        df2['Close'] = 0
        df2['ChagesRatio'] = 0.0
    df2['Close'] = pd.to_numeric(df2['Close'], errors='coerce').fillna(0) if 'Close' in df2.columns else 0
    df2['ChagesRatio'] = pd.to_numeric(df2['ChagesRatio'], errors='coerce').fillna(0) if 'ChagesRatio' in df2.columns else 0

    # 세부 점수 컬럼 (없으면 0으로 채움)
    for col in ['Score_Momentum', 'Score_Supply', 'Score_Volume', 'Score_MA', 'Score_Candle']:
        if col not in df2.columns:
            df2[col] = 0.0

    def quant_grade(s):
        if s >= 80: return '🔥 강력매수'
        if s >= 65: return '⭐ 매수'
        if s >= 50: return '👀 관심'
        return '🔍 검토'

    df2['Grade'] = df2['Total_Score'].apply(quant_grade)

    fig.add_trace(go.Treemap(
        labels=df2['Name'], parents=[''] * len(df2),
        values=df2['Total_Score'],
        marker=dict(colors=df2['Total_Score'], colorscale='Reds', showscale=False),
        text=df2['Total_Score'].apply(lambda x: f"{x:.1f}점"),
        customdata=df2[[
            'Code', 'Total_Score', 'Grade',
            'Score_Momentum', 'Score_Supply', 'Score_Volume', 'Score_MA', 'Score_Candle',
            'Close', 'ChagesRatio'
        ]].values,
        texttemplate='<b>%{label}</b><br>%{text}',
        hovertemplate=(
            '<b>%{label}</b> (%{customdata[0]})<br>'
            '━━━━━━━━━━━━━━━<br>'
            'Quant 점수: <b>%{customdata[1]:.1f}점</b>  %{customdata[2]}<br>'
            '━━━━━━━━━━━━━━━<br>'
            '📈 가격 모멘텀:  %{customdata[3]:.1f} / 20점<br>'
            '👥 외국인+기관:  %{customdata[4]:.1f} / 30점<br>'
            '📊 거래대금 서지:  %{customdata[5]:.1f} / 20점<br>'
            '🧭 이평선 추세:  %{customdata[6]:.1f} / 15점<br>'
            '🕯️ 캔들 시그널:  %{customdata[7]:.1f} / 15점<br>'
            '━━━━━━━━━━━━━━━<br>'
            '현재가: %{customdata[8]:,}원 '
            '(%{customdata[9]:+.2f}%)'
            '<extra></extra>'
        )
    ), row=1, col=2)

# [Panel 3] 거래대금 리더(15) (df_full_market 기반)
# 컬럼: Name, Code, Amount, Close, ChagesRatio
if not df_m.empty and 'Amount' in df_m.columns:
    df3 = df_m.sort_values('Amount', ascending=False).head(15).copy()
    # 거래대금을 '억원' 단위로 변환
    df3['Amount_100M'] = df3['Amount'] / 100000000
    
    fig.add_trace(go.Treemap(
        labels=df3['Name'], parents=[''] * len(df3),
        values=df3['Amount'],
        marker=dict(colors=df3['ChagesRatio'], colorscale=kr_scale, cmid=0),
        text=df3['ChagesRatio'].apply(lambda x: f"{x:+.2f}%"),
        customdata=df3[['Code', 'Close', 'Amount_100M', 'ChagesRatio']].values,
        texttemplate='<b>%{label}</b><br>%{text}',
        hovertemplate=(
            '<b>%{label}</b> (%{customdata[0]})<br>'
            '현재가: %{customdata[1]:,}원<br>'
            '등락률: %{customdata[3]:+.2f}%<br>'
            '거래대금: %{customdata[2]:,.0f}억원'
            '<extra></extra>'
        )
    ), row=1, col=3)

# [Panel 4] 시장 요약 테이블 (df_market_summary 기반)
if not df_summary.empty:
    def get_color(v):
        try:
            f = float(str(v).replace(',', '').replace('%', '').replace('+', ''))
            return '#ff6b6b' if f > 0 else ('#4e9ff5' if f < 0 else '#cccccc')
        except:
            return '#cccccc'

    # 컬럼명 정리: 인코딩에 상관없이 전체 컬럼을 한글 폴백으로 덮어씌움
    fallback_cols = ['종목/종류', '지수', '등락률', '추이', '외국인(억)', '개인(억)', '기관(억)']
    if len(df_summary.columns) == 3:
        df_summary.columns = fallback_cols
    elif len(df_summary.columns) != 3:
        # 컬럼 수가 다르다면 컬럼명이 깨진 것만 한글로 대체
        def is_broken(s):
            return any(0x1200 <= ord(c) <= 0x137F for c in str(s))
        new_cols = list(df_summary.columns)
        for i, c in enumerate(new_cols):
            if is_broken(c):
                if i < len(fallback_cols):
                    new_cols[i] = fallback_cols[i]
        df_summary.columns = new_cols

    # 행 데이터 값도 깨진 경우 한글로 치환 (CSV 파일 자체 인코딩 오류 방어)
    # 첫 번째 컬럼(종목/종류)의 값이 깨진 문자인 경우 코스피/코스닥 순서로 매핑
    def fix_row_value(val, idx):
        s = str(val)
        # 에티오피아 문자(U+1200~U+137F) 또는 기타 비정상 문자가 포함된 경우
        if any(0x1200 <= ord(c) <= 0x137F for c in s) or any(0x0370 <= ord(c) <= 0x03FF for c in s):
            known = ['코스피', '코스닥', 'USD/KRW']
            return known[idx] if idx < len(known) else val
        return val

    if '종목/종류' in df_summary.columns:
        df_summary['종목/종류'] = [
            fix_row_value(v, i) for i, v in enumerate(df_summary['종목/종류'])
        ]

    # 등락률 컬럼명 자동 탐색
    chg_col = None
    for candidate in ['등락률', 'ChagesRatio', 'ChangeRatio', 'Changes']:
        if candidate in df_summary.columns:
            chg_col = candidate
            break

    color_list = ['#cccccc'] * len(df_summary.columns)
    if chg_col:
        col_idx = list(df_summary.columns).index(chg_col)
        color_list[col_idx] = [get_color(x) for x in df_summary[chg_col]]

    # 행별 배경색 (홀/짝 구분)
    row_fill = ['#1a2332', '#111920'] * (len(df_summary) // 2 + 1)
    row_fill = row_fill[:len(df_summary)]

    fig.add_trace(go.Table(
        columnwidth=[1.5, 1.5, 1.5, 0.8, 1.2, 1.2, 1.2],
        header=dict(
            values=[f'<b>{c}</b>' for c in df_summary.columns],
            fill_color='#1e3a5f',
            line_color='#4e9ff5',
            font=dict(color='#e0e8f0', size=12, family='malgun gothic, nanum gothic, sans-serif'),
            align='center',
            height=32
        ),
        cells=dict(
            values=[df_summary[c] for c in df_summary.columns],
            fill_color=[row_fill] * len(df_summary.columns),
            line_color='rgba(78,159,245,0.2)',
            font=dict(color=color_list, size=12, family='malgun gothic, nanum gothic, sans-serif'),
            align='center',
            height=28
        )
    ), row=2, col=1)

# [Panel 5] 코스피/코스닥 수급 라인차트
p5_has_data = not df_intraday.empty and 'Time' in df_intraday.columns

if p5_has_data:
    def to_num(s):
        return pd.to_numeric(s.astype(str).str.replace(',', ''), errors='coerce').fillna(0)

    col_cfg = [
        ('Foreign_Net',       '외국인', '#4e9ff5'),
        ('Individual_Net',    '개인',   '#ff6b6b'),
        ('Institutional_Net', '기관',   '#51cf66'),
    ]

    # KOSPI 트레이스 (visible=True)
    kospi_start = len(fig.data)
    df_k = df_intraday[df_intraday['Market'] == '코스피'].sort_values('Time')
    for col, name, color in col_cfg:
        if not df_k.empty and col in df_k.columns:
            fig.add_trace(go.Scatter(
                x=df_k['Time'], y=to_num(df_k[col]),
                name=f'코스피 {name}', mode='lines',
                line=dict(color=color, width=2),
                visible=True, showlegend=True,
                hovertemplate=f'<b>{name}</b>: %{{y:+,.0f}}억원<extra>코스피</extra>'
            ), row=2, col=2)
    kospi_end = len(fig.data)

    # KOSDAQ 트레이스 (visible=False)
    kosdaq_start = len(fig.data)
    df_qd = df_intraday[df_intraday['Market'] == '코스닥'].sort_values('Time')
    for col, name, color in col_cfg:
        if not df_qd.empty and col in df_qd.columns:
            fig.add_trace(go.Scatter(
                x=df_qd['Time'], y=to_num(df_qd[col]),
                name=f'코스닥 {name}', mode='lines',
                line=dict(color=color, width=2, dash='dot'),
                visible=False, showlegend=True,
                hovertemplate=f'<b>{name}</b>: %{{y:+,.0f}}억원<extra>코스닥</extra>'
            ), row=2, col=2)
    kosdaq_end = len(fig.data)

    fig.update_yaxes(
        ticksuffix='억',
        zeroline=True, zerolinecolor='rgba(255,255,255,0.3)', zerolinewidth=1,
        gridcolor='rgba(255,255,255,0.05)',
        row=2, col=2
    )
    fig.update_xaxes(
        tickangle=-30,
        row=2, col=2
    )
else:
    kospi_start = kospi_end = kosdaq_start = kosdaq_end = len(fig.data)
    fig.add_annotation(
        text='📡 수급 데이터 수집 중...',
        x=0.5, y=0.25, xref='paper', yref='paper',
        showarrow=False, font=dict(size=12, color='#888'), align='center'
    )

# [Panel 6] 상승률 리더(15) (df_full_market 기반)
# 컬럼: Name, Code, ChagesRatio, Close, Volume
if not df_m.empty and 'ChagesRatio' in df_m.columns:
    df6 = df_m.sort_values('ChagesRatio', ascending=False).head(15).copy()
    fig.add_trace(go.Treemap(
        labels=df6['Name'], parents=[''] * len(df6),
        values=df6['ChagesRatio'].abs() + 0.01,
        marker=dict(colors=df6['ChagesRatio'], colorscale=kr_scale, cmid=0),
        text=df6['ChagesRatio'].apply(lambda x: f"{x:+.2f}%"),
        customdata=df6[['Code', 'Close', 'Volume', 'ChagesRatio']].values,
        texttemplate='<b>%{label}</b><br>%{text}',
        hovertemplate=(
            '<b>%{label}</b> (%{customdata[0]})<br>'
            '현재가: %{customdata[1]:,}원<br>'
            '등락률: <b>%{customdata[3]:+.2f}%</b><br>'
            '거래량: %{customdata[2]:,}주'
            '<extra></extra>'
        )
    ), row=2, col=3)

# updatemenus 생성 (Panel 5 코스피/코스닥 전환 버튼)
if p5_has_data:
    total_n = len(fig.data)

    def make_vis(show_kospi):
        vis = []
        for i in range(total_n):
            if kospi_start <= i < kospi_end:
                vis.append(show_kospi)
            elif kosdaq_start <= i < kosdaq_end:
                vis.append(not show_kospi)
            else:
                vis.append(True)
        return vis

    updatemenus = [dict(
        type='buttons',
        direction='right',
        x=0.34, y=0.56,
        xanchor='left',
        yanchor='top',
        showactive=False,
        buttons=[
            dict(
                label='▶ 코스피',
                method='update',
                args=[{'visible': make_vis(True)},
                      {'legend.title.text': '코스피 수급'}]
            ),
            dict(
                label='▶ 코스닥',
                method='update',
                args=[{'visible': make_vis(False)},
                      {'legend.title.text': '코스닥 수급'}]
            ),
        ],
        bgcolor='#0d1b2a',
        bordercolor='#4e9ff5',
        borderwidth=1,
        font=dict(color='white', size=11),
        active=0,
        pad={'r': 8, 't': 5, 'b': 5, 'l': 8}
    )]
else:
    updatemenus = []

fig.update_layout(
    height=900,
    template='plotly_dark',
    margin=dict(t=60, l=20, r=20, b=20),
    showlegend=True,
    legend=dict(
        title=dict(text='수급 구분', font=dict(size=10, color='#aabbcc')),
        orientation='h',
        x=0.34, y=0.40,
        xanchor='left',
        yanchor='top',
        font=dict(size=10),
        bgcolor='rgba(0,0,0,0)',
        tracegroupgap=0
    ),
    updatemenus=updatemenus,
    hovermode='x unified',
    font=dict(family='malgun gothic, nanum gothic, sans-serif')
)

st.plotly_chart(fig, use_container_width=True)

# 하단 갱신 버튼
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if st.button('🔄 데이터 새로고침', use_container_width=True):
        st.cache_data.clear()
        st.rerun()
