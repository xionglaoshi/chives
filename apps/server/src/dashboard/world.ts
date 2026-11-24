import type { WorldDashboardDto, WorldIndexDto, WorldMarketStatsDto } from '../api/protocol.js';
import { CoalescedTtlCache } from './cache.js';

const markets = [
  { name: '香港', scanner: 'hongkong', indexes: [
    ['^HSI', '恒生指数', 'r_hkHSI'], ['HSTECH.HK', '恒生科技', 'r_hkHSTECH'], ['^HSCE', '恒生国企', 'r_hkHSCEI'],
  ] },
  { name: '美国', scanner: 'america', indexes: [
    ['^GSPC', '标普500', 'usINX'], ['^IXIC', '纳斯达克综合', 'usIXIC'], ['^DJI', '道琼斯工业', 'usDJI'],
  ] },
  { name: '英国', scanner: 'uk', indexes: [['^FTSE', '富时100', '']] },
  { name: '德国', scanner: 'germany', indexes: [['^GDAXI', '德国DAX', '']] },
  { name: '法国', scanner: 'france', indexes: [['^FCHI', '法国CAC 40', '']] },
  { name: '日本', scanner: 'japan', indexes: [['^N225', '日经225', '']] },
] as const;

const indexCache = new Map<string, CoalescedTtlCache<WorldIndexDto>>();
const statsCache = new Map<string, CoalescedTtlCache<WorldMarketStatsDto>>();
const japanLimitCache = new CoalescedTtlCache<{limitUp: number | null; limitDown: number | null}>(Date.now);
const emptyStats = { volumeShares: null, up: null, down: null, limitUp: null, limitDown: null };

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

async function loadIndex(code: string, name: string, market: string): Promise<WorldIndexDto> {
  const response = await fetch(
    'https://query1.finance.yahoo.com/v8/finance/chart/' + encodeURIComponent(code) + '?range=1d&interval=5m',
    {headers: {'user-agent': 'Mozilla/5.0'}, signal: AbortSignal.timeout(6500)}
  );
  if (!response.ok) throw new Error('Index chart unavailable');
  const payload = await response.json() as {chart?: {result?: Array<{
    meta?: {regularMarketPrice?: number; chartPreviousClose?: number; regularMarketTime?: number};
    indicators?: {quote?: Array<{close?: Array<number | null>}>};
  }>}};
  const result = payload.chart?.result?.[0];
  const meta = result?.meta;
  const price = meta?.regularMarketPrice, previous = meta?.chartPreviousClose;
  if (!finite(price) || price <= 0) throw new Error('Index price unavailable');
  return {
    code, name, market, price,
    changePct: finite(previous) && previous > 0 ? (price / previous - 1) * 100 : null,
    spark: (result?.indicators?.quote?.[0]?.close ?? []).filter(value => finite(value) && value > 0) as number[],
    time: finite(meta?.regularMarketTime) ? new Date(meta.regularMarketTime * 1000).toISOString() : null,
  };
}

