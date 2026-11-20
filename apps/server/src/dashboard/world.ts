// Tencent quote timestamps are exchange-local wall times (Hong Kong or New York).
const markets = [
  ['r_hkHSI','恒生指数','港股'], ['r_hkHSTECH','恒生科技','港股'], ['r_hkHSCEI','恒生国企','港股'],
  ['usINX','标普500','美股'], ['usIXIC','纳斯达克综合','美股'], ['usDJI','道琼斯工业','美股'],
] as const;

export async function worldIndices() {
  const response = await fetch('https://qt.gtimg.cn/q='+markets.map(([id])=>id).join(','), {
    signal: AbortSignal.timeout(8000),
  });
  if (!response.ok) throw new Error('海外行情暂不可用');
  const raw = new TextDecoder('gb18030').decode(await response.arrayBuffer());
  const records = new Map(Array.from(raw.matchAll(/v_(\w+)="([^"]*)"/g), m=>[m[1],m[2]!.split('~')]));
  const rows = markets.map(([id,name,market])=>{
    const fields = records.get(id) ?? [];
    const valid = Number(fields[3]) > 0 && /^\d{4}[-/]\d{2}[-/]\d{2} /.test(fields[30] ?? '');
    return {name,market,price:valid ? Number(fields[3]) : null,
      changePct:valid && fields[32]?.trim() && Number.isFinite(Number(fields[32])) ? Number(fields[32]) : null,
      time:valid ? fields[30]!.replaceAll('/','-') : null};
  });
  if (!rows.some(r=>r.price!==null)) throw new Error('海外行情暂不可用');
  return {rows};
}
