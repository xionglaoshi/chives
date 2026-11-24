import { createHash, randomUUID } from 'node:crypto';
import { mkdir, mkdtemp, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import type { HoldingValuation } from './holding-valuations.js';

type Entry = { path: string; sha256: string };
type Catalog = { schema: 2; publishedAt: string; files: Entry[] };
type StockProfile = { code: string; name?: string; asOf?: string; analysis?: string; strategy?: string; valuation?: HoldingValuation | null };
type Snapshot = { hotspots: Record<string, unknown> | null; valuations: Record<string, HoldingValuation>; stockProfiles: Record<string, StockProfile> };

function validValuation(value: HoldingValuation): boolean {
  const {low, high, score, valuationKind} = value;
  return ['动态估值', '静态参考', '依据不足'].includes(valuationKind)
    && (low === null && high === null || typeof low === 'number' && typeof high === 'number'
      && Number.isFinite(low) && Number.isFinite(high) && low > 0 && high >= low)
    && (score === null || Number.isInteger(score) && Math.abs(score) <= 5);
}

function parseCatalog(bytes: Buffer): Catalog {
  const catalog = JSON.parse(bytes.toString('utf8')) as Catalog;
  if (catalog.schema !== 2 || !Array.isArray(catalog.files) || typeof catalog.publishedAt !== 'string'
      || catalog.files.some(entry => !/^[a-z][a-z0-9-]*\/[a-zA-Z0-9][a-zA-Z0-9._-]*\.json$/.test(entry.path)
        || !/^[a-f0-9]{64}$/.test(entry.sha256)
        || entry.path.startsWith('stocks/') && !/^stocks\/\d{6}\.(SH|SZ|BJ)\.json$/.test(entry.path))
      || new Set(catalog.files.map(entry => entry.path)).size !== catalog.files.length) {
    throw new Error('Invalid featured data catalog');
  }
  return catalog;
}

class FeatureAccessDenied extends Error {}

async function download(url: URL) {
  const response = await fetch(url, { redirect: 'error', signal: AbortSignal.timeout(8000) });
  if (response.status === 401 || response.status === 403) throw new FeatureAccessDenied();
  if (!response.ok || !response.body) throw new Error('Featured data download failed');
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    for (;;) {
      const chunk = await reader.read();
      if (chunk.done) return Buffer.concat(chunks, size);
      size += chunk.value.byteLength;
      if (size > 32 * 1024 * 1024) throw new Error('Featured data exceeds its size limit');
      chunks.push(chunk.value);
    }
  } finally {
    await reader.cancel();
  }
}

function matches(bytes: Buffer | undefined, entry: Entry): bytes is Buffer {
  return !!bytes && createHash('sha256').update(bytes).digest('hex') === entry.sha256;
}

async function atomicWrite(path: string, bytes: Buffer) {
  await mkdir(dirname(path), { recursive: true });
  const temporary = path + '.' + randomUUID() + '.tmp';
  try {
    await writeFile(temporary, bytes, { flag: 'wx' });
    await rename(temporary, path);
  } finally {
    await rm(temporary, { force: true });
  }
}

