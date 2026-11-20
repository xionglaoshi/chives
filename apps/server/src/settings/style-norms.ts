import { readFileSync } from 'node:fs';
import { z } from 'zod';

const sample = z.object({
  instrument: z.enum(['style-v2','interview100-card-v1']),
  form: z.enum(['core', 'full']),
  dimensionId: z.string().min(1),
  peerGroup: z.string().trim().min(1),
  period: z.string().trim().min(1),
  source: z.url({protocol: /^https$/}),
  // One count per integer score, from 0 through 100, using the same scoring rules.
  counts: z.array(z.number().int().min(0).max(100_000_000)).length(101),
});
type Sample = z.infer<typeof sample>;

function loadReferenceGroups(): Sample[] {
  try {
    const file = new URL('../../../../presets/style-assessment/norms.json', import.meta.url);
    return z.object({groups: z.array(sample)}).parse(JSON.parse(readFileSync(file, 'utf8'))).groups;
  } catch {
    // A missing or incompatible reference must not interrupt the assessment itself.
    return [];
  }
}

const groups = loadReferenceGroups();

export function referencePosition(dimensionId: string, score: number, form: 'core' | 'full', reference = groups, instrument:Sample['instrument']='style-v2') {
  if (!Number.isFinite(score) || score < 0 || score > 100) return null;
  const group = reference.find(row => row.instrument === instrument && row.dimensionId === dimensionId && row.form === form);
  if (!group) return null;
  const n = group.counts.reduce((sum, count) => sum + count, 0);
  if (n < 100) return null;
  const bin = Math.round(score);
  const lower = group.counts.slice(0, bin).reduce((sum, count) => sum + count, 0);
  const tied = group.counts[bin]!;
  const percentile = Math.round(100 * (lower + tied / 2) / n);
  return {peerGroup: group.peerGroup, n, source: group.source, period: group.period,
    percentile, topPercent: Math.max(1, 100 - percentile)};
}

export const cardPercentile=(id:string,value:number)=>referencePosition(id,value,'full',groups,'interview100-card-v1');
