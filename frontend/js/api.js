/* ══════════════════════════════════════════════
   GD3 Market Hub — API 통신 모듈 (api.js)
   FastAPI 백엔드와의 REST API & WebSocket 클라이언트
   ══════════════════════════════════════════════ */

const API_BASE = window.location.origin;

const API = {
  // ── 시장 지수 / 수급 / 퀀트 ──
  async getIndices() {
    const res = await fetch(`${API_BASE}/api/market/indices`);
    return await res.json();
  },

  async getMarketSupply() {
    const res = await fetch(`${API_BASE}/api/market/supply`);
    return await res.json();
  },

  async getMarketSummary() {
    const res = await fetch(`${API_BASE}/api/market/summary`);
    return await res.json();
  },

  async getQuantTop10() {
    const res = await fetch(`${API_BASE}/api/market/quant-top10`);
    return await res.json();
  },

  async getHighDensity() {
    const res = await fetch(`${API_BASE}/api/market/high-density`);
    return await res.json();
  },

  // ── 개별 종목 ──
  async getStockDailyChart(code) {
    const res = await fetch(`${API_BASE}/api/stock/${code}/chart/daily`);
    return await res.json();
  },

  async getStockMinuteChart(code, count = 300) {
    const res = await fetch(`${API_BASE}/api/stock/${code}/chart/minute?count=${count}`);
    return await res.json();
  },

  async getStockSupply(code, days = 10) {
    const res = await fetch(`${API_BASE}/api/stock/${code}/supply?days=${days}`);
    return await res.json();
  },

  async getStockNews(code, count = 5) {
    const res = await fetch(`${API_BASE}/api/stock/${code}/news?count=${count}`);
    return await res.json();
  },

  async getStockInvestors(code) {
    const res = await fetch(`${API_BASE}/api/stock/${code}/investors`);
    return await res.json();
  },

  // ── 포트폴리오 ──
  async getPortfolio() {
    const res = await fetch(`${API_BASE}/api/portfolio`);
    return await res.json();
  },

  async addPortfolio(item) {
    const res = await fetch(`${API_BASE}/api/portfolio`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(item)
    });
    return await res.json();
  },

  async deletePortfolio(code) {
    const res = await fetch(`${API_BASE}/api/portfolio/${code}`, {
      method: 'DELETE'
    });
    return await res.json();
  },

  // ── 거래대금 리더 (Panel 3) ──
  async getVolumeLeaders() {
    const res = await fetch(`${API_BASE}/api/market/volume-leaders`);
    return await res.json();
  },

  // ── 상승률 리더 (Panel 6) ──
  async getChangeLeaders() {
    const res = await fetch(`${API_BASE}/api/market/change-leaders`);
    return await res.json();
  },

  // ── KIS 1분봉 (KIS API) ──
  async getKisMinuteChart(code) {
    const res = await fetch(`${API_BASE}/api/stock/${code}/chart/kis-minute`);
    return await res.json();
  },

  // ── Gemini AI 코멘터리 ──
  async getAICommentary(code, currentPrice = 0, chgRate = 0) {
    const res = await fetch(`${API_BASE}/api/stock/${code}/ai-commentary?current_price=${currentPrice}&chg_rate=${chgRate}`);
    return await res.json();
  },

  // ── 스캘핑 신호 ──
  async getScalpingSignal(code) {
    const res = await fetch(`${API_BASE}/api/stock/${code}/scalping-signal`);
    return await res.json();
  },

  // ── 볼린저 밴드(20,2) 시장 에너지 지표 ──
  async getBollingerEnergy() {
    const res = await fetch(`${API_BASE}/api/market/bollinger-energy`);
    return await res.json();
  }
};

// ── WebSocket 클라이언트 ──
class RealtimeWS {
  constructor(onMessage) {
    this.onMessage = onMessage;
    this.ws = null;
    this.reconnectTimer = null;
  }

  connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/realtime`;
    
    try {
      this.ws = new WebSocket(wsUrl);
      
      this.ws.onopen = () => {
        console.log("WebSocket 연결 성공");
        if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (this.onMessage) this.onMessage(data);
        } catch (e) {
          console.error("WS 메시지 파싱 에러:", e);
        }
      };

      this.ws.onclose = () => {
        console.log("WebSocket 끊김, 10초 후 재연동 시도...");
        this.reconnectTimer = setTimeout(() => this.connect(), 10000);
      };

      this.ws.onerror = (err) => {
        console.error("WS 에러:", err);
      };
    } catch (e) {
      console.error("WS 생성 에러:", e);
    }
  }
}
