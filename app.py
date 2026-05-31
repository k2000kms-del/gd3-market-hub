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
    'df_high_density.csv':   '1UQTyfpFD2xuK-fKlq2RqK2MvCqxXaAB3',
    'df_quant_final.csv':    '1eD7HHBnQ_7FYE5ZCpnjMgYcW_rmmAqjP',
    'df_full_market.csv':    '1RA1PkDChDuLpj6YkmTb6uGfS6Nhpleve',
    'df_market_summary.csv': '17F5LJf4UcA0neVw60oRCP2qk7PugRAok',
}

@st.cache_data(ttl=60)  # 60초마다 데이터 갱신
def load_data():
    """구글 드라이브 공개 URL에서 직접 CSV 읽기 (gdown 불필요)"""
    dfs = {}
    for fname, fid in FILE_IDS.items():
        if not fid:
            dfs[fname] = pd.DataFrame()
            continue
        try:
            url = f'https://drive.google.com/uc?export=download&id={fid}'
            dfs[fname] = pd.read_csv(url)
        except Exception as e:
            st.warning(f'{fname} 로드 실패: {e}')
            dfs[fname] = pd.DataFrame()
    return dfs

# ── 데이터 로드 ────────────────────────────────────────────────
with st.spinner('📡 데이터 불러오는 중...'):
    data = load_data()

df_hd      = data['df_high_density.csv']
df_q       = data['df_quant_final.csv']
df_m       = data['df_full_market.csv']
df_summary = data['df_market_summary.csv']

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
        '🔥 거래량 리더(15)',
        '📉 시장 요약 및 수급',
        '📈 코스피/코스닥 수급 현황',
        '🚀 상승률 리더(15)'
    )
)

# [Panel 1] 실시간 수급
if not df_hd.empty and 'Total_Combined_Net' in df_hd.columns:
    df1 = df_hd.sort_values('Total_Combined_Net', ascending=False).head(10).copy()
    df1['Disp'] = df1['ChagesRatio'].apply(lambda x: f"{x:+.2f}%")
    fig.add_trace(go.Treemap(
        labels=df1['Name'], parents=[''] * len(df1),
        values=df1['Total_Combined_Net'].abs() + 1,
        marker=dict(colors=df1['ChagesRatio'], colorscale=kr_scale, cmid=0),
        text=df1['Disp'],
        texttemplate='<b>%{label}</b><br>%{text}',
        hovertemplate='<b>%{label}</b><br>등락률: %{text}<extra></extra>'
    ), row=1, col=1)

# [Panel 2] Quant Buy TOP 10
if not df_q.empty and 'Total_Score' in df_q.columns:
    df2 = df_q.sort_values('Total_Score', ascending=False).head(10).copy()
    fig.add_trace(go.Treemap(
        labels=df2['Name'], parents=[''] * len(df2),
        values=df2['Total_Score'],
        marker=dict(colors=df2['Total_Score'], colorscale='Reds', showscale=False),
        text=df2['Total_Score'].apply(lambda x: f"{x:.1f}점"),
        texttemplate='<b>%{label}</b><br>%{text}',
        hovertemplate='<b>%{label}</b><br>Quant점수: %{text}<extra></extra>'
    ), row=1, col=2)

# [Panel 3] 거래량 리더(15)
if not df_m.empty and 'Volume' in df_m.columns:
    df3 = df_m.sort_values('Volume', ascending=False).head(15).copy()
    fig.add_trace(go.Treemap(
        labels=df3['Name'], parents=[''] * len(df3),
        values=df3['Volume'],
        marker=dict(colors=df3['ChagesRatio'], colorscale=kr_scale, cmid=0),
        text=df3['ChagesRatio'].apply(lambda x: f"{x:+.2f}%"),
        texttemplate='<b>%{label}</b><br>%{text}',
        hovertemplate='<b>%{label}</b><br>등락률: %{text}<extra></extra>'
    ), row=1, col=3)

