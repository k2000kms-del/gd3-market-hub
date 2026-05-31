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
        [{'type': 'table'},   {'type': 'treemap'}, {'type': 'treemap'}]
    ],
    subplot_titles=(
        '📊 실시간 수급(외/기/프)',
        '🎯 Quant Buy TOP 10',
        '🔥 거래량 리더(15)',
        '📉 시장 요약 및 수급',
        '🏗️ 섹터 상태',
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

# [Panel 5] 섹터 상태
if not df_m.empty and 'Sector' in df_m.columns:
    df5 = df_m.groupby('Sector').agg(
        Avg_Change=('ChagesRatio', 'mean'),
        Count=('Name', 'count')
    ).reset_index()
    fig.add_trace(go.Treemap(
        labels=df5['Sector'], parents=[''] * len(df5),
        values=df5['Count'],
        marker=dict(colors=df5['Avg_Change'], colorscale=kr_scale, cmid=0),
        text=df5['Avg_Change'].apply(lambda x: f"{x:+.2f}%"),
        texttemplate='<b>%{label}</b><br>%{text}',
        hovertemplate='<b>%{label}</b><br>평균등락률: %{text}<extra></extra>'
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
    showlegend=False
)

st.plotly_chart(fig, use_container_width=True)

# 하단 갱신 버튼
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if st.button('🔄 데이터 새로고침', use_container_width=True):
        st.cache_data.clear()
        st.rerun()
