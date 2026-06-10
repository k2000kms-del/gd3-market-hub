# -*- coding: utf-8 -*-
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import FinanceDataReader as fdr

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

@st.cache_data(ttl=300)  # 5분 캐시 (일봉 데이터는 자주 바뀌지 않음)
def get_stock_history(code: str):
    """종목 일봉 데이터 조회 (90일)"""
    try:
        start = (pd.Timestamp.now() - pd.Timedelta(days=120)).strftime('%Y-%m-%d')
        df = fdr.DataReader(code, start)
        return df if not df.empty else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


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

# ── 실시간 시세 반영 (FinanceDataReader) ───────────────────────
if df_m is not None and not df_m.empty:
    with st.sidebar.status("🔄 실시간 시세 및 지수 반영 중...", expanded=False) as status:
        try:
            # 1. 코스피 / 코스닥 실시간 시세 조회
            st.write("📈 코스피/코스닥 전체 시세 조회 중...")
            df_ks_live = fdr.StockListing('KOSPI')
            df_kq_live = fdr.StockListing('KOSDAQ')
            
            if not df_ks_live.empty or not df_kq_live.empty:
                df_live = pd.concat([df_ks_live, df_kq_live], ignore_index=True)
                
                # 필요한 컬럼만 추출 및 이름 통일 (Name 추가)
                df_live = df_live[['Code', 'Name', 'Close', 'ChagesRatio', 'Volume', 'Amount']].copy()
                df_live['Code'] = df_live['Code'].astype(str).str.zfill(6)
                
                # 세션 스테이트에 전체 상장 종목 목록 백업 (검색용)
                st.session_state['df_live_all'] = df_live
                
                # df_m의 기존 가격 관련 컬럼 드롭 후 머지 (Name 제외)
                df_m_base = df_m.drop(columns=['Close', 'ChagesRatio', 'Volume', 'Amount'], errors='ignore')
                df_m = df_m_base.merge(df_live.drop(columns=['Name'], errors='ignore'), on='Code', how='left')
                
                # 결측치 채우기
                for col in ['Close', 'ChagesRatio', 'Volume', 'Amount']:
                    if col in df_m.columns:
                        df_m[col] = pd.to_numeric(df_m[col], errors='coerce').fillna(0)
                
                st.write("✅ 전체 시장 시세 반영 완료")
            else:
                st.write("⚠️ 실시간 시세 데이터를 가져오지 못했습니다.")
        except Exception as e:
            st.write(f"❌ 실시간 시세 반영 실패: {e}")
            
        try:
            # 2. 실시간 지수 및 환율 반영
            if df_summary is not None and not df_summary.empty and '종목/종류' in df_summary.columns:
                st.write("📊 주요 지수 및 환율 조회 중...")
                start_date = (pd.Timestamp.now() - pd.Timedelta(days=7)).strftime('%Y-%m-%d')
                ks_df = fdr.DataReader('KS11', start_date)
                kq_df = fdr.DataReader('KQ11', start_date)
                usd_df = fdr.DataReader('USD/KRW', start_date)
                
                for idx, row in df_summary.iterrows():
                    name = str(row['종목/종류'])
                    if '코스피' in name and not ks_df.empty:
                        close_val = ks_df['Close'].iloc[-1]
                        chg_val = ks_df['Change'].iloc[-1] * 100
                        df_summary.at[idx, '지수'] = f"{close_val:,.2f}"
                        df_summary.at[idx, '등락률'] = f"{chg_val:+.2f}%"
                        df_summary.at[idx, '추이'] = '📈' if chg_val > 0 else ('📉' if chg_val < 0 else '➖')
                    elif '코스닥' in name and not kq_df.empty:
                        close_val = kq_df['Close'].iloc[-1]
                        chg_val = kq_df['Change'].iloc[-1] * 100
                        df_summary.at[idx, '지수'] = f"{close_val:,.2f}"
                        df_summary.at[idx, '등락률'] = f"{chg_val:+.2f}%"
                        df_summary.at[idx, '추이'] = '📈' if chg_val > 0 else ('📉' if chg_val < 0 else '➖')
                    elif ('USD/KRW' in name or '환율' in name) and not usd_df.empty:
                        close_val = usd_df['Close'].iloc[-1]
                        chg_val = usd_df['Change'].iloc[-1] * 100
                        df_summary.at[idx, '지수'] = f"{close_val:,.2f}"
                        df_summary.at[idx, '등락률'] = f"{chg_val:+.2f}%"
                        df_summary.at[idx, '추이'] = '📈' if chg_val > 0 else ('📉' if chg_val < 0 else '➖')
                st.write("✅ 지수 및 환율 반영 완료")
        except Exception as e:
            st.write(f"❌ 지수 및 환율 반영 실패: {e}")
        
        status.update(label="⚡ 실시간 시세 반영 완료", state="complete")

