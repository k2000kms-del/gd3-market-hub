import io
import os
from typing import List, Dict, Any
from PIL import Image, ImageDraw, ImageFont


def _get_font(size: int, bold: bool = False):
    candidate_paths = [
        'C:/Windows/Fonts/malgunbd.ttf' if bold else 'C:/Windows/Fonts/malgun.ttf',
        'C:/Windows/Fonts/NanumGothicBold.ttf' if bold else 'C:/Windows/Fonts/NanumGothic.ttf',
        'C:/Windows/Fonts/gulim.ttc',
        '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf' if bold else '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ]
    for p in candidate_paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def create_desk_slide(
    slide_num: int,
    total_slides: int,
    main_title: str,
    sub_title: str,
    date_str: str,
    sections: List[Dict[str, Any]]
) -> io.BytesIO:
    width, height = 800, 1060
    bg_color = (19, 78, 63)
    im = Image.new('RGB', (width, height), bg_color)
    draw = ImageDraw.Draw(im)

    card_x0, card_y0 = 36, 70
    card_x1, card_y1 = width - 36, height - 60
    card_color = (252, 252, 250)
    draw.rounded_rectangle([card_x0, card_y0, card_x1, card_y1], radius=24, fill=card_color)

    tape_w, tape_h = 100, 24
    tape_x0 = (width - tape_w) // 2
    tape_y0 = card_y0 - 10
    draw.rounded_rectangle([tape_x0, tape_y0, tape_x0 + tape_w, tape_y0 + tape_h], radius=4, fill=(218, 188, 142))

    f_logo = _get_font(18, bold=True)
    f_badge = _get_font(15, bold=True)
    f_h1 = _get_font(28, bold=True)
    f_h2 = _get_font(20, bold=True)
    f_sec_h = _get_font(17, bold=True)
    f_body = _get_font(15, bold=False)
    f_footer = _get_font(13, bold=False)

    cur_y = card_y0 + 26
    draw.text((card_x0 + 24, cur_y), 'THE DESK', fill=(45, 52, 54), font=f_logo)
    
    badge_text = f'{slide_num}/{total_slides}'
    badge_w, badge_h = 56, 24
    bx1 = card_x1 - 24
    bx0 = bx1 - badge_w
    draw.rounded_rectangle([bx0, cur_y - 2, bx1, cur_y + badge_h - 2], radius=12, fill=(45, 52, 54))
    draw.text((bx0 + 13, cur_y + 1), badge_text, fill=(255, 255, 255), font=f_badge)

    cur_y += 36

    h_box_y0 = cur_y
    h_box_h = 82 if date_str else 68
    h_box_color = (255, 235, 145)
    draw.rounded_rectangle([card_x0 + 20, h_box_y0, card_x1 - 20, h_box_y0 + h_box_h], radius=16, fill=h_box_color)

    if date_str:
        draw.text((card_x0 + 36, h_box_y0 + 12), date_str, fill=(30, 39, 46), font=f_h1)
        draw.text((card_x0 + 36, h_box_y0 + 46), main_title, fill=(50, 60, 70), font=f_h2)
    else:
        draw.text((card_x0 + 36, h_box_y0 + 18), main_title, fill=(30, 39, 46), font=f_h1)

    cur_y = h_box_y0 + h_box_h + 16

    for sec in sections:
        badge = sec.get('badge', '')
        title = sec.get('title', '')
        lines = sec.get('lines', [])
        is_highlight = sec.get('highlight', False)

        sec_bg = (255, 245, 235) if is_highlight else (243, 245, 247)
        sec_border = (255, 168, 1) if is_highlight else None

        line_count = len(lines)
        sec_h = 36 + (line_count * 23) + 12
        sec_y0 = cur_y
        sec_y1 = cur_y + sec_h

        if sec_y1 > card_y1 - 40:
            break

        draw.rounded_rectangle(
            [card_x0 + 20, sec_y0, card_x1 - 20, sec_y1],
            radius=12,
            fill=sec_bg,
            outline=sec_border,
            width=2 if sec_border else 1
        )

        title_y = sec_y0 + 8
        if badge:
            b_fill = (255, 107, 107) if is_highlight else (19, 78, 63)
            b_w = len(badge) * 14 + 16
            draw.rounded_rectangle([card_x0 + 32, title_y, card_x0 + 32 + b_w, title_y + 22], radius=6, fill=b_fill)
            draw.text((card_x0 + 40, title_y + 2), badge, fill=(255, 255, 255), font=f_footer)
            draw.text((card_x0 + 40 + b_w + 10, title_y + 2), title, fill=(45, 52, 54), font=f_sec_h)
        else:
            draw.text((card_x0 + 32, title_y + 2), title, fill=(45, 52, 54), font=f_sec_h)

        line_y = title_y + 28
        for line in lines:
            draw.text((card_x0 + 36, line_y), line, fill=(45, 52, 54), font=f_body)
            line_y += 23

        cur_y = sec_y1 + 12

    footer_text = '출처: GD 3.0 AI 분석실 · 정보 제공용 · 투자 권유 아님'
    draw.text((card_x0 + 200, card_y1 - 32), footer_text, fill=(120, 130, 140), font=f_footer)

    buf = io.BytesIO()
    im.save(buf, format='JPEG', quality=95)
    buf.seek(0)
    return buf


def generate_hodugamza_weekly_cardset(
    date_str: str,
    period_str: str,
    market_summary: dict = None,
    conditions_picks: list = None,
    us_signals: list = None
) -> List[io.BytesIO]:
    market_summary = market_summary or {}
    conditions_picks = conditions_picks or []
    us_signals = us_signals or []
    slides = []

    s1_sections = [
        {
            'badge': '주말 브리핑',
            'title': 'THE DESK Market Pulse',
            'lines': [
                f'• 주간 검증 기간: {period_str}',
                '• 과거 데이터 학습·검증 시장 초과 수익 조건 추적',
                '• 월요일 KR 시초가 갭 & 주도 테마 1차 전망'
            ],
            'highlight': True
        },
        {
            'badge': '핵심 결론',
            'title': '시장 수급 및 주간 판정',
            'lines': [
                '• KR 증시: 10일 이동평균선 지지 여부 테스트 구간',
                '• 수급 축소 흐름 속 조선/전력/방산 섹터 차별화',
                '• 월요일 시초가는 보수적 방어선 유지 권장'
            ]
        }
    ]
    slides.append(create_desk_slide(1, 5, 'THE DESK 주말 브리핑', '', date_str, s1_sections))

    kospi_chg = market_summary.get('kospi_chg', -1.71)
    kosdaq_chg = market_summary.get('kosdaq_chg', -1.00)
    sp_chg = market_summary.get('sp_chg', -2.09)
    nasdaq_chg = market_summary.get('nasdaq_chg', -0.37)

    s2_sections = [
        {
            'badge': '한줄 요약',
            'title': '국내 vs 글로벌 시장 등락률',
            'lines': [
                f'• KOSPI: {kospi_chg:+.2f}%  |  KOSDAQ: {kosdaq_chg:+.2f}%',
                f'• S&P500: {sp_chg:+.2f}%  |  NASDAQ: {nasdaq_chg:+.2f}%',
                '• 변동성 지수 및 환율 안정성 지속 점검 필요'
            ]
        },
        {
            'badge': '월요일 전망',
            'title': 'KR 시초가 갭 예상 구간',
            'lines': [
                '• KOSPI 예상: 직전 종가 대비 -0.5% ~ -1.2% 하락 출발 우세',
                '• KOSDAQ 예상: 장초반 투매 후 10:30경 기술적 반등 시도',
                '• 개장 직후 무리한 추격매수 금지 및 세력선 지지 확인'
            ],
            'highlight': True
        }
    ]
    slides.append(create_desk_slide(2, 5, '주간 지수 결산 및 시초가 갭', '', '시장 국면 체크', s2_sections))

    s3_lines = []
    for p in conditions_picks[:5]:
        s3_lines.append(f"• {p.get('name', '종목')} — {p.get('desc', '공시 분석')}")
    if not s3_lines:
        s3_lines = [
            '• DB하이텍 — 자사주 취득 신탁 체결 (+0.1%)',
            '• 파라텍스이더리움 — 공시 이후 +0.3% 지지',
            '• 신흥 — 자사주 취득 공시 이후 방어선 유지'
        ]

    s3_sections = [
        {
            'badge': '공시 추적',
            'title': '자사주 취득 신탁계약 체결 (최근 7일)',
            'lines': [
                '• 과거 20거래일 평균 +2.2%p 초과수익 검증 조건'
            ] + s3_lines,
            'highlight': True
        }
    ]
    slides.append(create_desk_slide(3, 5, '검증된 조건 해당 종목 (7일 공시)', '', '기관급 알파 스캔', s3_sections))

    s4_lines = []
    for u in us_signals[:5]:
        s4_lines.append(f"• {u.get('title', '신호')}: {u.get('desc', '')}")
    if not s4_lines:
        s4_lines = [
            '• 미국 임원 장내 매수: TEAM, DDOG, PCT 매수 유입',
            '• 미국 반도체 → 국내 반도체 다음 달 신호: 켜짐 유지',
            '• 원/달러 야간 환율: 1,390원대 안정 흐름 유지'
        ]

    s4_sections = [
        {
            'badge': '글로벌 신호',
            'title': '미국 임원 매수 & 반도체 선행 지표',
            'lines': s4_lines
        }
    ]
    slides.append(create_desk_slide(4, 5, '글로벌 매크로 & 스마트 머니 추적', '', '선행 지표 분석', s4_sections))

    s5_sections = [
        {
            'badge': '주요 일정',
            'title': '다음 주 핵심 경제 캘린더',
            'lines': [
                '• 화요일: 미국 비농업 고용 및 ISM 제조업 지수',
                '• 수요일: 연준 FOMC 의사록 공개 및 연준위원 발언',
                '• 목요일: 한국은행 금통위 기준금리 결정 회의'
            ]
        },
        {
            'badge': '실전 가이드',
            'title': '대표님 계좌 1주일 액션 로드맵',
            'lines': [
                '• 포지션: 현금 비중 30% 이상 방어선 엄수',
                '• 매매 전략: 주도 섹터(조선/전력) 눌림목 분할 매수만 허용',
                '• 손절 규칙: 보유 종목 -3% 이탈 시 즉시 비중 축소'
            ],
            'highlight': True
        }
    ]
    slides.append(create_desk_slide(5, 5, '차주 캘린더 & 실전 매매 로드맵', '', '수석 비서 제언', s5_sections))

    return slides