export function featureDataService(endpoint: string, cache: string) {
  const base = new URL(endpoint.endsWith('/') ? endpoint : endpoint + '/');
  const catalogPath = join(cache, 'catalog.json');
  const denialPath = join(cache, '.access-denied');
  const sourcePath = join(cache, '.source');
  const sourceId = createHash('sha256').update(base.href).digest('hex');
  let denied = false;
  let snapshot: Snapshot | null = null;
  let refreshed = 0;
  let pending: Promise<Snapshot | null> | undefined;

  async function readRelease(catalog: Catalog, staging?: string, reuse = true) {
    const changed: string[] = [];
    const boards: Record<string, unknown> = {};
    const retained: string[] = [];
    const valuations: Record<string, HoldingValuation> = {};
    const stockProfiles: Record<string, StockProfile> = {};
    for (let offset = 0; offset < catalog.files.length; offset += 12) {
      const results = await Promise.allSettled(catalog.files.slice(offset, offset + 12).map(async entry => {
        const path = join(cache, entry.path);
        let bytes = reuse ? await readFile(path).catch(() => undefined) : undefined;
        const dirty = !matches(bytes, entry);
        if (dirty && staging) bytes = await download(new URL(entry.path, base));
        if (!matches(bytes, entry)) throw new Error('Invalid featured object checksum');
        const object = JSON.parse(bytes.toString('utf8'));
        const id = entry.path.slice(entry.path.indexOf('/') + 1, -5);
        if (entry.path.startsWith('rankings/')) {
          if (object.id !== id || !Array.isArray(object.board?.rows)) throw new Error('Invalid ranking');
          boards[id] = object.board;
          if (object.retained) retained.push(id);
        } else if (entry.path.startsWith('stocks/')) {
          if (object.code !== id) throw new Error('Invalid stock profile');
          if (object.valuation) {
            if (!validValuation(object.valuation)) throw new Error('Invalid stock valuation');
            valuations[id] = object.valuation;
          }
          stockProfiles[id] = object;
        }
        if (dirty && staging) {
          await atomicWrite(join(staging,entry.path), bytes);
          changed.push(entry.path);
        }
      }));
      for (const result of results) {
        if (result.status === 'rejected') throw result.reason;
      }
    }
    // Preserve publication order even when file reads finish out of order.
    const ordered = Object.fromEntries(catalog.files.filter(entry => entry.path.startsWith('rankings/'))
      .map(entry => entry.path.slice('rankings/'.length, -5)).map(id => [id, boards[id]]));
    const release = { hotspots: Object.keys(ordered).length ? {schema: 1, publishedAt: catalog.publishedAt, boards: ordered, retained} : null, valuations, stockProfiles };
    return {release,changed};
  }

  async function refresh(): Promise<Snapshot | null> {
    const previous = await readFile(catalogPath).then(parseCatalog).catch(() => undefined);
    const sameSource = await readFile(sourcePath,'utf8').then(value=>value===sourceId,()=>false);
    if (!snapshot && !denied) denied = await readFile(denialPath,'utf8').then(value=>value===sourceId,()=>false);
    if (!snapshot && !denied && sameSource && previous) snapshot = await readRelease(previous).then(result=>result.release).catch(() => null);
    let staging: string | undefined;
    try {
      const bytes = await download(new URL('catalog.json', base));
      const next = parseCatalog(bytes);
      await mkdir(cache,{recursive:true});
      staging = await mkdtemp(join(cache,'.incoming-'));
      const {release,changed} = await readRelease(next, staging, sameSource);
      for (const path of changed) {
        const target=join(cache,path);
        await mkdir(dirname(target),{recursive:true});
        await rename(join(staging,path), target);
      }
      await atomicWrite(catalogPath, bytes);
      await atomicWrite(sourcePath, Buffer.from(sourceId));
      await rm(denialPath,{force:true});
      denied = false;
      snapshot = release;
      const currentPaths = new Set(next.files.map(entry => entry.path));
      for (const entry of previous?.files ?? []) {
        if (!currentPaths.has(entry.path)) await rm(join(cache, entry.path), { force: true }).catch(() => {});
      }
    } catch (error) {
      if (error instanceof FeatureAccessDenied) {
        denied = true;
        snapshot = null;
        await atomicWrite(denialPath,Buffer.from(sourceId)).catch(()=>{});
      }
      // Transient failures retain the last successfully loaded release.
    } finally {
      if (staging) await rm(staging,{recursive:true,force:true}).catch(() => {});
      refreshed = Date.now();
    }
    return snapshot;
  }

  return {
    denied: () => denied,
    read(force = false) {
      if (!force && Date.now() - refreshed < 60000) return Promise.resolve(snapshot);
      return pending ??= refresh().finally(() => { pending = undefined; });
    },
  };
}