# [Panel 4] 시장 요약 테이블
if not df_summary.empty:
    def get_color(v):
        try:
            f = float(str(v).replace(',', ''))
            return 'red' if f > 0 else ('blue' if f < 0 else 'white')
        except:
            return 'white'
    fig.add_trace(go.Table(
        header=dict(
            values=list(df_summary.columns),
            fill_color='#2c3e50',
            font=dict(color='white', size=11),
            align='center'
        ),
        cells=dict(
            values=[df_summary[c] for c in df_summary.columns],
            fill_color='#111111',
            font=dict(
                color=['white', 'white',
                       [get_color(x) for x in df_summary['등락률']],
                       'white', 'white', 'white', 'white'],
                size=11
            ),
            align='center'
        )
    ), row=2, col=1)

# [Panel 5] 코스피/코스닥 수급 현황 막대 차트
if not df_summary.empty and '외국인(억)' in df_summary.columns:
    # 코스피·코스닥 행만 추출
    markets = ['코스피', '코스닥']
    df5 = df_summary[df_summary['지수/종목'].isin(markets)].copy()

    def to_num(series):
        return pd.to_numeric(series.astype(str).str.replace(',', ''), errors='coerce').fillna(0)

    investor_cols = {'외국인(억)': '#4e9ff5', '개인(억)': '#ff6b6b', '기관(억)': '#51cf66'}

    for col, color in investor_cols.items():
        vals = to_num(df5[col])
        bar_colors = ['#e74c3c' if v > 0 else '#3498db' for v in vals]
        fig.add_trace(go.Bar(
            name=col.replace('(억)', ''),
            x=df5['지수/종목'].tolist(),
            y=vals.tolist(),
            marker_color=bar_colors,
            text=[f"{v:+,.0f}억" for v in vals],
            textposition='outside',
            marker_line_width=0,
            legendgroup=col,
            showlegend=False
        ), row=2, col=2)

    # 투자자 구분 레이블 추가
    for i, (col, color) in enumerate(investor_cols.items()):
        vals = to_num(df5[col])
        fig.add_trace(go.Bar(
            name=col.replace('(억)', ''),
            x=[None], y=[None],
            marker_color=color,
            showlegend=True,
            legendgroup=col
        ), row=2, col=2)

    fig.update_yaxes(title_text='순매수(억원)', row=2, col=2, zeroline=True,
                     zerolinecolor='rgba(255,255,255,0.3)', zerolinewidth=1)
    fig.update_xaxes(row=2, col=2)
else:
    # 데이터 없을 때 빈 안내 차트
    fig.add_trace(go.Bar(
        x=['코스피', '코스닥'],
        y=[0, 0],
        marker_color='#555555',
        showlegend=False
    ), row=2, col=2)

# [Panel 6] 상승률 리더(15)
if not df_m.empty and 'ChagesRatio' in df_m.columns:
    df6 = df_m.sort_values('ChagesRatio', ascending=False).head(15).copy()
    fig.add_trace(go.Treemap(
        labels=df6['Name'], parents=[''] * len(df6),
        values=df6['ChagesRatio'].abs() + 0.01,
        marker=dict(colors=df6['ChagesRatio'], colorscale=kr_scale, cmid=0),
        text=df6['ChagesRatio'].apply(lambda x: f"{x:+.2f}%"),
        texttemplate='<b>%{label}</b><br>%{text}',
        hovertemplate='<b>%{label}</b><br>등락률: %{text}<extra></extra>'
    ), row=2, col=3)

fig.update_layout(
    height=850,
    template='plotly_dark',
    margin=dict(t=50, l=10, r=10, b=10),
    showlegend=True,
    legend=dict(
        orientation='h',
        x=0.37, y=0.46,
        font=dict(size=10),
        bgcolor='rgba(0,0,0,0)'
    ),
    barmode='group'
)

st.plotly_chart(fig, use_container_width=True)

# 하단 갱신 버튼
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if st.button('🔄 데이터 새로고침', use_container_width=True):
        st.cache_data.clear()
        st.rerun()