# ── 세션 스테이트 초기화 (종목 클릭 차트용) ────────────────────
if 'sel_code' not in st.session_state:
    st.session_state.sel_code = None
if 'sel_name' not in st.session_state:
    st.session_state.sel_name = None
if 'chart_key_index' not in st.session_state:
    st.session_state.chart_key_index = 0


# ── 사이드바 정렬 옵션 ──
st.sidebar.title("🎛️ 대시보드 설정")
st.sidebar.markdown("### 🎯 Quant Buy TOP 10")
q_sort_by = st.sidebar.radio(
    "정렬 기준 선택",
    ["Quant 점수 순", "거래대금 순"],
    index=0,
    help="Quant Buy TOP 10 종목을 정렬하는 기준을 선택합니다."
)

st.sidebar.markdown('---')
st.sidebar.markdown('### 🔍 종목 검색')
st.sidebar.caption('종목명 또는 코드로 검색하면 대시보드 아래에 일봉 차트가 표시됩니다.')
_search_q = st.sidebar.text_input(
    '종목명 / 코드',
    placeholder='예: 삼성전자, 005930',
    key='sidebar_search',
    label_visibility='collapsed'
)
if _search_q:
    _sq = _search_q.strip()
    # 전체 종목(df_live_all) 검색 시도, 없으면 df_m에서 백업 검색
    _search_pool = st.session_state.get('df_live_all', pd.DataFrame())
    if _search_pool.empty:
        _search_pool = df_m
        
    if not _search_pool.empty and 'Name' in _search_pool.columns:
        _mask = (
            _search_pool['Name'].str.contains(_sq, na=False, case=False) |
            _search_pool['Code'].astype(str).str.contains(_sq, na=False)
        )
        _results = _search_pool[_mask].head(8)
        if _results.empty:
            st.sidebar.caption('⚠️ 검색 결과가 없습니다.')
        for _, _r in _results.iterrows():
            _chg = float(_r.get('ChagesRatio', 0))
            # FDR 전체 종목의 ChagesRatio는 소수점 비율(0.01 = 1%)일 수 있으므로 보정
            if abs(_chg) < 0.1 and _chg != 0:
                _chg_str = f"{_chg * 100:+.2f}%"
            else:
                _chg_str = f"{_chg:+.2f}%"
            _btn_label = f"{_r['Name']}  {_chg_str}"
            if st.sidebar.button(_btn_label, key=f"sb_{_r['Code']}", use_container_width=True):
                st.session_state.sel_code = str(_r['Code']).zfill(6)
                st.session_state.sel_name = str(_r['Name'])
                st.rerun()


kr_scale = 'RdBu_r'

