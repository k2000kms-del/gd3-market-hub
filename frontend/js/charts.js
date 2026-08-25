/* ══════════════════════════════════════════════
   GD3 Market Hub — Plotly 차트 모듈 (charts.js)
   클라이언트 브라우저 GPU를 통한 고속 차트 렌더링
   ══════════════════════════════════════════════ */

const Charts = {
  // 다크 테마 공통 Layout
  commonLayout: {
    paper_bgcolor: '#161a22',
    plot_bgcolor: '#161a22',
    font: { family: 'Pretendard, sans-serif', color: '#eaeaea', size: 11 },
    margin: { l: 45, r: 20, t: 30, b: 30 },
    showlegend: true,
    legend: { orientation: 'h', y: 1.1, x: 0, font: { size: 10 } },
    xaxis: {
      gridcolor: '#2a2f3d',
      zerolinecolor: '#2a2f3d',
      showgrid: true,
    },
    yaxis: {
      gridcolor: '#2a2f3d',
      zerolinecolor: '#2a2f3d',
      showgrid: true,
      side: 'right'
    }
  },

  // ── 1. 수급 추이 차트 ──
  renderSupplyChart(elementId, dailyData, marketName = '코스피') {
    if (!dailyData || dailyData.length === 0) return;

    const dates = dailyData.map(d => d.date);
    const foreigner = dailyData.map(d => d.foreigner || 0);
    const organ = dailyData.map(d => d.organ || 0);
    const individual = dailyData.map(d => d.individual || 0);

    const traceFgn = {
      x: dates, y: foreigner, name: '외국인', type: 'bar',
      marker: { color: '#e74c3c' }
    };
    const traceOrg = {
      x: dates, y: organ, name: '기관', type: 'bar',
      marker: { color: '#6c63ff' }
    };
    const traceInd = {
      x: dates, y: individual, name: '개인', type: 'bar',
      marker: { color: '#2ecc71' }
    };

    const layout = {
      ...this.commonLayout,
      barmode: 'group',
      title: { text: `${marketName} 최근 일별 수급 (억원)`, font: { size: 13, color: '#9aa0b4' } }
    };

    Plotly.react(elementId, [traceFgn, traceOrg, traceInd], layout, { responsive: true, displayModeBar: false });
  },

  // ── 2. 개별 종목 일봉 차트 (Candlestick + MA5, MA20, MA60) ──
  renderDailyChart(elementId, historyData, stockName) {
    if (!historyData || historyData.length === 0) {
      document.getElementById(elementId).innerHTML = '<div style="color:#5c6277; text-align:center; padding-top:100px;">일봉 데이터가 없습니다.</div>';
      return;
    }

    const dates = historyData.map(d => d.Date);
    const opens = historyData.map(d => d.Open);
    const highs = historyData.map(d => d.High);
    const lows = historyData.map(d => d.Low);
    const closes = historyData.map(d => d.Close);
    const ma5 = historyData.map(d => d.MA5);
    const ma20 = historyData.map(d => d.MA20);
    const ma60 = historyData.map(d => d.MA60);

    const candleTrace = {
      x: dates, open: opens, high: highs, low: lows, close: closes,
      type: 'candlestick',
      name: '주가',
      increasing: { line: { color: '#e74c3c' }, fillcolor: '#e74c3c' },
      decreasing: { line: { color: '#2ecc71' }, fillcolor: '#2ecc71' }
    };

    const traceMA5 = { x: dates, y: ma5, name: 'MA5', type: 'scatter', mode: 'lines', line: { color: '#f1c40f', width: 1.2 } };
    const traceMA20 = { x: dates, y: ma20, name: 'MA20', type: 'scatter', mode: 'lines', line: { color: '#e67e22', width: 1.2 } };
    const traceMA60 = { x: dates, y: ma60, name: 'MA60', type: 'scatter', mode: 'lines', line: { color: '#9b59b6', width: 1.2 } };

    const layout = {
      ...this.commonLayout,
      xaxis: { ...this.commonLayout.xaxis, rangeslider: { visible: false } },
      margin: { l: 20, r: 50, t: 30, b: 30 }
    };

    Plotly.react(elementId, [candleTrace, traceMA5, traceMA20, traceMA60], layout, { responsive: true, displayModeBar: false });
  },

  // ── 3. 개별 종목 1분봉 차트 ──
  renderMinuteChart(elementId, minuteData, stockName) {
    if (!minuteData || minuteData.length === 0) {
      document.getElementById(elementId).innerHTML = '<div style="color:#5c6277; text-align:center; padding-top:100px;">데이터를 불러오는 중...<br><small>KIS API 키가 없으면 네이버 1분봉 사용</small></div>';
      return;
    }

    const times = minuteData.map(d => d.Time);
    const opens = minuteData.map(d => d.Open);
    const highs = minuteData.map(d => d.High);
    const lows = minuteData.map(d => d.Low);
    const closes = minuteData.map(d => d.Close);

    const candleTrace = {
      x: times, open: opens, high: highs, low: lows, close: closes,
      type: 'candlestick',
      name: '1분봉',
      increasing: { line: { color: '#e74c3c' }, fillcolor: '#e74c3c' },
      decreasing: { line: { color: '#2ecc71' }, fillcolor: '#2ecc71' }
    };

    const layout = {
      ...this.commonLayout,
      xaxis: { ...this.commonLayout.xaxis, rangeslider: { visible: false } },
      margin: { l: 20, r: 50, t: 30, b: 30 }
    };

    Plotly.react(elementId, [candleTrace], layout, { responsive: true, displayModeBar: false });
  },

  // ── 4. 수급 Treemap (Panel 1) ──
  renderSupplyTreemap(elementId, supplyData) {
    const el = document.getElementById(elementId);
    if (!supplyData || supplyData.length === 0) {
      el.innerHTML = '<div style="color:#5c6277; text-align:center; padding-top:100px;">수급 데이터 로딩 중...</div>';
      return;
    }

    const names   = supplyData.map(d => d.Name || d.Code || '');
    const parents = supplyData.map(() => '');
    const values  = supplyData.map(d => Math.abs(parseFloat(d.Total_Combined_Net || d.net || 0)) + 1);
    const netVals = supplyData.map(d => parseFloat(d.Total_Combined_Net || d.net || 0));
    const maxAbs  = Math.max(...netVals.map(Math.abs), 1);
    const colors  = netVals.map(v => {
      const ratio = v / maxAbs;
      if (ratio > 0) return `rgba(231,76,60,${0.3 + 0.7 * ratio})`;
      return `rgba(46,204,113,${0.3 + 0.7 * Math.abs(ratio)})`;
    });

    const trace = {
      type: 'treemap',
      labels: names,
      parents: parents,
      values: values,
      marker: { colors: colors, line: { width: 1, color: '#0d0f14' } },
      textinfo: 'label+text',
      text: netVals.map(v => `${v > 0 ? '+' : ''}${v.toLocaleString()}`),
      hovertemplate: '<b>%{label}</b><br>수급: %{text}<extra></extra>',
    };

    const layout = {
      ...this.commonLayout,
      margin: { l: 0, r: 0, t: 10, b: 0 }
    };

    Plotly.react(elementId, [trace], layout, { responsive: true, displayModeBar: false });
  },

  // ── 5. 퀀트 수평 Bar Chart (Panel 2) ──
  renderQuantBarChart(elementId, quantList) {
    if (!quantList || quantList.length === 0) return;
    const scoreKey = quantList[0].T_Score_Adj !== undefined ? 'T_Score_Adj' : (quantList[0].T_Score !== undefined ? 'T_Score' : 'Quant_Score');
    const names  = quantList.map(d => d.Name || '').reverse();
    const tScore = quantList.map(d => parseFloat(d[scoreKey] || 0)).reverse();
    const sScore = quantList.map(d => parseFloat(d.S_Score || 0)).reverse();

    const traceT = {
      y: names, x: tScore, name: '툀트점수',
      type: 'bar', orientation: 'h',
      marker: { color: '#6c63ff', opacity: 0.85 },
      hovertemplate: '<b>%{y}</b><br>툀트: %{x:.1f}점<extra></extra>'
    };
    const traceS = {
      y: names, x: sScore, name: '수급점수',
      type: 'bar', orientation: 'h',
      marker: { color: '#2ecc71', opacity: 0.7 },
      hovertemplate: '<b>%{y}</b><br>수급: %{x:.1f}점<extra></extra>'
    };

    const layout = {
      ...this.commonLayout,
      barmode: 'group',
      margin: { l: 100, r: 30, t: 20, b: 30 },
      xaxis: { ...this.commonLayout.xaxis, side: 'bottom' },
      yaxis: { ...this.commonLayout.yaxis, side: 'left', automargin: true }
    };
    Plotly.react(elementId, [traceT, traceS], layout, { responsive: true, displayModeBar: false });
  },

  // ── 6. 거래대금 리더 적층 Bar (Panel 3) ──
  renderVolumeLeadersChart(elementId, leaderData) {
    const el = document.getElementById(elementId);
    if (!leaderData || leaderData.length === 0) {
      el.innerHTML = '<div style="color:#5c6277; text-align:center; padding-top:80px;">데이터 로딩 중...</div>';
      return;
    }
    const sorted  = [...leaderData].sort((a, b) => parseFloat(a.total_amount) - parseFloat(b.total_amount));
    const names   = sorted.map(d => d.Name || '');
    const buyVis  = sorted.map(d => parseFloat(d.buy_visual || 0));
    const sellVis = sorted.map(d => parseFloat(d.sell_visual || 0));
    const customData = sorted.map(d => [
      d.Code, parseFloat(d.Close||0), parseFloat(d.ChagesRatio||0),
      parseFloat(d.total_amount||0), parseFloat(d.buy_amount||0), parseFloat(d.sell_amount||0)
    ]);

    const traceBuy = {
      y: names, x: buyVis, name: '매수 대금',
      type: 'bar', orientation: 'h',
      marker: { color: '#ff6b6b', line: { color: 'rgba(255,255,255,0.08)', width: 1 } },
      customdata: customData,
      hovertemplate: '<b>%{y}</b> (%{customdata[0]})<br>옵 %{customdata[3]:,.0f}억원<br>거래대금 %{customdata[4]:,.0f}억 매수<extra></extra>'
    };
    const traceSell = {
      y: names, x: sellVis, name: '매도 대금',
      type: 'bar', orientation: 'h',
      marker: { color: '#4e9ff5', line: { color: 'rgba(255,255,255,0.08)', width: 1 } },
      text: sorted.map(d => ` ${parseFloat(d.total_amount||0).toFixed(0)}억`),
      textposition: 'outside',
      customdata: customData,
      hovertemplate: '<b>%{y}</b> (%{customdata[0]})<br>옅 %{customdata[3]:,.0f}억원<br>거래대금 %{customdata[5]:,.0f}억 매도<extra></extra>'
    };

    const maxX = Math.max(...sorted.map(d => parseFloat(d.buy_visual||0) + parseFloat(d.sell_visual||0)), 1);
    const layout = {
      ...this.commonLayout,
      barmode: 'stack',
      showlegend: false,
      margin: { l: 100, r: 70, t: 10, b: 20 },
      xaxis: { ...this.commonLayout.xaxis, range: [0, maxX * 1.3], side: 'bottom' },
      yaxis: { ...this.commonLayout.yaxis, side: 'left', automargin: true }
    };
    Plotly.react(elementId, [traceBuy, traceSell], layout, { responsive: true, displayModeBar: false });
  },

  // ── 7. 상승률 리더 Bar (Panel 6) ──
  renderChangeLeadersChart(elementId, leaderData) {
    const el = document.getElementById(elementId);
    if (!leaderData || leaderData.length === 0) {
      el.innerHTML = '<div style="color:#5c6277; text-align:center; padding-top:80px;">데이터 로딩 중...</div>';
      return;
    }
    const sorted   = [...leaderData].sort((a, b) => parseFloat(a.ChagesRatio) - parseFloat(b.ChagesRatio));
    const names    = sorted.map(d => d.Name || '');
    const chgRatio = sorted.map(d => parseFloat(d.ChagesRatio || 0));
    const colors   = chgRatio.map(v => v >= 0 ? '#e74c3c' : '#2ecc71');
    const customData = sorted.map(d => [d.Code, parseFloat(d.Close||0), parseInt(d.Volume||0)]);

    const trace = {
      y: names, x: chgRatio, name: '등락률',
      type: 'bar', orientation: 'h',
      marker: { color: colors, line: { color: 'rgba(255,255,255,0.08)', width: 1 } },
      text: chgRatio.map(v => ` ${v > 0 ? '+' : ''}${v.toFixed(2)}%`),
      textposition: 'outside',
      customdata: customData,
      hovertemplate: '<b>%{y}</b> (%{customdata[0]})<br>등락률: %{text}<br>현재가: %{customdata[1]:,}원<extra></extra>'
    };

    const maxX = Math.max(...chgRatio.map(Math.abs), 1);
    const layout = {
      ...this.commonLayout,
      showlegend: false,
      margin: { l: 100, r: 70, t: 10, b: 20 },
      xaxis: { ...this.commonLayout.xaxis, range: [0, maxX * 1.3], side: 'bottom' },
      yaxis: { ...this.commonLayout.yaxis, side: 'left', automargin: true }
    };
    Plotly.react(elementId, [trace], layout, { responsive: true, displayModeBar: false });
  },

  // ── 8. 볼린저 밴드(20,2) 돌파 종목 수 + 5일 MA 콤보 차트 ──
  renderBollingerEnergyChart(elementId, historyData) {
    const el = document.getElementById(elementId);
    if (!historyData || historyData.length === 0) {
      el.innerHTML = '<div style="color:#5c6277; text-align:center; padding-top:80px;">에너지 데이터 로딩 중...</div>';
      return;
    }

    const dates  = historyData.map(d => d.date.slice(5));
    const counts = historyData.map(d => d.break_count);
    const ma5s   = historyData.map(d => d.ma5);

    const traceBar = {
      x: dates, y: counts, name: '당일 돌파 수',
      type: 'bar',
      marker: { color: 'rgba(108, 99, 255, 0.65)', line: { color: '#6c63ff', width: 1 } },
      hovertemplate: '<b>%{x}</b><br>당일 돌파: <b>%{y}개</b><extra></extra>'
    };

    const traceLine = {
      x: dates, y: ma5s, name: '5일 이동평균',
      type: 'scatter', mode: 'lines+markers',
      line: { color: '#ff6b6b', width: 3, shape: 'spline' },
      marker: { size: 6, color: '#ff6b6b' },
      hovertemplate: '<b>%{x}</b><br>5일 MA: <b>%{y:.1f}개</b><extra></extra>'
    };

    // 기준선 20(강세) 및 10(위험)
    const layout = {
      ...this.commonLayout,
      showlegend: true,
      legend: { orientation: 'h', x: 0, y: 1.15, font: { color: '#a0a5b5', size: 11 } },
      margin: { l: 30, r: 20, t: 30, b: 30 },
      xaxis: { ...this.commonLayout.xaxis, type: 'category' },
      yaxis: { ...this.commonLayout.yaxis, side: 'left' },
      shapes: [
        { type: 'line', x0: 0, x1: 1, y0: 20, y1: 20, xref: 'paper', line: { color: '#e74c3c', width: 1.5, dash: 'dash' } },
        { type: 'line', x0: 0, x1: 1, y0: 10, y1: 10, xref: 'paper', line: { color: '#f39c12', width: 1.5, dash: 'dash' } }
      ]
    };

    Plotly.react(elementId, [traceBar, traceLine], layout, { responsive: true, displayModeBar: false });
  }
};