async function fallbackQuotes(codes: string[]) {
  const response = await fetch('https://qt.gtimg.cn/q=' + codes.join(','), {signal: AbortSignal.timeout(5000)});
  if (!response.ok) throw new Error('Fallback index quotes unavailable');
  const raw = new TextDecoder('gb18030').decode(await response.arrayBuffer());
  return new Map(Array.from(raw.matchAll(/v_(\w+)="([^"]*)"/g), m => [m[1]!, m[2]!.split('~')]));
}

async function scanStocks(scanner: string, columns: string[]) {
  const response = await fetch('https://scanner.tradingview.com/' + scanner + '/scan', {
    method: 'POST',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify({
      filter: [
        {left: 'type', operation: 'equal', right: 'stock'},
        {left: 'typespecs', operation: 'has', right: ['common']},
        {left: 'is_primary', operation: 'equal', right: true},
        {left: 'volume', operation: 'greater', right: 0},
      ],
      columns,
      range: [0, 10_000],
    }),
    signal: AbortSignal.timeout(7500),
  });
  if (!response.ok) throw new Error('Market breadth unavailable');
  const result = await response.json() as {totalCount?: number; data?: Array<{d: unknown[]}>};
  if (!result.data?.length || result.data.length !== result.totalCount) throw new Error('Incomplete market breadth');

  return result.data;
}

async function loadStats(scanner: string, market: string): Promise<WorldMarketStatsDto> {
  const stocks = await scanStocks(scanner, ['change', 'volume']);
  let volumeShares = 0, volumeCount = 0, changeCount = 0, up = 0, down = 0;
  for (const {d: [change, volume]} of stocks) {
    if (finite(volume) && volume > 0) { volumeShares += volume; volumeCount++; }
    if (!finite(change)) continue;
    changeCount++;
    if (change > 0) up++;
    if (change < 0) down++;
  }
  return {
    ...emptyStats, market,
    volumeShares: volumeCount === stocks.length ? volumeShares : null,
    up: changeCount > 0 ? up : null,
    down: changeCount > 0 ? down : null,
  };
}

const industryNames: Record<string, string> = {
  'Airlines': '航空运输', 'Electrical Products': '电气产品', 'Computer Peripherals': '计算机外设',
  'Medical Specialties': '医疗设备', 'Specialty Telecommunications': '专用通信服务', 'Specialty Stores': '专业零售',
  'Semiconductors': '半导体', 'Major Banks': '大型银行', 'Regional Banks': '区域性银行',
  'Internet Software/Services': '互联网软件与服务', 'Packaged Software': '软件',
  'Investment Banks/Brokers': '投行与券商', 'Real Estate Development': '房地产开发',
  'Finance/Rental/Leasing': '金融与租赁', 'Pharmaceuticals: Major': '大型制药',
  'Pharmaceuticals: Other': '其他制药', 'Biotechnology': '生物技术',
  'Motor Vehicles': '汽车整车', 'Telecommunications Equipment': '通信设备',
  'Electronic Production Equipment': '电子生产设备', 'Electronic Components': '电子元件',
  'Computer Processing Hardware': '计算机硬件', 'Internet Retail': '网络零售',
  'Wireless Telecommunications': '无线通信', 'Multi-Line Insurance': '综合保险',
  'Oil & Gas Production': '油气开采', 'Integrated Oil': '综合石油',
  'Industrial Machinery': '工业机械', 'Metal Fabrication': '金属加工',
  'Other Metals/Minerals': '其他金属与矿产', 'Precious Metals': '贵金属',
  'Electronics Distributors': '电子产品分销', 'Movies/Entertainment': '影视娱乐',
  'Aerospace & Defense': '航空航天与国防', 'Information Technology Services': '信息技术服务',
};

export async function worldIndustries(market: 'hk' | 'us') {
  const currency = market === 'hk' ? 'HKD' : 'USD';
  const stocks = await scanStocks(market === 'hk' ? 'hongkong' : 'america',
    ['description', 'industry', 'change', 'Value.Traded', 'currency']);
  const groups = new Map<string, { count: number; sum: number; amount: number; leader: {name: string; change_pct: number} }>();
  for (const {d: [name, industry, change, amount, quoteCurrency]} of stocks) {
    if (quoteCurrency !== currency || typeof name !== 'string' || typeof industry !== 'string' ||
        !industry || !finite(change) || !finite(amount) || amount <= 0) continue;
    const stock = {name, change_pct: change};
    const group = groups.get(industry) ?? {count: 0, sum: 0, amount: 0, leader: stock};
    group.count++;
    group.sum += change;
    group.amount += amount;
    if (change > group.leader.change_pct) group.leader = stock;
    groups.set(industry, group);
  }
  if (!groups.size) throw new Error('Industry quotes unavailable');
  const rows = [...groups].sort((a, b) => b[1].amount - a[1].amount).slice(0, 12)
    .map(([industry, group]) => ({
      name: industryNames[industry] ?? industry,
      change_pct: group.sum / group.count,
      amount: group.amount,
      leader: group.leader,
    }));
  return {rows, asOf: new Date().toISOString(), stale: false};
}

async function japanLimitCount(direction: 'up' | 'down'): Promise<number> {
  const response = await fetch('https://s.kabutan.jp/warnings/price_limit_' + direction + '/', {
    signal: AbortSignal.timeout(7000),
  });
  if (!response.ok) throw new Error('Japan price-limit table unavailable');
  const html = await response.text();
  const stockLinks = [...html.matchAll(/<a\b[^>]*class="[^"]*\bstockPopup\b[^"]*"[^>]*href="\/stocks\/([0-9A-Z]+)\/"[^>]*>([\s\S]*?)<\/a>/g)];
  if (!stockLinks.length) throw new Error('Japan price-limit table missing');
  const color = direction === 'up' ? 'red' : 'blue';
  const atLimit = new RegExp('<span class="text-' + color + ' [^"]*">Ｓ</span>');
  return new Set(stockLinks.filter(([, , row]) =>
    />東[PSG]<\/span>/.test(row ?? '') && atLimit.test(row ?? '')
  ).map(([, code]) => code)).size;
}

export async function worldIndices(): Promise<WorldDashboardDto> {
  const symbols = markets.flatMap(({name: market, indexes}) => indexes.map(([code, name, fallback]) => ({code, name, fallback, market})));
  const [quotes, stats, japanLimits] = await Promise.all([
    Promise.allSettled(symbols.map(({code, name, market}) => {
      const cache = indexCache.get(code) ?? new CoalescedTtlCache<WorldIndexDto>(Date.now);
      indexCache.set(code, cache);
      return cache.get(120_000, () => loadIndex(code, name, market));
    })),
    Promise.all(markets.map(async ({name, scanner}) => {
      const cache = statsCache.get(scanner) ?? new CoalescedTtlCache<WorldMarketStatsDto>(Date.now);
      statsCache.set(scanner, cache);
      try { return await cache.get(180_000, () => loadStats(scanner, name)); }
      catch { return {market: name, ...emptyStats}; }
    })),
    japanLimitCache.get(180_000, async () => {
      const [up, down] = await Promise.allSettled([japanLimitCount('up'), japanLimitCount('down')]);
      if (up.status === 'rejected' && down.status === 'rejected') throw up.reason;
      return {limitUp: up.status === 'fulfilled' ? up.value : null, limitDown: down.status === 'fulfilled' ? down.value : null};
    }).catch(() => ({limitUp: null, limitDown: null})),
  ]);

  const missing = symbols.flatMap(({fallback}, i) => fallback && quotes[i]?.status === 'rejected' ? [fallback] : []);
  const fallback = missing.length ? await fallbackQuotes(missing).catch(() => undefined) : undefined;
  const rows = symbols.map(({code, name, market, fallback: symbol}, i) => {
    const quote = quotes[i];
    if (quote?.status === 'fulfilled') return quote.value;
    const fields = fallback?.get(symbol);
    const price = Number(fields?.[3]);
    const changePct = fields?.[32]?.trim() ? Number(fields[32]) : NaN;
    return {code, name, market, price: price > 0 ? price : null,
      changePct: finite(changePct) ? changePct : null, time: fields?.[30] ?? null, spark: []};
  });
  if (!rows.some(row => row.price !== null) && stats.every(market => market.volumeShares === null)) {
    throw new Error('海外行情暂不可用');
  }
  return {rows, stats: stats.map(row => row.market === '日本' ? {...row, ...japanLimits} : row)};
}
