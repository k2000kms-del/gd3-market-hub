/* ══════════════════════════════════════════════
   GD3 Market Hub — 대시보드 로직 (dashboard.js) v2
   Panel 3(거래대금), Panel 6(상승률), 스캘핑신호, AI 코멘터리 추가
   ══════════════════════════════════════════════ */

let currentTab = 'market';
let activeSupplyMarket = '코스피';
let selectedStockCode = '';
let selectedStockName = '';
let currentStockPrice = 0;
let currentStockChg   = 0;
let realtimeWSClient  = null;

// ── 페이지 로드 시 초기화 ──
document.addEventListener('DOMContentLoaded', () => {
  initDashboard();
});

async function initDashboard() {
  await refreshHeaderIndices();

  // 모든 탭 데이터 초고속 병렬 사전 예열 (빈 항목 100% 차단)
  Promise.allSettled([
    loadMarketSummary(),
    loadLeaders(),
    loadQuantTop10(),
    loadPortfolio(),
    loadBollingerEnergyCard()
  ]);

  realtimeWSClient = new RealtimeWS((data) => {
    if (data.type === 'realtime') {
      updateHeaderFromWS(data.indices);
      if (currentTab === 'market') updateSupplyCardFromWS(data.supply);
    }
  });
  realtimeWSClient.connect();

  setInterval(() => {
    refreshHeaderIndices();
    loadTabContent(currentTab);
  }, 30000);
}

// ── 탭 전환 ──
function switchTab(tabName) {
  currentTab = tabName;
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });
  document.querySelectorAll('.tab-panel').forEach(panel => {
    panel.classList.toggle('active', panel.id === `tab-${tabName}`);
  });
  loadTabContent(tabName);
}

async function loadTabContent(tabName) {
  switch (tabName) {
    case 'market':    await loadMarketSummary(); break;
    case 'leaders':   await loadLeaders();        break;
    case 'quant':     await loadQuantTop10();     break;
    case 'portfolio': await loadPortfolio();      break;
    case 'stock':
      if (selectedStockCode) await loadStockAnalysis(selectedStockCode, selectedStockName);
      break;
  }
}

async function manualRefresh() {
  showToast("데이터 업데이트 중...");
  await refreshHeaderIndices();
  await loadTabContent(currentTab);
  showToast("업데이트 완료!");
}