# ── 클릭 이벤트 공통 핸들러 함수 ─────────────────────────────
def handle_chart_click(event_data):
    if event_data and hasattr(event_data, 'selection') and event_data.selection and event_data.selection.points:
        pt = event_data.selection.points[0]
        # Treemap은 label, Bar 차트는 y에 레이블이 얹혀 리턴됨
        clicked_name = pt.get('label', '') or pt.get('y', '')
        cd = pt.get('customdata', [])
        
        found_code = None
        if len(cd) > 0:
            for val in cd:
                v_str = str(val).split('.')[0].zfill(6)
                if v_str.isdigit() and len(v_str) == 6:
                    found_code = v_str
                    break
        if not found_code and clicked_name and not df_m.empty:
            match = df_m[df_m['Name'] == clicked_name]
            if not match.empty:
                found_code = str(match.iloc[0]['Code']).zfill(6)
        if found_code:
            st.session_state.sel_code = found_code
            st.session_state.sel_name = clicked_name or found_code
            st.rerun()

# ── 개별 차트 6분할 레이아웃 (st.columns 분리) ───────────────
st.markdown("### 📊 실시간 시장 종합 대시보드")
st.caption("차트 내부의 막대(종목)를 클릭하면, 아래에서 즉시 해당 종목의 일봉 차트를 볼 수 있습니다.")

row1_col1, row1_col2, row1_col3 = st.columns(3)
row2_col1, row2_col2, row2_col3 = st.columns(3)

# ── [Panel 1] 실시간 수급 (Treemap) ─────────────────────────
with row1_col1:
    st.markdown("##### 📊 실시간 수급 (외/기/프)")
    fig_p1 = go.Figure()
    if not df_hd.empty and 'Total_Combined_Net' in df_hd.columns:
        df1 = df_hd.sort_values('Total_Combined_Net', ascending=False).head(10).copy()
        df1['Code'] = df1['Code'].astype(str)
        if 'ChagesRatio' not in df1.columns:
            if not df_m.empty and 'Code' in df_m.columns and 'ChagesRatio' in df_m.columns:
                df1 = df1.merge(df_m[['Code', 'ChagesRatio']], on='Code', how='left')
            else:
                df1['ChagesRatio'] = 0.0
        df1['ChagesRatio'] = pd.to_numeric(df1['ChagesRatio'], errors='coerce').fillna(0)
        cp_col = 'Current_Price' if 'Current_Price' in df1.columns else ('Close' if 'Close' in df1.columns else 'Price')
        tv_col = 'Trade_Volume' if 'Trade_Volume' in df1.columns else ('Volume' if 'Volume' in df1.columns else 'Vol')
        df1['Current_Price_Val'] = pd.to_numeric(df1[cp_col], errors='coerce').fillna(0) if cp_col in df1.columns else 0
        df1['Trade_Volume_Val']  = pd.to_numeric(df1[tv_col], errors='coerce').fillna(0) if tv_col in df1.columns else 0
        df1['Foreign_Net']   = pd.to_numeric(df1['Foreign_Net'], errors='coerce').fillna(0) if 'Foreign_Net' in df1.columns else 0
        df1['Institutional_Net'] = pd.to_numeric(df1['Institutional_Net'], errors='coerce').fillna(0) if 'Institutional_Net' in df1.columns else 0
        df1['Disp'] = df1['ChagesRatio'].apply(lambda x: f"{x:+.2f}%")
        
        fig_p1.add_trace(go.Treemap(
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
        ))
    fig_p1.update_layout(
        height=320,
        template='plotly_dark',
        margin=dict(t=10, b=10, l=10, r=10),
        clickmode='event+select',
        font=dict(family='malgun gothic, nanum gothic, sans-serif')
    )
    ev_p1 = st.plotly_chart(fig_p1, use_container_width=True, on_select='rerun', selection_mode=['points'], key=f"p1_chart_{st.session_state.chart_key_index}")
    handle_chart_click(ev_p1)

