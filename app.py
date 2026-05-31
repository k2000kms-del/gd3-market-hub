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
    """구글 드라이브 공개 URL에서 직접 CSV 읽기 (gdown 불필요)"""
    dfs = {}
    for fname, fid in FILE_IDS.items():
        if not fid:  # ID 없으면 빈 DataFrame
            dfs[fname] = pd.DataFrame()
            continue
        try:
            url = f'https://drive.google.com/uc?export=download&id={fid}'
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

# [Panel 5] 수급 현황 - 하단 탭으로 이동됨 (안내 텍스트)
fig.add_annotation(
    text='📈 코스피 / 코스닥 수급 툵<br>아래 탭에서 확인',
    x=0.5, y=0.25, xref='paper', yref='paper',
    showarrow=False, font=dict(size=13, color='#aaaaaa'), align='center'
)

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

# ── 코스피 / 코스닥 수급 상세 탭 ────────────────────────────────────────
st.markdown('### 📈 코스피 / 코스닥 수급 흐름 (외국인 · 개인 · 기관)')
tab_k, tab_q = st.tabs(['📊 코스피', '📊 코스닥'])

def draw_supply_tab(market):
    if df_intraday.empty or 'Time' not in df_intraday.columns:
        st.info('📡 수급 데이터를 수집 중입니다. Colab에서 수집기를 실행해 주세요.')
        return

    df_mkt = df_intraday[df_intraday['Market'] == market].copy()
    if df_mkt.empty:
        st.info(f'{market} 데이터가 없습니다.')
        return

    df_mkt = df_mkt.sort_values('Time').reset_index(drop=True)

    def to_n(s):
        return pd.to_numeric(s.astype(str).str.replace(',', ''), errors='coerce').fillna(0)

    cfg = [
        ('Foreign_Net',      '외국인', '#4e9ff5', 2.0),
        ('Individual_Net',   '개인',   '#ff6b6b', 2.0),
        ('Institutional_Net','기관',   '#51cf66', 2.0),
    ]

    fig2 = go.Figure()
    for col, name, color, width in cfg:
        if col in df_mkt.columns:
            fig2.add_trace(go.Scatter(
                x=df_mkt['Time'],
                y=to_n(df_mkt[col]),
                name=name,
                mode='lines',
                line=dict(color=color, width=width)
            ))

    # 0선 명시
    fig2.add_hline(
        y=0,
        line_dash='dash',
        line_color='rgba(255,255,255,0.25)',
        line_width=1
    )

    # 수급 합계 지표 (우측 상단 표시)
    last = df_mkt.iloc[-1]
    for col, name, color, _ in cfg:
        if col in df_mkt.columns:
            val = to_n(df_mkt[col]).iloc[-1]
            sign = '+' if val >= 0 else ''
            fig2.add_annotation(
                x=df_mkt['Time'].iloc[-1],
                y=to_n(df_mkt[col]).iloc[-1],
                text=f'  {name} {sign}{val:.0f}억',
                showarrow=False,
                font=dict(color=color, size=11),
                xanchor='left'
            )

    fig2.update_layout(
        template='plotly_dark',
        height=380,
        margin=dict(t=40, l=10, r=80, b=40),
        yaxis_title='순매수(억원)',
        xaxis_title='시간',
        legend=dict(orientation='h', y=1.12, x=0, font=dict(size=11)),
        hovermode='x unified'
    )
    st.plotly_chart(fig2, use_container_width=True)

with tab_k:
    draw_supply_tab('코스피')

with tab_q:
    draw_supply_tab('코스닥')

# 하단 갱신 버튼
st.markdown('---')
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if st.button('🔄 데이터 새로고침', use_container_width=True):
        st.cache_data.clear()
        st.rerun()