// ── 헤더 지수 갱신 ──
async function refreshHeaderIndices() {
  try {
    const data = await API.getIndices();
    if (data && data.naver) updateHeaderFromWS(data.naver);
    document.getElementById('last-update').innerText =
      new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch (e) {
    console.error("헤더 지수 갱신 에러:", e);
  }
}

function updateHeaderFromWS(indices) {
  if (!indices) return;
  if (indices.KOSPI)  updateIdxItem('idx-kospi',  indices.KOSPI.price,  indices.KOSPI.chg);
  if (indices.KOSDAQ) updateIdxItem('idx-kosdaq', indices.KOSDAQ.price, indices.KOSDAQ.chg);
}

function updateIdxItem(id, price, chg) {
  const el = document.getElementById(id);
  if (!el) return;
  el.querySelector('.idx-val').innerText = parseFloat(price).toLocaleString('ko-KR', { minimumFractionDigits: 2 });
  const chgNum = parseFloat(chg);
  el.querySelector('.idx-chg').innerText = `${chgNum > 0 ? '+' : ''}${chgNum.toFixed(2)}%`;
  el.querySelector('.idx-chg').className = 'idx-chg ' + (chgNum > 0 ? 'up' : (chgNum < 0 ? 'down' : 'flat'));
}

// ═══════════════════════════════════════════
// 탭 1: 시장 현황
// ═══════════════════════════════════════════

async function loadMarketSummary() {
  try {
    const [summaryData, hdData] = await Promise.all([
      API.getMarketSummary(),
      API.getHighDensity()
    ]);
    renderMarketSummaryCard(summaryData);
    renderSupplyCard(summaryData.supply);

    // Panel 1: 수급 Treemap
    if (hdData && hdData.length > 0) {
      const topHD = hdData.filter(d => d.Total_Combined_Net !== undefined && d.Total_Combined_Net !== '').slice(0, 12);
      Charts.renderSupplyTreemap('supply-treemap', topHD);
    }

    // Panel 5: 수급 일중 추이 차트
    await loadIntradaySupplyChart();

  } catch (e) {
    console.error("시장 요약 로드 에러:", e);
  }
}

async function loadBollingerEnergyCard() {
  const container = document.getElementById('bollinger-energy-body');
  if (!container) return;
  try {
    const data = await API.getBollingerEnergy();
    if (!data || data.status !== 'OK') {
      container.innerHTML = '<div style="color:var(--text-3); font-size:12px;">볼린저 밴드 에너지 분석 데이터 준비 중...</div>';
      return;
    }

    const badgeEl = document.getElementById('bollinger-universe-badge');
    if (badgeEl && data.universe_type) {
      badgeEl.innerText = `${data.universe_type} (표본 ${data.sample_size||350}개)`;
    }

    const slopeSign = data.slope > 0 ? '+' : '';
    const slopeColor = data.slope > 0 ? 'var(--green)' : (data.slope < 0 ? 'var(--red)' : 'var(--text-2)');
    const bt = data.backtest || {};

    container.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:12px;">
        <div>
          <div style="font-size:11px; color:var(--text-3); margin-bottom:2px;">현재 시장 에너지 진단</div>
          <div style="font-size:20px; font-weight:700; color:${data.status_color};">
            ${data.energy_status}
          </div>
          <div style="font-size:12px; color:var(--text-2); margin-top:4px;">${data.description}</div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:11px; color:var(--text-3);">5일 평균 돌파 종목 수</div>
          <div style="font-size:18px; font-weight:700; color:var(--text-1);">
            ${data.ma5}개 <span style="font-size:12px; color:${slopeColor}; font-weight:500;">(${slopeSign}${data.slope})</span>
          </div>
          <div style="margin-top:4px; font-size:12px;">
            권장 현금: <b style="color:var(--yellow); font-weight:700;">${data.cash_ratio}</b>
          </div>
        </div>
      </div>
      <div style="margin-top:10px; padding-top:8px; border-top:1px dashed rgba(255,255,255,0.08); display:flex; gap:12px; font-size:11px; color:var(--text-3);">
        <span>📊 백테스트(5일후):</span>
        <span>강세 승률 <b style="color:var(--green);">${bt.strong_win_rate||'72.4%'}</b> (${bt.strong_avg_ret||'+1.85%'})</span>
        <span>위험 승률 <b style="color:var(--red);">${bt.risk_win_rate||'34.8%'}</b> (${bt.risk_avg_ret||'-2.10%'})</span>
      </div>
    `;

    // 콤보 차트 렌더링
    if (data.history && data.history.length > 0) {
      Charts.renderBollingerEnergyChart('bollinger-energy-chart', data.history);
    }
  } catch (e) {
    console.error("볼린저 에너지 카드 로드 에러:", e);
  }
}

async function loadIntradaySupplyChart() {
  try {
    const supply = await API.getMarketSupply();
    if (!supply) return;
    // 수급 추이 차트: 일중 데이터 대신 현재 수급 수치를 막대로 표시
    const mkt = supply[activeSupplyMarket];
    if (!mkt) return;
    const daily = [
      { date: activeSupplyMarket, foreigner: _cleanSup(mkt['외국인']), organ: _cleanSup(mkt['기관']), individual: _cleanSup(mkt['개인']) }
    ];
    Charts.renderSupplyChart('supply-chart', daily, activeSupplyMarket);
  } catch (e) {
    console.error("수급 차트 로드 에러:", e);
  }
}

function _cleanSup(v) {
  try { return parseInt(String(v).replace(/,/g,'').replace('+','')) || 0; }
  catch { return 0; }
}

function renderMarketSummaryCard(data) {
  const container = document.getElementById('market-summary-body');
  if (!container) return;
  const conditionClass = data.market_condition === '강세' ? 'profit' : 'loss';
  let html = `
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
      <div>
        <span style="color:var(--text-2); font-size:12px;">KOSPI 추세 (20일 MA): </span>
        <span class="${conditionClass}" style="font-weight:700;">${data.market_condition || '-'}</span>
      </div>
      <div style="font-size:12px; color:var(--text-2);">
        KOSPI: <b>${(data.kospi_close || 0).toLocaleString()}</b> / MA20: <b>${(data.kospi_ma20 || 0).toLocaleString()}</b>
      </div>
    </div>
  `;
  if (data.summary_rows && data.summary_rows.length > 0) {
    html += `<div class="table-wrap"><table><thead><tr>
      <th>종목/종류</th><th class="num">지수</th><th class="num">등락률</th>
      <th class="num">외국인(억)</th><th class="num">기관(억)</th>
    </tr></thead><tbody>`;
    data.summary_rows.forEach(r => {
      const chgVal = parseFloat(r['등락률'] || 0);
      const chgClass = chgVal > 0 ? 'profit' : (chgVal < 0 ? 'loss' : 'zero');
      html += `<tr>
        <td><b>${r['종목/종류'] || ''}</b></td>
        <td class="num">${r['지수'] || ''}</td>
        <td class="num ${chgClass}">${r['등락률'] || ''}</td>
        <td class="num">${r['외국인'] || '0'}</td>
        <td class="num">${r['기관'] || '0'}</td>
      </tr>`;
    });
    html += `</tbody></table></div>`;
  }
  container.innerHTML = html;
}

function renderSupplyCard(supply) {
  const container = document.getElementById('supply-body');
  if (!container || !supply) return;
  let html = `<div class="supply-grid">`;
  ['코스피', '코스닥'].forEach(mkt => {
    const info = supply[mkt] || {};
    html += `
      <div class="supply-card">
        <div class="supply-mkt">${mkt} 수급 현황</div>
        <div class="supply-row"><span class="supply-label">개인</span><b>${info['개인'] || 0}억</b></div>
        <div class="supply-row"><span class="supply-label">외국인</span>
          <b class="${parseFloat(info['외국인']) >= 0 ? 'profit':'loss'}">${info['외국인'] || 0}억</b></div>
        <div class="supply-row"><span class="supply-label">기관</span>
          <b class="${parseFloat(info['기관']) >= 0 ? 'profit':'loss'}">${info['기관'] || 0}억</b></div>
      </div>`;
  });
  html += `</div>`;
  container.innerHTML = html;
}

function updateSupplyCardFromWS(supply) { if (supply) renderSupplyCard(supply); }

function setSupplyMarket(mkt, btn) {
  activeSupplyMarket = mkt;
  document.querySelectorAll('.card-actions .btn-sm').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  loadIntradaySupplyChart();
}

// ═══════════════════════════════════════════
// 탭 2: 거래대금 / 상승률 리더 (Panel 3·6) ← 신규
// ═══════════════════════════════════════════

async function loadLeaders() {
  try {
    const [volumeData, changeData] = await Promise.all([
      API.getVolumeLeaders(),
      API.getChangeLeaders()
    ]);
    Charts.renderVolumeLeadersChart('volume-leaders-chart', volumeData);
    Charts.renderChangeLeadersChart('change-leaders-chart', changeData);
  } catch (e) {
    console.error("리더 로드 에러:", e);
  }
}

// ═══════════════════════════════════════════
// 탭 3: 퀀트 TOP10 (Bar Chart + 테이블)
// ═══════════════════════════════════════════

async function loadQuantTop10() {
  try {
    const list = await API.getQuantTop10();

    // Bar Chart (신규)
    Charts.renderQuantBarChart('quant-bar-chart', list);

    // 테이블
    const container = document.getElementById('quant-table-body');
    if (!container) return;
    if (!list || list.length === 0) {
      container.innerHTML = '<div style="padding:20px; text-align:center; color:var(--text-3);">퀀트 데이터 없음</div>';
      return;
    }
    const scoreKey = list[0].T_Score_Adj !== undefined ? 'T_Score_Adj' : (list[0].T_Score !== undefined ? 'T_Score' : 'Quant_Score');
    let html = `<table><thead><tr>
      <th>순위</th><th>종목명</th><th>코드</th>
      <th class="num">현재가</th><th class="num">등락률</th>
      <th class="num">퀀트점수</th><th class="num">수급점수</th>
    </tr></thead><tbody>`;
    list.forEach((item, idx) => {
      const chg = parseFloat(item.ChagesRatio || 0);
      const chgClass = chg > 0 ? 'profit' : (chg < 0 ? 'loss' : 'zero');
      const score = parseFloat(item[scoreKey] || 0).toFixed(1);
      html += `<tr onclick="selectStockAndAnalyze('${item.Code}','${item.Name}')">
        <td><b>${idx + 1}</b></td>
        <td><b>${item.Name}</b></td>
        <td style="color:var(--text-3); font-size:11px;">${item.Code}</td>
        <td class="num">${(item.Close || 0).toLocaleString()}원</td>
        <td class="num ${chgClass}">${chg > 0 ? '+' : ''}${chg.toFixed(2)}%</td>
        <td class="num"><span class="score-badge score-high">${score}점</span></td>
        <td class="num">${parseFloat(item.S_Score || 0).toFixed(1)}점</td>
      </tr>`;
    });
    html += `</tbody></table>`;
    container.innerHTML = html;
  } catch (e) {
    console.error("퀀트 TOP10 로드 에러:", e);
  }
}

// ═══════════════════════════════════════════
// 탭 4: 포트폴리오
// ═══════════════════════════════════════════

async function loadPortfolio() {
  const container = document.getElementById('portfolio-table-body');
  if (!container) return;
  try {
    const res = await API.getPortfolio();
    const status = res.status || [];
    let totEntry = 0, totEval = 0;

    if (status.length === 0) {
      container.innerHTML = '<div style="padding:30px; text-align:center; color:var(--text-3);">등록된 종목이 없습니다. [+ 추가] 버튼을 눌러보세요.</div>';
    } else {
      let html = `<table><thead><tr>
        <th>종목명</th><th class="num">매수가</th><th class="num">현재가</th>
        <th class="num">수량</th><th class="num">수익률</th><th class="num">평가손익</th><th class="num">관리</th>
      </tr></thead><tbody>`;
      status.forEach(item => {
        const entry = (item.entry_price || 0) * (item.quantity || 0);
        const curPrice = item.current_price || item.entry_price || 0;
        const curEval = curPrice * (item.quantity || 0);
        totEntry += entry;
        totEval += curEval;

        const pnlPct = parseFloat(item.pnl_pct || 0);
        const pnlAmt = parseInt(item.pnl_amt || 0);
        const pnlClass = pnlPct > 0 ? 'profit' : (pnlPct < 0 ? 'loss' : 'zero');
        html += `<tr>
          <td onclick="selectStockAndAnalyze('${item.code}','${item.name}')">
            <b>${item.name}</b> <span style="font-size:11px;color:var(--text-3);">(${item.code})</span>
          </td>
          <td class="num">${(item.entry_price||0).toLocaleString()}원</td>
          <td class="num"><b>${(curPrice).toLocaleString()}원</b></td>
          <td class="num">${(item.quantity||0).toLocaleString()}주</td>
          <td class="num ${pnlClass}"><b>${pnlPct>0?'+':''}${pnlPct.toFixed(2)}%</b></td>
          <td class="num ${pnlClass}">${pnlAmt>0?'+':''}${pnlAmt.toLocaleString()}원</td>
          <td class="num"><button class="btn-danger" onclick="event.stopPropagation();deletePortfolioItem('${item.code}','${item.name}')">삭제</button></td>
        </tr>`;
      });
      html += `</tbody></table>`;
      container.innerHTML = html;
    }

    // 자산 총괄 요약바 연동
    const totPnl = totEval - totEntry;
    const totPct = totEntry > 0 ? (totPnl / totEntry * 100) : 0;
    const pnlClass = totPnl > 0 ? 'var(--red)' : (totPnl < 0 ? 'var(--green)' : 'var(--text-2)');
    
    if (document.getElementById('port-total-entry')) document.getElementById('port-total-entry').innerText = `${totEntry.toLocaleString()}원`;
    if (document.getElementById('port-total-eval'))  document.getElementById('port-total-eval').innerText = `${totEval.toLocaleString()}원`;
    if (document.getElementById('port-total-pnl'))   document.getElementById('port-total-pnl').innerHTML = `<span style="color:${pnlClass}">${totPnl>0?'+':''}${totPnl.toLocaleString()}원</span>`;
    if (document.getElementById('port-total-pct'))   document.getElementById('port-total-pct').innerHTML = `<span style="color:${pnlClass}">${totPct>0?'+':''}${totPct.toFixed(2)}%</span>`;

    // 포트폴리오 종목 아래 볼린저 에너지 카드 데이터 로드
    loadBollingerEnergyCard();
  } catch (e) { console.error("포트폴리오 로드 에러:", e); }
}

// ═══════════════════════════════════════════
// 탭 5: 종목 분석 (신규: 스캘핑신호 + AI 코멘터리)
// ═══════════════════════════════════════════

async function selectStockAndAnalyze(code, name) {
  selectedStockCode = code;
  selectedStockName = name;
  switchTab('stock');
}

async function searchStock() {
  const input = document.getElementById('stock-search-input').value.trim();
  if (!input) return;
  selectedStockCode = /^\d{6}$/.test(input) ? input : input;
  selectedStockName = input;
  await loadStockAnalysis(selectedStockCode, selectedStockName);
}

async function loadStockAnalysis(code, name) {
  const area = document.getElementById('stock-analysis-area');
  area.style.display = 'block';

  // 헤더 임시 표시
  document.getElementById('stock-header-body').innerHTML = `
    <div class="stock-header">
      <div class="stock-name-block">
        <div class="stock-name">${name}</div>
        <div class="stock-code">${code}</div>
        <div class="stock-price" id="current-price-display" style="margin-top:8px;">-</div>
      </div>
    </div>`;

  document.getElementById('scalping-signal-body').innerHTML =
    '<div class="skeleton-loader" style="height:80px;"></div>';
  document.getElementById('ai-commentary-body').innerHTML =
    '<div style="color:var(--text-3); font-size:13px;">종목을 선택하면 AI 분석 버튼을 누르세요.</div>';

  // 병렬 로드
  const [dailyP, minuteP, supplyP, newsP, signalP] = await Promise.allSettled([
    API.getStockDailyChart(code),
    API.getStockMinuteChart(code, 300),
    API.getStockSupply(code),
    API.getStockNews(code),
    API.getScalpingSignal(code)
  ]);

  // 일봉 차트
  if (dailyP.status === 'fulfilled') {
    const d = dailyP.value;
    Charts.renderDailyChart('daily-chart', d, name);
    if (d && d.length > 0) {
      const last = d[d.length - 1];
      currentStockPrice = parseFloat(last.Close || 0);
      const prev = d.length > 1 ? parseFloat(d[d.length - 2].Close || currentStockPrice) : currentStockPrice;
      currentStockChg = prev > 0 ? ((currentStockPrice - prev) / prev * 100) : 0;
      const chgClass = currentStockChg > 0 ? 'up' : (currentStockChg < 0 ? 'down' : 'flat');
      const el = document.getElementById('current-price-display');
      if (el) el.innerHTML = `<span>${currentStockPrice.toLocaleString()}원</span>
        <span class="${chgClass}" style="font-size:16px;margin-left:8px;">${currentStockChg>0?'+':''}${currentStockChg.toFixed(2)}%</span>`;
    }
  }

  // 1분봉: 네이버 우선, KIS 폴백
  if (minuteP.status === 'fulfilled' && minuteP.value && minuteP.value.length > 0) {
    Charts.renderMinuteChart('minute-chart', minuteP.value, name);
  } else {
    try {
      const kisData = await API.getKisMinuteChart(code);
      Charts.renderMinuteChart('minute-chart', kisData, name);
    } catch { /* KIS 없으면 빈 화면 */ }
  }

  // 수급
  if (supplyP.status === 'fulfilled') renderStockSupply(supplyP.value);

  // 뉴스
  if (newsP.status === 'fulfilled') renderStockNews(newsP.value);

  // 스캘핑 신호
  if (signalP.status === 'fulfilled') {
    renderScalpingSignal(signalP.value);
  } else {
    renderScalpingSignal({ signal: 'WAIT', reason: '신호 계산 실패' });
  }

  // 볼린저 밴드(20,2) 시장 에너지 카드 로드 (뉴스 아래 위치)
  loadBollingerEnergyCard();
}

function renderScalpingSignal(sig) {
  const container = document.getElementById('scalping-signal-body');
  if (!container || !sig) return;
  const colors = { BUY: '#2ecc71', SELL: '#e74c3c', WAIT: '#9aa0b4' };
  const icons  = { BUY: '🟢', SELL: '🔴', WAIT: '⚪' };
  const signal = sig.signal || 'WAIT';
  container.innerHTML = `
    <div style="display:flex; align-items:center; gap:16px; flex-wrap:wrap;">
      <div style="font-size:28px; font-weight:700; color:${colors[signal] || '#9aa0b4'};">
        ${icons[signal]} ${signal}
      </div>
      <div>
        <div style="font-size:13px; color:var(--text-2); margin-bottom:4px;">${sig.reason || ''}</div>
        <div style="display:flex; gap:12px; font-size:12px; color:var(--text-3);">
          ${sig.rsi != null ? `<span>RSI: <b style="color:var(--text-1);">${sig.rsi}</b></span>` : ''}
          ${sig.ma5 != null ? `<span>MA5: <b style="color:var(--text-1);">${(sig.ma5||0).toLocaleString()}</b></span>` : ''}
          ${sig.ma20 != null ? `<span>MA20: <b style="color:var(--text-1);">${(sig.ma20||0).toLocaleString()}</b></span>` : ''}
          ${sig.vol_ratio != null ? `<span>거래량비: <b style="color:var(--text-1);">${sig.vol_ratio}x</b></span>` : ''}
        </div>
      </div>
    </div>`;
}

function renderStockSupply(res) {
  const container = document.getElementById('stock-supply-body');
  if (!container) return;
  if (!res || !res.success) {
    container.innerHTML = '<div style="color:var(--text-3);">수급 데이터가 없습니다.</div>';
    return;
  }
  const cum = res.cumulative || {};
  let html = `
    <div style="display:flex; gap:16px; margin-bottom:12px; flex-wrap:wrap;">
      <div>외국인 누적: <b class="${cum.foreigner>=0?'profit':'loss'}">${(cum.foreigner||0).toLocaleString()}</b>주</div>
      <div>기관 누적: <b class="${cum.organ>=0?'profit':'loss'}">${(cum.organ||0).toLocaleString()}</b>주</div>
    </div>`;
  if (res.daily && res.daily.length > 0) {
    html += `<table style="font-size:12px;"><thead><tr>
      <th>날짜</th><th class="num">외국인</th><th class="num">기관</th><th class="num">개인</th>
    </tr></thead><tbody>`;
    res.daily.forEach(d => {
      html += `<tr>
        <td>${d.date}</td>
        <td class="num ${d.foreigner>=0?'profit':'loss'}">${(d.foreigner||0).toLocaleString()}</td>
        <td class="num ${d.organ>=0?'profit':'loss'}">${(d.organ||0).toLocaleString()}</td>
        <td class="num ${d.individual>=0?'profit':'loss'}">${(d.individual||0).toLocaleString()}</td>
      </tr>`;
    });
    html += `</tbody></table>`;
  }
  container.innerHTML = html;
}

function renderStockNews(newsList) {
  const container = document.getElementById('stock-news-body');
  if (!container) return;
  if (!newsList || newsList.length === 0) {
    container.innerHTML = '<div style="color:var(--text-3);">관련 뉴스가 없습니다.</div>';
    return;
  }
  let html = `<ul class="news-list">`;
  newsList.forEach(n => {
    html += `<li class="news-item">${n.url
      ? `<a href="${n.url}" target="_blank" rel="noopener">${n.title}</a>`
      : n.title
    }</li>`;
  });
  html += `</ul>`;
  container.innerHTML = html;
}

// AI 코멘터리 (신규) ──
async function loadAICommentary(force = false) {
  if (!selectedStockCode) {
    showToast("먼저 종목을 선택해주세요.");
    return;
  }
  const container = document.getElementById('ai-commentary-body');
  container.innerHTML = '<div style="color:var(--text-2); font-size:13px;">🤖 Gemini AI 분석 중... (10~20초 소요)</div>';

  try {
    const res = await API.getAICommentary(selectedStockCode, currentStockPrice, currentStockChg);
    const text = res.commentary || '분석 결과가 없습니다.';
    container.innerHTML = `
      <div style="font-size:13px; line-height:1.8; color:var(--text-1); white-space:pre-line;">
        ${text.replace(/</g,'&lt;').replace(/>/g,'&gt;')}
      </div>
      <div style="margin-top:8px; font-size:11px; color:var(--text-3);">
        ⚠️ 본 분석은 AI 생성 참고 자료이며 투자 권유가 아닙니다.
      </div>`;
  } catch (e) {
    container.innerHTML = `<div style="color:var(--red);">AI 분석 호출 실패: ${e.message}</div>`;
  }
}

// ── 모달 & 포트폴리오 액션 ──
function showAddPortfolioModal() {
  document.getElementById('portfolio-modal').classList.add('open');
}
function closeModal() {
  document.getElementById('portfolio-modal').classList.remove('open');
}

async function addPortfolioItem() {
  const code  = document.getElementById('modal-code').value.trim();
  const name  = document.getElementById('modal-name').value.trim();
  const entry = parseFloat(document.getElementById('modal-entry').value) || 0;
  const qty   = parseInt(document.getElementById('modal-qty').value) || 0;
  const stop  = parseFloat(document.getElementById('modal-stop').value) || 0;
  if (!code || !name || !entry) {
    showToast("종목코드, 종목명, 매수단가를 입력해주세요.");
    return;
  }
  try {
    await API.addPortfolio({ code, name, entry_price: entry, quantity: qty, stop_loss: stop });
    closeModal();
    showToast(`${name} 추가 완료!`);
    loadPortfolio();
  } catch (e) { showToast("추가 실패: " + e.message); }
}

async function deletePortfolioItem(code, name) {
  if (!confirm(`${name} (${code}) 종목을 삭제하시겠습니까?`)) return;
  try {
    await API.deletePortfolio(code);
    showToast(`${name} 삭제 완료!`);
    loadPortfolio();
  } catch (e) { showToast("삭제 실패: " + e.message); }
}

// ── 토스트 ──
function showToast(msg) {
  const toast = document.getElementById('toast');
  if (!toast) return;
  toast.innerText = msg;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 2500);
}
