import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, rename, rm, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import type { HoldingValuation } from './holding-valuations.js';

interface Snapshot {
  hotspots: Record<string, unknown> | null;
  valuations: Record<string, HoldingValuation>;
}

const sizeLimit = 32 * 1024 * 1024;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseSnapshot(bytes: Uint8Array): Snapshot {
  const value: unknown = JSON.parse(Buffer.from(bytes).toString('utf8'));
  if (!isRecord(value) || !isRecord(value.valuations) ||
      (value.hotspots !== null && !isRecord(value.hotspots))) {
    throw new Error('Invalid featured data snapshot');
  }
  for (const [code, estimate] of Object.entries(value.valuations)) {
    if (!/^\d{6}\.(SH|SZ|BJ)$/.test(code) || !isRecord(estimate) ||
        !['动态估值', '静态参考', '依据不足'].some(kind => kind === estimate.valuationKind) ||
        !(estimate.low === null && estimate.high === null ||
          typeof estimate.low === 'number' && typeof estimate.high === 'number' &&
          Number.isFinite(estimate.low) && Number.isFinite(estimate.high) &&
          estimate.low > 0 && estimate.high >= estimate.low) ||
        !(estimate.score === null || typeof estimate.score === 'number' &&
          Number.isInteger(estimate.score) && Math.abs(estimate.score) <= 5)) {
      throw new Error('Invalid featured valuation');
    }
  }
  return value as unknown as Snapshot;
}

async function download(url: URL, limit: number): Promise<Buffer> {
  const response = await fetch(url, { redirect: 'error', signal: AbortSignal.timeout(8000) });
  if (!response.ok || !response.body) throw new Error('Featured data download failed');
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    for (;;) {
      const chunk = await reader.read();
      if (chunk.done) return Buffer.concat(chunks, size);
      size += chunk.value.byteLength;
      if (size > limit) throw new Error('Featured data exceeds its size limit');
      chunks.push(chunk.value);
    }
  } finally {
    await reader.cancel();
  }
}

export function featureDataService(endpoint: string, cache: string) {
  const base = new URL(endpoint.endsWith('/') ? endpoint : endpoint + '/');
  const cached = join(cache, 'snapshot.json');
  let snapshot: Snapshot | null = null;
  let refreshed = 0;
  let downloadedHash: string | undefined;
  let pending: Promise<Snapshot | null> | undefined;

  async function refresh(): Promise<Snapshot | null> {
    if (!snapshot) {
      try { snapshot = parseSnapshot(await readFile(cached)); }
      catch { /* The initial download can rebuild a missing or invalid cache. */ }
    }
    try {
      const manifest: unknown = JSON.parse((await download(new URL('manifest.json', base), 4096)).toString('utf8'));
      if (!isRecord(manifest) || manifest.schema !== 1 ||
          typeof manifest.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(manifest.sha256)) {
        throw new Error('Invalid featured data manifest');
      }
      if (snapshot && downloadedHash === manifest.sha256 &&
          (await stat(cached).catch(() => undefined))?.isFile()) {
        return snapshot;
      }
      const bytes = await download(new URL(manifest.sha256 + '.json', base), sizeLimit);
      if (createHash('sha256').update(bytes).digest('hex') !== manifest.sha256) {
        throw new Error('Featured snapshot checksum mismatch');
      }
      const next = parseSnapshot(bytes);
      await mkdir(cache, { recursive: true });
      const temporary = join(cache, randomUUID() + '.tmp');
      try {
        await writeFile(temporary, bytes, { flag: 'wx' });
        await rename(temporary, cached);
      } finally {
        await rm(temporary, { force: true });
      }
      snapshot = next;
      downloadedHash = manifest.sha256;
    } catch {
      // Keep serving the last verified release during publication or network failures.
    } finally {
      refreshed = Date.now();
    }
    return snapshot;
  }

  return {
    read(force = false) {
      if (!force && Date.now() - refreshed < 60000) return Promise.resolve(snapshot);
      return pending ??= refresh().finally(() => { pending = undefined; });
    },
  };
}
