import { createHash } from 'node:crypto';
import { readdirSync, readFileSync, realpathSync, statSync } from 'node:fs';
import { isAbsolute, join, relative, sep } from 'node:path';

const codePattern = /^\d{6}\.(SH|SZ|BJ)$/;
const dayPattern = /^\d{4}-\d{2}-\d{2}$/;
const idPattern = /^[a-f0-9]{64}$/;

export function readValuationReceipt(data: string, code: string, day: string, id: string) {
  if (!codePattern.test(code) || !dayPattern.test(day) || !idPattern.test(id)) throw new Error('Invalid receipt path');
  const root = realpathSync(data);
  const file = realpathSync(join(root, 'equity-research', 'valuations', code, day, id + '.json'));
  const position = relative(root, file);
  if (isAbsolute(position) || position === '..' || position.startsWith('..' + sep)) {
    throw new Error('Valuation receipt is outside the production workspace');
  }
  const blob = readFileSync(file);
  if (createHash('sha256').update(blob).digest('hex') !== id) throw new Error('Invalid receipt hash');
  const record = JSON.parse(blob.toString('utf8'));
  if (record.code !== code || record.requested_as_of !== day || record.currency !== 'CNY' ||
      !dayPattern.test(record.as_of) || typeof record.model_version !== 'string') throw new Error('Invalid receipt scope');

  const band = record.dynamic ?? record.static;
  if (band != null && !(Number.isFinite(band.low) && Number.isFinite(band.high) && band.low > 0 && band.high >= band.low)) {
    throw new Error('Invalid valuation range');
  }
  const score = record.outlook?.score;
  return {record, estimate: {
    score: typeof score === 'number' && Number.isInteger(score) && Math.abs(score) <= 5 ? score : null,
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