# ── [Panel 2] Quant Buy TOP 10 (Horizontal Bar) ─────────────
with row1_col2:
    st.markdown(f"##### 🎯 Quant Buy TOP 10 ({q_sort_by})")
    fig_p2 = go.Figure()
    if not df_q.empty and 'Total_Score' in df_q.columns:
        df2 = df_q.copy()
        df2['Code'] = df2['Code'].astype(str).str.split('.').str[0].str.zfill(6)
        if not df_m.empty and 'Code' in df_m.columns:
            df2 = df2.drop(columns=['Close', 'ChagesRatio', 'Amount'], errors='ignore')
            df2 = df2.merge(df_m[['Code', 'Close', 'ChagesRatio', 'Amount']], on='Code', how='left')
        else:
            df2['Close'] = 0
            df2['ChagesRatio'] = 0.0
            df2['Amount'] = 0.0
        df2['Close'] = pd.to_numeric(df2['Close'], errors='coerce').fillna(0)
        df2['ChagesRatio'] = pd.to_numeric(df2['ChagesRatio'], errors='coerce').fillna(0)
        df2['Amount'] = pd.to_numeric(df2['Amount'], errors='coerce').fillna(0)

        if q_sort_by == "거래대금 순" and 'Amount' in df2.columns:
            df2 = df2.sort_values('Amount', ascending=True).tail(10).copy()
            x_val = df2['Amount'] / 1e8
            hover_label = '거래대금: %{x:,.1f}억원'
            text_labels = df2['Amount'].apply(lambda x: f" {x/1e8:,.0f}억")
        else:
            df2 = df2.sort_values('Total_Score', ascending=True).tail(10).copy()
            x_val = df2['Total_Score']
            hover_label = 'Quant 점수: %{x:.1f}점'
            text_labels = df2['Total_Score'].apply(lambda x: f" {x:.1f}점")

        fig_p2.add_trace(go.Bar(
            y=df2['Name'],
            x=x_val,
            orientation='h',
            marker=dict(
                colorscale='Reds',
                color=df2['Total_Score'],
                showscale=False,
                line=dict(color='rgba(255,255,255,0.1)', width=1)
            ),
            text=text_labels,
            textposition='outside',
            customdata=df2[['Code', 'Close', 'ChagesRatio', 'Total_Score']].values,
            hovertemplate=(
                '<b>%{y}</b> (%{customdata[0]})<br>'
                '━━━━━━━━━━━━━━━<br>'
                + hover_label + '<br>'
                '현재가: %{customdata[1]:,}원 (%{customdata[2]:+.2f}%)<br>'
                'Quant 종합 점수: %{customdata[3]:.1f}점'
                '<extra></extra>'
            )
        ))
    fig_p2.update_layout(
        height=320,
        template='plotly_dark',
        margin=dict(t=10, b=10, l=10, r=30),
        clickmode='event+select',
        font=dict(family='malgun gothic, nanum gothic, sans-serif')
    )
    ev_p2 = st.plotly_chart(fig_p2, use_container_width=True, on_select='rerun', selection_mode=['points'], key=f"p2_chart_{st.session_state.chart_key_index}")
    handle_chart_click(ev_p2)

# ── [Panel 3] 거래대금 리더 (Horizontal Bar) ─────────────────
with row1_col3:
    st.markdown("##### 🔥 거래대금 리더 (12)")
    fig_p3 = go.Figure()
    if not df_m.empty and 'Amount' in df_m.columns:
        df3 = df_m.sort_values('Amount', ascending=True).tail(12).copy()
        df3['Amount_100M'] = df3['Amount'] / 100000000
        
        fig_p3.add_trace(go.Bar(
            y=df3['Name'],
            x=df3['Amount_100M'],
            orientation='h',
            marker=dict(
                colorscale=kr_scale,
                color=df3['ChagesRatio'],
                cmid=0,
                showscale=False,
                line=dict(color='rgba(255,255,255,0.1)', width=1)
            ),
            text=df3['Amount_100M'].apply(lambda x: f" {x:,.0f}억"),
            textposition='outside',
            customdata=df3[['Code', 'Close', 'ChagesRatio']].values,
            hovertemplate=(
                '<b>%{y}</b> (%{customdata[0]})<br>'
                '거래대금: %{x:,.0f}억원<br>'
                '현재가: %{customdata[1]:,}원 (%{customdata[2]:+.2f}%)'
                '<extra></extra>'
            )
        ))
    fig_p3.update_layout(
        height=320,
        template='plotly_dark',
        margin=dict(t=10, b=10, l=10, r=30),
        clickmode='event+select',
        font=dict(family='malgun gothic, nanum gothic, sans-serif')
    )
    ev_p3 = st.plotly_chart(fig_p3, use_container_width=True, on_select='rerun', selection_mode=['points'], key=f"p3_chart_{st.session_state.chart_key_index}")
    handle_chart_click(ev_p3)

