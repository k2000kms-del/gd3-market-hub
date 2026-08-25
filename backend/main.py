# -*- coding: utf-8 -*-
"""
GD3 Market Hub — FastAPI 백엔드 메인
실행: uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
"""
import os, sys, asyncio, json
from datetime import datetime
from typing import Optional

# 경로 설정
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

import backend.services as svc

# ── FastAPI 앱 초기화 ──
app = FastAPI(
    title="GD3 Market Hub API",
    description="퀀트 대시보드 REST API + WebSocket",
    version="2.0.0"
)

# ── CORS 설정 (태블릿/외부 접속 허용) ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 프론트엔드 정적 파일 서빙 ──
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'frontend')
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ══════════════════════════════════════════════════════════════
# 루트 — 프론트엔드 서빙
# ══════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    index_path = os.path.join(FRONTEND_DIR, 'index.html')
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "GD3 Market Hub API", "docs": "/docs"}


# ══════════════════════════════════════════════════════════════
# REST API — 시장 데이터
# ══════════════════════════════════════════════════════════════

@app.get("/api/market/indices")
async def get_indices():
    """코스피/코스닥/환율/해외지수 실시간"""
    try:
        naver = svc.fetch_naver_realtime_indices()
        fdr_idx = svc.fetch_live_indices()
        return {"naver": naver, "fdr": fdr_idx, "ts": datetime.now().isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/market/supply")
async def get_market_supply():
    """코스피/코스닥 실시간 투자자 수급"""
    try:
        return svc.fetch_naver_realtime_supply()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/market/summary")
async def get_market_summary():
    """시장 전체 요약 (지수 + 수급 + KOSPI MA20)"""
    try:
        dfs     = svc.load_market_data()
        indices = svc.fetch_naver_realtime_indices()
        supply  = svc.fetch_naver_realtime_supply()
        return svc.get_market_summary(dfs, indices, supply)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/market/quant-top10")
async def get_quant_top10():
    """퀀트 TOP10 종목"""
    try:
        dfs = svc.load_market_data()
        return svc.get_quant_top10(dfs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/market/high-density")
async def get_high_density():
    """고밀도 관심 종목 리스트"""
    try:
        dfs = svc.load_market_data()
        df  = dfs.get('df_high_density', None)
        if df is None or df.empty:
            return []
        return df.head(50).fillna('').to_dict(orient='records')
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/market/bollinger-energy")
async def get_bollinger_energy():
    """볼린저 밴드(20,2) 상단 돌파 분석 기반 시장 에너지 지표"""
    try:
        return svc.get_bollinger_market_energy()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════
# REST API — 개별 종목
# ══════════════════════════════════════════════════════════════

@app.get("/api/stock/{code}/chart/daily")
async def get_stock_daily_chart(code: str):
    """종목 일봉 차트 데이터"""
    try:
        return svc.get_stock_history(code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock/{code}/chart/minute")
async def get_stock_minute_chart(code: str, count: int = 300):
    """종목 1분봉 차트 데이터"""
    try:
        return svc.get_minute_history(code, count)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock/{code}/supply")
async def get_stock_supply(code: str, days: int = 10):
    """종목 수급 추이"""
    try:
        return svc.fetch_stock_supply_trend(code, days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock/{code}/news")
async def get_stock_news(code: str, count: int = 5):
    """종목 최근 뉴스"""
    try:
        return svc.fetch_stock_recent_news(code, count)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock/{code}/investors")
async def get_stock_investors(code: str):
    """종목 외국인/기관 수급"""
    try:
        result = svc.fetch_stock_realtime_investors((code,))
        return result.get(code, {"foreign": 0, "institutional": 0})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════
# REST API — 포트폴리오
# ══════════════════════════════════════════════════════════════

@app.get("/api/portfolio")
async def get_portfolio():
    """포트폴리오 + 현재 손익 조회"""
    try:
        portfolio = svc.load_portfolio()
        dfs       = svc.load_market_data()
        status    = svc.get_portfolio_status(portfolio, dfs)
        return {"portfolio": portfolio, "status": status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class PortfolioItem(BaseModel):
    code: str
    name: str
    entry_price: float
    quantity: int = 0
    stop_loss: float = 0.0
    memo: str = ""


@app.post("/api/portfolio")
async def add_portfolio_item(item: PortfolioItem):
    """종목 추가"""
    try:
        portfolio = svc.load_portfolio()
        portfolio[item.code] = {
            "name": item.name,
            "entry_price": item.entry_price,
            "quantity": item.quantity,
            "stop_loss": item.stop_loss,
            "memo": item.memo,
        }
        svc.save_portfolio(portfolio)
        return {"success": True, "portfolio": portfolio}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/portfolio/{code}")
async def delete_portfolio_item(code: str):
    """종목 삭제"""
    try:
        portfolio = svc.load_portfolio()
        if code not in portfolio:
            raise HTTPException(status_code=404, detail="종목 없음")
        del portfolio[code]
        svc.save_portfolio(portfolio)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════
# WebSocket — 실시간 시세
# ══════════════════════════════════════════════════════════════

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, data: dict):
        msg = json.dumps(data, ensure_ascii=False)
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


@app.websocket("/ws/realtime")
async def websocket_realtime(ws: WebSocket):
    """실시간 시세 WebSocket — 연결 후 30초마다 지수/수급 push"""
    await manager.connect(ws)
    try:
        while True:
            try:
                indices = svc.fetch_naver_realtime_indices()
                supply  = svc.fetch_naver_realtime_supply()
                await ws.send_text(json.dumps({
                    "type": "realtime",
                    "indices": indices,
                    "supply": supply,
                    "ts": datetime.now().isoformat()
                }, ensure_ascii=False))
            except Exception as e:
                print(f"WS broadcast error: {e}")
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        manager.disconnect(ws)


@app.get("/api/market/volume-leaders")
async def get_volume_leaders():
    """거래대금 리더 (Panel 3)"""
    try:
        dfs = svc.load_market_data()
        return svc.get_volume_leaders(dfs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/market/change-leaders")
async def get_change_leaders():
    """상승률 리더 (Panel 6)"""
    try:
        dfs = svc.load_market_data()
        return svc.get_change_leaders(dfs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock/{code}/chart/kis-minute")
async def get_kis_minute(code: str, app_key: str = "", app_secret: str = ""):
    """KIS API 1분봉 (app_key, app_secret 쿼리 파라미터)"""
    try:
        if not app_key or not app_secret:
            app_key    = svc._get_secret("KIS_APP_KEY")
            app_secret = svc._get_secret("KIS_APP_SECRET")
        if not app_key:
            return []
        return svc.get_kis_minute_history(app_key, app_secret, code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock/{code}/ai-commentary")
async def get_ai_commentary(code: str, current_price: float = 0, chg_rate: float = 0):
    """Gemini AI 종목 코멘터리"""
    try:
        api_key = svc._get_secret("GEMINI_API_KEY")
        supply  = svc.fetch_stock_supply_trend(code)
        news    = svc.fetch_stock_recent_news(code, count=3)
        comment = svc.get_gemini_commentary_simple(
            code=code, name=code, api_key=api_key,
            current_price=current_price, chg_rate=chg_rate,
            supply=supply, news=news
        )
        return {"commentary": comment}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stock/{code}/scalping-signal")
async def get_scalping_signal(code: str):
    """스캘핑 매수/관망 신호"""
    try:
        minute_data = svc.get_minute_history(code, count=100)
        if not minute_data:
            kis_key = svc._get_secret("KIS_APP_KEY")
            kis_sec = svc._get_secret("KIS_APP_SECRET")
            if kis_key:
                minute_data = svc.get_kis_minute_history(kis_key, kis_sec, code)
        return svc.get_scalping_signal(minute_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 헬스체크 ──
@app.get("/healthz")
async def health():
    return {"status": "ok", "ts": datetime.now().isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
