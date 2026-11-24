import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

const codePattern = /^\d{6}\.(SH|SZ|BJ)$/;
const dayPattern = /^\d{4}-\d{2}-\d{2}$/;
const idPattern = /^[a-f0-9]{64}$/;

export function readValuationReceipt(data: string, code: string, day: string, id: string) {
  if (!codePattern.test(code) || !dayPattern.test(day) || !idPattern.test(id)) throw new Error('Invalid receipt path');
  const blob = readFileSync(join(data, 'equity-research', 'valuations', code, day, id + '.json'));
  if (createHash('sha256').update(blob).digest('hex') !== id) throw new Error('Invalid receipt hash');
  const record = JSON.parse(blob.toString('utf8'));
  if (record.code !== code || record.requested_as_of !== day || record.currency !== 'CNY' ||
      !dayPattern.test(record.as_of) || typeof record.model_version !== 'string') throw new Error('Invalid receipt scope');

  const band = record.dynamic ?? record.static;
  if (band != null && !(Number.isFinite(band.low) && Number.isFinite(band.high) && band.low > 0 && band.high >= band.low)) {
    throw new Error('Invalid valuation range');
  }
  return {record, estimate: {
    low: band?.low ?? null, high: band?.high ?? null,
    valuationKind: record.dynamic ? '动态估值' as const : record.static ? '静态参考' as const : '依据不足' as const,
  }};
}

export type HoldingValuation = ReturnType<typeof readValuationReceipt>['estimate'];

function readNames(path: string): string[] {
  try { return readdirSync(path); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [];
    throw error;
  }
}

export function latestHoldingValuation(data: string, code: string, today: string): HoldingValuation | undefined {
  if (!codePattern.test(code)) return undefined;
  const root = join(data, 'equity-research', 'valuations', code);
  const days = readNames(root).filter(day => dayPattern.test(day) && day <= today).sort().reverse();
  for (const day of days) {
    const directory = join(root, day);
    const candidates = readNames(directory).filter(name => idPattern.test(name.slice(0,-5)) && name.endsWith('.json'));
    const ordered = candidates.map(name => ({name, stamp:statSync(join(directory, name), {throwIfNoEntry:false})?.mtimeMs ?? 0}))
      .sort((a,b) => b.stamp - a.stamp);
    for (const {name} of ordered) {
      try { return readValuationReceipt(data, code, day, name.slice(0,-5)).estimate; }
      catch { /* Skip incomplete or invalid receipts. */ }
    }
  }
  return undefined;
}

export function measureHoldingValuation(python: string, root: string, data: string, code: string, day: string): Promise<HoldingValuation> {
  return new Promise((resolve, reject) => {
    execFile(python, ['-c', 'import sys; from equity_evidence.valuation import estimate_equity_value; print(estimate_equity_value(*sys.argv[1:])["valuation_id"])', code, day], {
      cwd: root, env: {...process.env, CHIVES_RESEARCH_LIBRARY:join(data,'equity-research')}, timeout:120_000,
    }, (error, stdout) => {
      if (error) { reject(error); return; }
      try { resolve(readValuationReceipt(data, code, day, stdout.trim().split('\n').at(-1)!).estimate); }
      catch (failure) { reject(failure); }
    });
  });
}