# ── [Panel 4] 시장 요약 테이블 ──────────────────────────────
with row2_col1:
    st.markdown("##### 📉 시장 요약")
    fig_p4 = go.Figure()
    if not df_summary.empty:
        def get_color(v):
            try:
                f = float(str(v).replace(',', '').replace('%', '').replace('+', ''))
                return '#ff6b6b' if f > 0 else ('#4e9ff5' if f < 0 else '#cccccc')
            except:
                return '#cccccc'
        fallback_cols = ['종목/종류', '지수', '등락률', '추이', '외국인(억)', '개인(억)', '기관(억)']
        if len(df_summary.columns) == 3:
            df_summary.columns = fallback_cols
        elif len(df_summary.columns) != 3:
            def is_broken(s):
                return any(0x1200 <= ord(c) <= 0x137F for c in str(s))
            new_cols = list(df_summary.columns)
            for i, c in enumerate(new_cols):
                if is_broken(c):
                    if i < len(fallback_cols):
                        new_cols[i] = fallback_cols[i]
            df_summary.columns = new_cols

        def fix_row_value(val, idx):
            s = str(val)
            if any(0x1200 <= ord(c) <= 0x137F for c in s) or any(0x0370 <= ord(c) <= 0x03FF for c in s):
                known = ['코스피', '코스닥', 'USD/KRW']
                return known[idx] if idx < len(known) else val
            return val

        if '종목/종류' in df_summary.columns:
            df_summary['종목/종류'] = [
                fix_row_value(v, i) for i, v in enumerate(df_summary['종목/종류'])
            ]

        chg_col = None
        for candidate in ['등락률', 'ChagesRatio', 'ChangeRatio', 'Changes']:
            if candidate in df_summary.columns:
                chg_col = candidate
                break

        color_list = ['#cccccc'] * len(df_summary.columns)
        if chg_col:
            col_idx = list(df_summary.columns).index(chg_col)
            color_list[col_idx] = [get_color(x) for x in df_summary[chg_col]]

        row_fill = ['#1a2332', '#111920'] * (len(df_summary) // 2 + 1)
        row_fill = row_fill[:len(df_summary)]

        fig_p4.add_trace(go.Table(
            columnwidth=[1.5, 1.5, 1.5, 0.8, 1.2, 1.2, 1.2],
            header=dict(
                values=[f'<b>{c}</b>' for c in df_summary.columns],
                fill_color='#1e3a5f',
                line_color='#4e9ff5',
                font=dict(color='#e0e8f0', size=11, family='malgun gothic, nanum gothic, sans-serif'),
                align='center',
                height=30
            ),
            cells=dict(
                values=[df_summary[c] for c in df_summary.columns],
                fill_color=[row_fill] * len(df_summary.columns),
                line_color='rgba(78,159,245,0.2)',
                font=dict(color=color_list, size=11, family='malgun gothic, nanum gothic, sans-serif'),
                align='center',
                height=26
            )
        ))
    fig_p4.update_layout(
        height=320,
        template='plotly_dark',
        margin=dict(t=10, b=10, l=10, r=10)
    )
    st.plotly_chart(fig_p4, use_container_width=True)

# ── [Panel 5] 코스피/코스닥 수급 (Line) ───────────────────────
with row2_col2:
    st.markdown("##### 📈 수급 현황 (일중 추이)")
    p5_has_data = not df_intraday.empty and 'Time' in df_intraday.columns
    if p5_has_data:
        # updatemenus 버튼 대신 Streamlit의 radio 토글을 차트 상단에 깔끔하게 배치
        market_tab = st.radio("수급 구분", ["코스피 수급", "코스닥 수급"], horizontal=True, label_visibility="collapsed", key="p5_market_tab")
        target_market = '코스피' if market_tab == "코스피 수급" else '코스닥'
        df_line = df_intraday[df_intraday['Market'] == target_market].sort_values('Time')
        
        fig_p5 = go.Figure()
        def to_num(s):
            return pd.to_numeric(s.astype(str).str.replace(',', ''), errors='coerce').fillna(0)

        col_cfg = [
            ('Foreign_Net',       '외국인', '#4e9ff5'),
            ('Individual_Net',    '개인',   '#ff6b6b'),
            ('Institutional_Net', '기관',   '#51cf66'),
        ]

        for col, name, color in col_cfg:
            if not df_line.empty and col in df_line.columns:
                fig_p5.add_trace(go.Scatter(
                    x=df_line['Time'], y=to_num(df_line[col]),
                    name=name, mode='lines',
                    line=dict(color=color, width=2),
                    hovertemplate=f'<b>{name}</b>: %{{y:+,.0f}}억원'
                ))
    else:
        fig_p5 = go.Figure()
        fig_p5.add_annotation(
            text='📡 수급 데이터 수집 중...',
            x=0.5, y=0.5, showarrow=False, font=dict(size=12, color='#888')
        )
    fig_p5.update_layout(
        height=265,  # Radio 높이 고려한 높이 보정
        template='plotly_dark',
        margin=dict(t=10, b=10, l=10, r=10),
        hovermode='x unified',
        font=dict(family='malgun gothic, nanum gothic, sans-serif')
    )
    st.plotly_chart(fig_p5, use_container_width=True)

# ── [Panel 6] 상승률 리더 (Horizontal Bar) ───────────────────
with row2_col3:
    st.markdown("##### 🚀 상승률 리더 (12)")
    fig_p6 = go.Figure()
    if not df_m.empty and 'ChagesRatio' in df_m.columns:
        df6 = df_m.sort_values('ChagesRatio', ascending=True).tail(12).copy()
        
        fig_p6.add_trace(go.Bar(
            y=df6['Name'],
            x=df6['ChagesRatio'],
            orientation='h',
            marker=dict(
                colorscale=kr_scale,
                color=df6['ChagesRatio'],
                cmid=0,
                showscale=False,
                line=dict(color='rgba(255,255,255,0.1)', width=1)
            ),
            text=df6['ChagesRatio'].apply(lambda x: f" {x:+.2f}%"),
            textposition='outside',
            customdata=df6[['Code', 'Close', 'Volume']].values,
            hovertemplate=(
                '<b>%{y}</b> (%{customdata[0]})<br>'
                '등락률: <b>%{x:+.2f}%</b><br>'
                '현재가: %{customdata[1]:,}원<br>'
                '거래량: %{customdata[2]:,}주'
                '<extra></extra>'
            )
        ))
    fig_p6.update_layout(
        height=320,
        template='plotly_dark',
        margin=dict(t=10, b=10, l=10, r=30),
        clickmode='event+select',
        font=dict(family='malgun gothic, nanum gothic, sans-serif')
    )
    ev_p6 = st.plotly_chart(fig_p6, use_container_width=True, on_select='rerun', selection_mode=['points'], key=f"p6_chart_{st.session_state.chart_key_index}")
    handle_chart_click(ev_p6)



# ── 대시보드 내 종목 선택 버튼 탭 ─────────────────────────────
st.markdown('#### 📈 종목 선택 → 일봉 차트 조회')
st.caption('아래 종목 버튼을 클릭하면 일봉 차트가 표시됩니다. 막대스: 퀌눁 점수 / 거래대금 / 수급')

_tab1, _tab2, _tab3 = st.tabs(['🎯 Quant TOP 10', '🔥 거래대금 TOP 10', '📡 수급 TOP 10'])

with _tab1:
    if not df_q.empty and 'Name' in df_q.columns:
        _sorted_q = df_q.sort_values('Total_Score', ascending=False).head(10)
        _cols = st.columns(5)
        for _i, (_, _r) in enumerate(_sorted_q.iterrows()):
            _chg = float(_r.get('ChagesRatio', 0))
            _score = float(_r.get('Total_Score', 0))
            _color = '🔴' if _chg >= 0 else '🔵'
            if _cols[_i % 5].button(
                f"{_color} {_r['Name']}\n{_score:.0f}점",
                key=f'btn_q_{_r["Code"]}',
                use_container_width=True
            ):
                st.session_state.sel_code = str(_r['Code']).zfill(6)
                st.session_state.sel_name = str(_r['Name'])
                st.rerun()

with _tab2:
    if not df_m.empty and 'Amount' in df_m.columns:
        _sorted_v = df_m.sort_values('Amount', ascending=False).head(10)
        _cols = st.columns(5)
        for _i, (_, _r) in enumerate(_sorted_v.iterrows()):
            _chg = float(_r.get('ChagesRatio', 0))
            _amt = float(_r.get('Amount', 0)) / 1e8
            _color = '🔴' if _chg >= 0 else '🔵'
            if _cols[_i % 5].button(
                f"{_color} {_r['Name']}\n{_amt:,.0f}억",
                key=f'btn_v_{_r["Code"]}',
                use_container_width=True
            ):
                st.session_state.sel_code = str(_r['Code']).zfill(6)
                st.session_state.sel_name = str(_r['Name'])
                st.rerun()

with _tab3:
    if not df_hd.empty and 'Total_Combined_Net' in df_hd.columns:
        _sorted_s = df_hd.sort_values('Total_Combined_Net', ascending=False).head(10)
        _cols = st.columns(5)
        for _i, (_, _r) in enumerate(_sorted_s.iterrows()):
            _chg = float(_r.get('ChagesRatio', 0)) if 'ChagesRatio' in _r else 0
            _net = float(_r.get('Total_Combined_Net', 0))
            _color = '🔴' if _chg >= 0 else '🔵'
            if _cols[_i % 5].button(
                f"{_color} {_r['Name']}\n{'+' if _net>=0 else ''}{_net:,.0f}주",
                key=f'btn_s_{_r["Code"]}',
                use_container_width=True
            ):
                st.session_state.sel_code = str(_r['Code']).zfill(6)
                st.session_state.sel_name = str(_r['Name'])
                st.rerun()

st.divider()

# ── 종목 일봉 차트 (선택 시 표시) ─────────────────────────────
if st.session_state.sel_code:
    code_disp = st.session_state.sel_code
    name_disp = st.session_state.sel_name or code_disp

    col_title, col_close = st.columns([6, 1])
    with col_title:
        st.markdown(f"### 📈 {name_disp} ({code_disp}) &nbsp; 일봉 차트")
    with col_close:
        if st.button('✕ 닫기', key='close_chart'):
            st.session_state.sel_code = None
            st.session_state.sel_name = None
            # 차트의 selection 상태를 완전히 리셋하기 위해 key 값 증가
            st.session_state.chart_key_index += 1
            st.rerun()

    with st.spinner(f'📡 {name_disp} 일봉 데이터 조회 중...'):
        df_candle = get_stock_history(code_disp)

    if df_candle.empty:
        st.warning('⚠️ 차트 데이터를 불러올 수 없습니다.')
    else:
        # MA 계산
        df_candle['MA5']  = df_candle['Close'].rolling(5).mean()
        df_candle['MA20'] = df_candle['Close'].rolling(20).mean()
        df_candle = df_candle.tail(90)  # 최근 90 거래일만 표시

        # 당일 등락률 계산
        if len(df_candle) >= 2:
            prev_close = df_candle['Close'].iloc[-2]
            last_close = df_candle['Close'].iloc[-1]
            daily_chg = (last_close - prev_close) / prev_close * 100 if prev_close > 0 else 0
            chg_color = '#ff6b6b' if daily_chg >= 0 else '#4e9ff5'
            chg_str   = f'{daily_chg:+.2f}%'
        else:
            last_close = df_candle['Close'].iloc[-1]
            chg_str = ''
            chg_color = '#cccccc'

        # 지표 요약 (상단 메트릭)
        mc1, mc2, mc3, mc4, mc5 = st.columns(5)
        mc1.metric('현재가', f'{int(last_close):,}원', chg_str)
        mc2.metric('52주 최고', f"{int(df_candle['High'].max()):,}원")
        mc3.metric('52주 최저', f"{int(df_candle['Low'].min()):,}원")
        mc4.metric('MA5', f"{int(df_candle['MA5'].iloc[-1]):,}원" if pd.notna(df_candle['MA5'].iloc[-1]) else '-')
        mc5.metric('MA20', f"{int(df_candle['MA20'].iloc[-1]):,}원" if pd.notna(df_candle['MA20'].iloc[-1]) else '-')

        # 캔들 차트 생성
        fig_c = make_subplots(
            rows=2, cols=1,
            row_heights=[0.72, 0.28],
            vertical_spacing=0.03,
            shared_xaxes=True
        )

        # 캔들스틱 (한국식: 상승=빨강, 하락=파랑)
        fig_c.add_trace(go.Candlestick(
            x=df_candle.index,
            open=df_candle['Open'], high=df_candle['High'],
            low=df_candle['Low'],   close=df_candle['Close'],
            increasing=dict(line=dict(color='#ff6b6b'), fillcolor='#ff6b6b'),
            decreasing=dict(line=dict(color='#4e9ff5'), fillcolor='#4e9ff5'),
            name='캔들', showlegend=False
        ), row=1, col=1)

        # MA5
        fig_c.add_trace(go.Scatter(
            x=df_candle.index, y=df_candle['MA5'],
            name='MA5', mode='lines',
            line=dict(color='#ffd43b', width=1.5)
        ), row=1, col=1)

        # MA20
        fig_c.add_trace(go.Scatter(
            x=df_candle.index, y=df_candle['MA20'],
            name='MA20', mode='lines',
            line=dict(color='#ff922b', width=1.5)
        ), row=1, col=1)

        # 거래량 막대 (색상: 상승일=빨강, 하락일=파랑)
        vol_colors = [
            '#ff6b6b' if c >= o else '#4e9ff5'
            for c, o in zip(df_candle['Close'], df_candle['Open'])
        ]
        fig_c.add_trace(go.Bar(
            x=df_candle.index, y=df_candle['Volume'],
            name='거래량', marker_color=vol_colors,
            showlegend=False, opacity=0.8
        ), row=2, col=1)

        fig_c.update_layout(
            template='plotly_dark',
            height=480,
            margin=dict(t=20, l=10, r=10, b=10),
            xaxis_rangeslider_visible=False,
            legend=dict(orientation='h', x=0, y=1.02, font=dict(size=11)),
            font=dict(family='malgun gothic, nanum gothic, sans-serif'),
            plot_bgcolor='#0d1b2a',
            paper_bgcolor='#0d1b2a',
        )
        fig_c.update_yaxes(tickformat=',d', gridcolor='rgba(255,255,255,0.06)', row=1, col=1)
        fig_c.update_yaxes(tickformat=',d', gridcolor='rgba(255,255,255,0.06)', row=2, col=1)
        fig_c.update_xaxes(gridcolor='rgba(255,255,255,0.04)', showticklabels=False, row=1, col=1)
        fig_c.update_xaxes(gridcolor='rgba(255,255,255,0.04)', tickangle=-30, row=2, col=1)

        st.plotly_chart(fig_c, use_container_width=True)

    st.divider()

# 하단 갱신 버튼
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if st.button('🔄 데이터 새로고침', use_container_width=True):
        st.cache_data.clear()
        st.rerun()
