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
        customdata=df1[['Price','Volume','Foreign_Net','Institutional_Net','Code']].values,
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

# [Panel 2] Quant Buy TOP 10
if not df_q.empty and 'Total_Score' in df_q.columns:
    df2 = df_q.sort_values('Total_Score', ascending=False).head(10).copy()

    # 세부 점수 콼럼 (data_collector에서 저장된 경우 사용, 없으면 0)
    for col in ['Score_Momentum','Score_Supply','Score_Volume','Score_Program']:
        if col not in df2.columns:
            df2[col] = 0.0

    # df_full_market에서 현재가/등락률 합치기
    if not df_m.empty and 'Code' in df_m.columns and 'Code' in df2.columns:
        df2 = df2.merge(df_m[['Code','Price','ChagesRatio']], on='Code', how='left')
    else:
        df2['Price'] = 0; df2['ChagesRatio'] = 0.0
    df2[['Price','ChagesRatio']] = df2[['Price','ChagesRatio']].fillna(0)

    def quant_grade(s):
        if s >= 90: return '🔥 강력매수'
        if s >= 80: return '⭐ 매수'
        if s >= 70: return '👀 관심'
        return '🔍 검토'

    df2['Grade'] = df2['Total_Score'].apply(quant_grade)

    fig.add_trace(go.Treemap(
        labels=df2['Name'], parents=[''] * len(df2),
        values=df2['Total_Score'],
        marker=dict(colors=df2['Total_Score'], colorscale='Reds', showscale=False),
        text=df2['Total_Score'].apply(lambda x: f"{x:.1f}점"),
        customdata=df2[[
            'Code','Total_Score','Grade',
            'Score_Momentum','Score_Supply','Score_Volume','Score_Program',
            'Price','ChagesRatio'
        ]].values,
        texttemplate='<b>%{label}</b><br>%{text}',
        hovertemplate=(
            '<b>%{label}</b> (%{customdata[0]})<br>'
            '━━━━━━━━━━━━━━━<br>'
            'Quant 점수: <b>%{customdata[1]:.1f}점</b>  %{customdata[2]}<br>'
            '━━━━━━━━━━━━━━━<br>'
            '📈 가격 모멘틴:  %{customdata[3]:.1f} / 25점<br>'
            '👥 외국인+기관:  %{customdata[4]:.1f} / 35점<br>'
            '📊 거래량 서지:  %{customdata[5]:.1f} / 25점<br>'
            '🤖 프로그램 매수: %{customdata[6]:.1f} / 15점<br>'
            '━━━━━━━━━━━━━━━<br>'
            '현재가: %{customdata[7]:,}원 '
            '(%{customdata[8]:+.2f}%)'
            '<extra></extra>'
        )
    ), row=1, col=2)

# [Panel 3] 거래량 리더(15)
if not df_m.empty and 'Volume' in df_m.columns:
    df3 = df_m.sort_values('Volume', ascending=False).head(15).copy()
    fig.add_trace(go.Treemap(
        labels=df3['Name'], parents=[''] * len(df3),
        values=df3['Volume'],
        marker=dict(colors=df3['ChagesRatio'], colorscale=kr_scale, cmid=0),
        text=df3['ChagesRatio'].apply(lambda x: f"{x:+.2f}%"),
        customdata=df3[['Code','Price','Volume','ChagesRatio']].values,
        texttemplate='<b>%{label}</b><br>%{text}',
        hovertemplate=(
            '<b>%{label}</b> (%{customdata[0]})<br>'
            '현재가: %{customdata[1]:,}원<br>'
            '등락률: %{customdata[3]:+.2f}%<br>'
            '거래량: %{customdata[2]:,}주'
            '<extra></extra>'
        )
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

# [Panel 5] 코스피/코스닥 수급 라인차트 (트레이스 수 동적 추적)
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
        title_text='순매수(억원)', row=2, col=2,
        zeroline=True, zerolinecolor='rgba(255,255,255,0.2)', zerolinewidth=1
    )
else:
    kospi_start = kospi_end = kosdaq_start = kosdaq_end = len(fig.data)
    fig.add_annotation(
        text='📡 수급 데이터 수집 중...',
        x=0.5, y=0.25, xref='paper', yref='paper',
        showarrow=False, font=dict(size=12, color='#888'), align='center'
    )

# [Panel 6] 상승률 리더(15)
if not df_m.empty and 'ChagesRatio' in df_m.columns:
    df6 = df_m.sort_values('ChagesRatio', ascending=False).head(15).copy()
    fig.add_trace(go.Treemap(
        labels=df6['Name'], parents=[''] * len(df6),
        values=df6['ChagesRatio'].abs() + 0.01,
        marker=dict(colors=df6['ChagesRatio'], colorscale=kr_scale, cmid=0),
        text=df6['ChagesRatio'].apply(lambda x: f"{x:+.2f}%"),
        customdata=df6[['Code','Price','Volume','ChagesRatio']].values,
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
    total_n = len(fig.data)  # Panel 6 포함한 전체 트레이스 수

    def make_vis(show_kospi):
        """KOSPI를 보여줄지 KOSDAQ을 보여줄지 관리"""
        vis = []
        for i in range(total_n):
            if kospi_start <= i < kospi_end:
                vis.append(show_kospi)
            elif kosdaq_start <= i < kosdaq_end:
                vis.append(not show_kospi)
            else:
                vis.append(True)   # 다른 패널은 항상 표시
        return vis

    updatemenus = [dict(
        type='buttons',
        direction='right',
        x=0.37, y=0.48,       # Panel 5 좌상단 (페이퍼 좌표)
        xanchor='left',
        yanchor='bottom',
        buttons=[
            dict(
                label='📊 코스피',
                method='update',
                args=[{'visible': make_vis(True)},
                      {'legend.title.text': '코스피 수급'}]
            ),
            dict(
                label='📊 코스닥',
                method='update',
                args=[{'visible': make_vis(False)},
                      {'legend.title.text': '코스닥 수급'}]
            ),
        ],
        bgcolor='#1e2a3a',
        bordercolor='#4e9ff5',
        borderwidth=1,
        font=dict(color='white', size=11),
        active=0,
        pad={'r': 4, 't': 4}
    )]
else:
    updatemenus = []

fig.update_layout(
    height=850,
    template='plotly_dark',
    margin=dict(t=50, l=10, r=10, b=10),
    showlegend=True,
    legend=dict(
        title=dict(text='코스피 수급', font=dict(size=10)),
        orientation='h',
        x=0.37, y=0.46,
        font=dict(size=10),
        bgcolor='rgba(0,0,0,0)'
    ),
    updatemenus=updatemenus,
    hovermode='x unified'   # Panel5 라인차트: 시간축 통합 툰팟
)

st.plotly_chart(fig, use_container_width=True)

# 하단 갱신 버튼
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if st.button('🔄 데이터 새로고침', use_container_width=True):
        st.cache_data.clear()
        st.rerun()
