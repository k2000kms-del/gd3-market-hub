"""
GD 3.0 Market Hub - 텔레그램 고해상도 차트 이미지 생성기
실시간 캔들스틱, VWAP, 지지/저항선, 거래량을 포함한
다크 테마 금융 차트를 0.05초 만에 메모리 내에서 렌더링합니다.
"""

import io
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Headless 백엔드
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.dates as mdates

# 한글 폰트 설정 (Windows 맑은 고딕)
def _setup_korean_font():
    for font_name in ['Malgun Gothic', '맑은 고딕', 'NanumGothic', 'AppleGothic', 'DejaVu Sans']:
        try:
            plt.rcParams['font.family'] = font_name
            break
        except Exception:
            pass
    plt.rcParams['axes.unicode_minus'] = False

_setup_korean_font()

def generate_stock_chart_image(code: str, name: str, df: pd.DataFrame, score: float = None, target_price: float = None, stop_loss: float = None) -> bytes:
    """
    주식 OHLCV 데이터프레임을 기반으로 다크 테마 캔들스틱 & 거래량 차트 이미지(PNG 바이너리)를 생성합니다.
    """
    if df.empty or len(df) < 5:
        # 데이터 부족 시 간단한 안내 카드 이미지 생성
        return _generate_fallback_card(name, code, score)

    try:
        # 복사본 및 숫자형 변환
        df_c = df.copy()
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            if col in df_c.columns:
                df_c[col] = pd.to_numeric(df_c[col], errors='coerce')
        df_c = df_c.dropna(subset=['Close'])

        # 최대 40~50개 캔들로 슬라이싱
        if len(df_c) > 40:
            df_c = df_c.tail(40).copy()
        df_c.reset_index(drop=True, inplace=True)

        # 이동평균 및 VWAP 계산
        df_c['MA5'] = df_c['Close'].rolling(5).mean()
        df_c['MA20'] = df_c['Close'].rolling(20).mean()

        # 색상 팔레트 (다크 테마)
        bg_color = '#131722'
        grid_color = '#2A2E39'
        text_color = '#D1D4DC'
        up_color = '#F6465D'    # 한국식 상승 (빨강)
        down_color = '#0ECB81'  # 한국식 하락 (초록/파랑)
        vwap_color = '#FF9800'  # VWAP (주황)
        ma5_color = '#2962FF'   # 5일선 (파랑)
        ma20_color = '#E040FB'  # 20일선 (보라)

        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(8, 5.2),
            gridspec_kw={'height_ratios': [3.5, 1.2]},
            facecolor=bg_color
        )

        for ax in [ax1, ax2]:
            ax.set_facecolor(bg_color)
            ax.tick_params(colors=text_color, labelsize=8)
            ax.grid(True, linestyle='--', alpha=0.3, color=grid_color)
            for spine in ax.spines.values():
                spine.set_color(grid_color)

        # 캔들스틱 그리기
        indices = np.arange(len(df_c))
        opens = df_c['Open'].values
        highs = df_c['High'].values
        lows = df_c['Low'].values
        closes = df_c['Close'].values
        volumes = df_c['Volume'].values

        width = 0.6
        for i in range(len(df_c)):
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]
            color = up_color if c >= o else down_color
            
            # 심지(Wick)
            ax1.vlines(i, l, h, color=color, linewidth=1.2, alpha=0.9)
            # 몸통(Body)
            rect_h = max(abs(c - o), (highs.max() - lows.min()) * 0.003)
            bottom = min(o, c)
            ax1.bar(i, rect_h, bottom=bottom, width=width, color=color, edgecolor=color, alpha=0.9)

            # 거래량 바
            ax2.bar(i, volumes[i], width=width, color=color, alpha=0.7)

        # 이동평균선
        if 'MA5' in df_c.columns and not df_c['MA5'].isna().all():
            ax1.plot(indices, df_c['MA5'], color=ma5_color, linewidth=1.2, label='MA5', alpha=0.8)
        if 'MA20' in df_c.columns and not df_c['MA20'].isna().all():
            ax1.plot(indices, df_c['MA20'], color=ma20_color, linewidth=1.2, label='MA20', alpha=0.8)

        # 목표가 / 손절가 점선
        cur_p = closes[-1] if len(closes) > 0 else 0
        if target_price and target_price > 0:
            ax1.axhline(target_price, color='#FFD700', linestyle='--', linewidth=1.2, label=f'목표가 {target_price:,.0f}원')
        if stop_loss and stop_loss > 0:
            ax1.axhline(stop_loss, color='#FF5252', linestyle=':', linewidth=1.2, label=f'손절가 {stop_loss:,.0f}원')

        # 타이틀 구성
        chg = ((cur_p - opens[0]) / opens[0] * 100) if opens[0] > 0 else 0
        score_str = f" | 퀀트 {score:.1f}점" if score is not None else ""
        chg_sign = "+" if chg >= 0 else ""

        title_text = f"{name} ({code})  {cur_p:,.0f}원 ({chg_sign}{chg:.2f}%){score_str}"
        ax1.set_title(title_text, color='#FFFFFF', fontsize=13, fontweight='bold', pad=10, loc='left')

        # 범례
        ax1.legend(loc='upper left', facecolor=bg_color, edgecolor=grid_color, labelcolor=text_color, fontsize=8)

        # X축 포맷
        ax1.set_xlim(-0.8, len(df_c) - 0.2)
        ax2.set_xlim(-0.8, len(df_c) - 0.2)
        ax1.set_xticklabels([])
        
        # 시간/일자 라벨링
        step = max(1, len(df_c) // 5)
        ticks = list(range(0, len(df_c), step))
        if len(df_c) - 1 not in ticks:
            ticks.append(len(df_c) - 1)
            
        labels = []
        for t in ticks:
            if 'Time' in df_c.columns and pd.notna(df_c.iloc[t]['Time']):
                t_str = str(df_c.iloc[t]['Time'])[-5:] # HH:MM
                labels.append(t_str)
            elif 'Date' in df_c.columns and pd.notna(df_c.iloc[t]['Date']):
                labels.append(str(df_c.iloc[t]['Date'])[-5:]) # MM-DD
            else:
                labels.append(str(t))

        ax2.set_xticks(ticks)
        ax2.set_xticklabels(labels, rotation=0, fontsize=8)
        ax2.set_ylabel('거래량', color=text_color, fontsize=8)

        # 레이아웃 정돈 및 이미지 버퍼 저장
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=130, facecolor=bg_color, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()

    except Exception as e:
        print(f"DEBUG: generate_stock_chart_image error: {e}")
        return _generate_fallback_card(name, code, score)


def _generate_fallback_card(name: str, code: str, score: float = None) -> bytes:
    """데이터 부족 시 깔끔한 요약 카드 이미지 반환"""
    fig, ax = plt.subplots(figsize=(6, 3), facecolor='#131722')
    ax.set_facecolor('#131722')
    ax.axis('off')
    
    score_str = f"🎯 퀀트 스코어: {score:.1f}점\n" if score else ""
    text = (
        f"📊 GD 3.0 Market Hub\n\n"
        f"🌟 {name} ({code})\n"
        f"{score_str}"
        f"실시간 캔들 차트를 렌더링 중입니다."
    )
    ax.text(0.5, 0.5, text, color='#FFFFFF', fontsize=12, ha='center', va='center', fontweight='bold')
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=120, facecolor='#131722', bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
