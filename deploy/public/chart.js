(async function () {
  const chart = document.querySelector('#chart');
  const value = document.querySelector('#value');
  const date = document.querySelector('#quotedate');
  async function fetchSnapshot() {
    const response = await fetch('/chives/entry/csi300.json', {cache: 'no-store'});
    if (!response.ok) throw Error('index unavailable');
    const snapshot = await response.json();
    if (snapshot.symbol !== '000300' || !Array.isArray(snapshot.points) || snapshot.points.length < 2) throw Error('invalid index');
    return snapshot;
  }
  let points, prices, last, low, high;
  function setSeries(snapshot) {
    points = snapshot.points;
    prices = points.map(point => point[1]);
    last = points.length - 1;
    low = Math.floor(Math.min(...prices) / 100) * 100;
    high = Math.ceil(Math.max(...prices) / 100) * 100;
    document.querySelector('#chart-range').textContent = points[0][0] + ' — ' + points[last][0];
    document.querySelector('#chart-source').textContent = '日收盘 · ' + (snapshot.sourceName ?? '新浪财经');
  }
  setSeries(await fetchSnapshot());
  const format = new Intl.NumberFormat('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const replay = 20000;
  const hold = 2800;
  let elapsed = 0, previous = null, frame = 0, inspected = null, displayed = null;
  let plotWidth, plotHeight, clip, cursor, dot, halo;
  const x = i => 4 + plotWidth * i / last;
  const y = price => 10 + plotHeight * (high - price) / (high - low || 1);
  function svg(tag, attributes, parent = chart) {
    const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [name, v] of Object.entries(attributes)) element.setAttribute(name, v);
    parent.append(element);
    return element;
  }
  function paint() {
    const playhead = inspected ?? (reduced.matches ? last : Math.min(elapsed / replay, 1) * last);
    const i = Math.floor(playhead);
    const fraction = playhead - i;
    const px = x(playhead);
    const py = y(prices[i] + fraction * (prices[Math.min(last, i + 1)] - prices[i]));
    clip.setAttribute('width', inspected === null ? px + 0.5 : chart.clientWidth);
    cursor.setAttribute('x1', px);
    cursor.setAttribute('x2', px);
    cursor.setAttribute('opacity', inspected === null ? 0 : 1);
    for (const node of [dot, halo]) {
      node.setAttribute('cx', px);
      node.setAttribute('cy', py);
    }
    if (displayed !== i) {
      value.textContent = format.format(prices[i]);
      date.textContent = points[i][0] + ' 收盘';
      displayed = i;
    }
  }
  function layout() {
    const w = chart.clientWidth, h = chart.clientHeight;
    plotWidth = Math.max(1, w - 55);
    plotHeight = Math.max(1, h - 23);
    chart.replaceChildren();
    chart.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
    const defs = svg('defs', {});
    const reveal = svg('clipPath', {id: 'market-replay'}, defs);
    clip = svg('rect', {x: 0, y: 0, height: h}, reveal);
    for (let tick = 0; tick <= 4; tick++) {
      const n = Math.round(low + (high - low) * tick / 4);
      svg('line', {x1: 3, x2: w-50, y1: y(n), y2: y(n), stroke: '#e4e9e6', 'stroke-dasharray': '2 5'});
      svg('text', {x: w-41, y: y(n)+3, fill: '#75827b', 'font-size': 10, 'font-family': 'monospace'}).textContent = n;
    }
    const line = prices.map((p,i) => (i ? 'L' : 'M') + x(i).toFixed(2) + ' ' + y(p).toFixed(2)).join(' ');
    svg('path', {d: line, fill: 'none', stroke: '#b7c5bc', 'stroke-width': 1, 'stroke-dasharray': '2 3'});
    const active = svg('g', {'clip-path': 'url(#market-replay)'});
    const dots = [];
    const stride = Math.max(1, Math.ceil(last * 7 / plotWidth));
    for (let i=0; i<=last; i+=stride) {
      dots.push('M'+x(i).toFixed(1)+' '+(y(prices[i])+5).toFixed(1)+'V'+(h-10));
    }
    svg('path', {d:dots.join(' '), fill:'none', stroke:'#d5dfd9', 'stroke-width':1.3, 'stroke-dasharray':'0.3 5', 'stroke-linecap':'round'}, active);
    svg('path', {d:line, fill:'none', stroke:'#456957', 'stroke-width':1.6, 'stroke-linejoin':'round'}, active);
    cursor = svg('line', {y1:5, y2:h-10, stroke:'#8b9e93', 'stroke-dasharray':'3 4'});
    halo = svg('circle', {r:8, fill:'#416653', opacity:0.12});
    dot = svg('circle', {r:3.5, fill:'#345b45', stroke:'white', 'stroke-width':1});
    paint();
  }
  function tick(now) {
    if (previous !== null) elapsed = (elapsed + now - previous) % (replay + hold);
    previous = now;
    paint();
    frame = requestAnimationFrame(tick);
  }
  function playback() {
    cancelAnimationFrame(frame);
    previous = null;
    paint();
    if (!document.hidden && !reduced.matches && inspected === null) frame = requestAnimationFrame(tick);
  }
  function inspect(i) {
    inspected = Math.max(0, Math.min(last, i));
    playback();
  }
  function resume() {
    if (inspected === null) return;
    elapsed = replay * inspected / last;
    inspected = null;
    playback();
  }
  function pointAt(event) {
    inspect(Math.round((event.clientX - chart.getBoundingClientRect().left - 4) * last / plotWidth));
  }
  chart.addEventListener('pointerenter', pointAt);
  chart.addEventListener('pointermove', pointAt);
  chart.addEventListener('pointerdown', pointAt);
  chart.addEventListener('pointerleave', resume);
  chart.addEventListener('pointercancel', resume);
  chart.addEventListener('focus', () => { if (inspected === null) inspect(displayed ?? last); });
  chart.addEventListener('blur', resume);
  chart.addEventListener('keydown', event => {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    event.preventDefault();
    inspect(event.key === 'Home' ? 0 : event.key === 'End' ? last : (inspected ?? displayed) + (event.key === 'ArrowLeft' ? -1 : 1));
  });
  layout();
  new ResizeObserver(layout).observe(chart);
  reduced.addEventListener('change', playback);
  let checkedAt = Date.now();
  let fetching = false;
  async function refreshIfDue() {
    if (document.hidden || fetching || Date.now() - checkedAt < 15 * 60 * 1000) return;
    checkedAt = Date.now();
    fetching = true;
    try {
      const snapshot = await fetchSnapshot();
      if (snapshot.points.at(-1)[0] <= points[last][0]) return;
      const selectedDay = inspected === null ? null : points[inspected][0];
      setSeries(snapshot);
      if (selectedDay !== null) inspected = Math.max(0, points.findIndex(p => p[0] === selectedDay));
      displayed = null;
      layout();
    } catch {
      // Keep the displayed history and retry on the next check.
    } finally {
      fetching = false;
    }
  }
  setInterval(refreshIfDue, 15 * 60 * 1000);
  document.addEventListener('visibilitychange', () => { playback(); refreshIfDue(); });
  playback();
})().catch(() => { document.querySelector('#chart').replaceWith('走势数据暂不可用'); });

// A decorative layer, independent of the index request and the login form.
(() => {
  const rain = document.createElement('div');
  rain.className = 'code-rain';
  rain.setAttribute('aria-hidden', 'true');
  const streams = [
    '0x3A01F', '0110[]8D1', 'F2=0.31', '01C4+A0B', '4E01::3',
    '10>A02', '0xF1_908', '20A1{F}', '1E01:B3', '001D+9',
    '0xCE1=2', '11A0<>7C', '0F+101', '8B0::12A',
    '0x2F1B', 'A9F0:7C', '01D+9E0', '31{A}02', 'F0C1.70',
    '1D::B08', 'E0A3_2', '7A+0101', '0xFF19', '0024[A]',
    '9D01:C', '10B0<>4', 'A1.E03', '6E0::B2'
  ];
  for (const text of streams) {
    const strand = document.createElement('span');
    strand.textContent = text;
    rain.append(strand);
  }
  document.body.prepend(rain);
})();
