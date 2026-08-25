import os

file_path = 'app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Extract the sidebar portfolio logic
start_str = "                portfolio_sidebar_container.markdown('---')\n                portfolio_sidebar_container.markdown('### 💼 실전 포트폴리오 관리')"
end_str = "                    else:\n                        portfolio_sidebar_container.button(\"🗑️ 삭제\", use_container_width=True, disabled=True, key=\"btn_port_del_dis\")"

start_idx = text.find(start_str)
end_idx = text.find(end_str, start_idx) + len(end_str)

if start_idx != -1 and end_idx != -1:
    portfolio_logic = text[start_idx:end_idx]
    
    # 2. Remove the logic from the old location
    text = text[:start_idx] + text[end_idx:]
    
    # 3. Create the replacement block for the top
    replacement = """portfolio_sidebar_container = st.sidebar.container()

# ── 💼 실전 포트폴리오 관리 사이드바 UI (즉시 렌더링) ──
_port_code_disp = st.session_state.get('sel_code', '005930')
_port_name_disp = st.session_state.get('sel_name', '삼성전자')
_port_last_close = 0.0
if 'df_m' in globals() and not df_m.empty:
    _match = df_m[df_m['Code'] == _port_code_disp]
    if not _match.empty:
        _port_last_close = float(_match.iloc[0]['Close'])

portfolio = load_portfolio()

portfolio_sidebar_container.markdown('---')
portfolio_sidebar_container.markdown('### 💼 실전 포트폴리오 관리')

# 현재 조회 중인 종목 보유 여부
is_held = _port_code_disp in portfolio
held_info = portfolio.get(_port_code_disp, {"entry_price": 0.0, "qty": 0.0})

# 평단가 및 수량 입력란 (streamlit input 사용)
col_p1, col_p2 = portfolio_sidebar_container.columns(2)
with col_p1:
    input_price = portfolio_sidebar_container.number_input(
        "매수 평단가 (원)", 
        min_value=0.0, 
        value=float(held_info["entry_price"]) if is_held else float(_port_last_close), 
        step=100.0,
        key="port_input_price"
    )
with col_p2:
    input_qty = portfolio_sidebar_container.number_input(
        "보유 수량 (주)", 
        min_value=0.0, 
        value=float(held_info["qty"]) if is_held else 0.0, 
        step=1.0,
        key="port_input_qty"
    )

# 등록/수정/삭제 버튼
col_btn1, col_btn2 = portfolio_sidebar_container.columns(2)
with col_btn1:
    if portfolio_sidebar_container.button("➕ 등록/수정", use_container_width=True, key="btn_port_save"):
        if input_price > 0 and input_qty > 0:
            portfolio[_port_code_disp] = {
                "name": _port_name_disp,
                "entry_price": input_price,
                "qty": input_qty
            }
            save_portfolio(portfolio)
            portfolio_sidebar_container.toast(f"💼 {_port_name_disp} 포트폴리오 저장 완료!", icon="✅")
            st.rerun()
        else:
            portfolio_sidebar_container.warning("가격과 수량을 입력해주세요.")
with col_btn2:
    if is_held:
        if portfolio_sidebar_container.button("🗑️ 삭제", use_container_width=True, key="btn_port_del"):
            del portfolio[_port_code_disp]
            save_portfolio(portfolio)
            portfolio_sidebar_container.toast(f"🗑️ {_port_name_disp} 포트폴리오 삭제 완료", icon="ℹ️")
            st.rerun()
    else:
        portfolio_sidebar_container.button("🗑️ 삭제", use_container_width=True, disabled=True, key="btn_port_del_dis")
"""

    text = text.replace("portfolio_sidebar_container = st.sidebar.container()", replacement)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(text)
    print("Success: Moved portfolio UI logic")
else:
    print("Error: Could not find portfolio logic")
