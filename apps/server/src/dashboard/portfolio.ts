/** Runs `python -m portfolio_mcp snapshot` and maps its JSON to the dashboard DTO. */

import { execFile } from 'node:child_process';
import { join } from 'node:path';

import type {
  PortfolioDashboardDto,
  PortfolioPositionDto,
  PortfolioSummaryDto,
} from '../api/protocol.js';

export class PortfolioError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PortfolioError';
  }
}

const SNAPSHOT_TIMEOUT_MS = 15_000;
const MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024;
const UNAVAILABLE = '持仓暂时取不到，稍后再试';

export interface SnapshotOptions {
  repoRoot: string;
  dshHome: string;
  exec?: typeof execFile;
  timeoutMs?: number;
}

export type SnapshotRunner = () => Promise<string>;

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : {};
}

/**
 * The child gets only DSH_HOME (the same value as the dsh child process), PATH and HOME.
 * Nothing else from the server environment is forwarded.
 */
export function createSnapshotRunner(options: SnapshotOptions): SnapshotRunner {
  const python = join(options.repoRoot, 'packages', 'portfolio-mcp', '.venv', 'bin', 'python');
  const cwd = join(options.repoRoot, 'packages', 'portfolio-mcp');
  const env = {
    DSH_HOME: options.dshHome,
    PATH: process.env['PATH'] ?? '',
    HOME: process.env['HOME'] ?? '',
  };
  const run = options.exec ?? execFile;
  return () =>
    new Promise<string>((resolve, reject) => {
      run(
        python,
        ['-m', 'portfolio_mcp', 'snapshot'],
        {
          cwd,
          env,
          timeout: options.timeoutMs ?? SNAPSHOT_TIMEOUT_MS,
          maxBuffer: MAX_SNAPSHOT_BYTES,
          encoding: 'utf8',
        },
        (error, stdout) => {
          if (error !== null) {
            reject(new PortfolioError(UNAVAILABLE));
            return;
          }
          resolve(typeof stdout === 'string' ? stdout : '');
        },
      );
    });
}

export function parseSnapshot(stdout: string): PortfolioDashboardDto {
  let raw: unknown;
  try {
    raw = JSON.parse(stdout) as unknown;
  } catch {
    throw new PortfolioError(UNAVAILABLE);
  }
  const payload = record(raw);
  if (payload['status'] === 'error') {
    throw new PortfolioError(UNAVAILABLE);
  }
  const positionsRaw = Array.isArray(payload['positions']) ? payload['positions'] : [];
  const positions: PortfolioPositionDto[] = positionsRaw.map((item) => {
    const row = record(item);
    return {
      code: str(row['code']),
      name: str(row['name']),
      qty: num(row['qty']),
      costPrice: num(row['cost_price']),
      price: num(row['price']),
      prevClose: num(row['prev_close']),
      changePct: num(row['change_pct']),
      marketValue: num(row['market_value']),
      pnl: num(row['pnl']),
      pnlPct: num(row['pnl_pct']),
      todayPnl: num(row['today_pnl']),
      priceAvailable: row['price_available'] !== false,
    };
  });
  const summaryRaw = record(payload['summary']);
  const summary: PortfolioSummaryDto = {
    positionCount: num(summaryRaw['position_count']) ?? positions.length,
    pricedCount: num(summaryRaw['priced_count']) ?? 0,
    unpricedCount: num(summaryRaw['unpriced_count']) ?? 0,
    totalMarketValue: num(summaryRaw['total_market_value']),
    totalPnl: num(summaryRaw['total_pnl']),
    totalPnlPct: num(summaryRaw['total_pnl_pct']),
    todayPnl: num(summaryRaw['today_pnl']),
    todayPnlPct: num(summaryRaw['today_pnl_pct']),
  };
  const unpriced = (Array.isArray(payload['unpriced']) ? payload['unpriced'] : []).map(
    (item) => {
      const row = record(item);
      return {
        code: str(row['code']),
        name: str(row['name']),
        reason: str(row['reason']),
      };
    },
  );
  const warnings = (Array.isArray(payload['warnings']) ? payload['warnings'] : []).map(
    (item) => {
      const row = record(item);
      return { code: str(row['code']), message: str(row['message']) };
    },
  );
  const asOf = payload['as_of'];
  const cash = payload['cash'];
  return {
    asOf: typeof asOf === 'string' && asOf !== '' ? asOf : null,
    cash: num(cash),
    summary,
    positions,
    unpriced,
    empty: positions.length === 0,
    warnings,
  };
}
