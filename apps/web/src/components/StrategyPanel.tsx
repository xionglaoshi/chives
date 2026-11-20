import { useCallback, useEffect, useState } from 'react';
import type { ReactElement } from 'react';

import type { StrategyPoolRow, StrategyPoolsDto } from '@chives/server/protocol';

import { fetchStrategyPools } from '../api/client';
import { strategyLabel } from '../utils/panels';
import './StrategyPanel.css';

type Status = 'loading' | 'ready' | 'error';

function num(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(value) : '—';
}

function pct(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${(value * 100).toFixed(2)}%`
    : '—';
}

function rowName(row: StrategyPoolRow): string {
  return row.name ?? row.code;
}

const PAGE = 50;

/** Rating badge in the engine's order: 优先级一 → 优先级二 → 确认中/观察 by total score. */
function rating(row: StrategyPoolRow): { label: string; tone: 'p1' | 'p2' | 'pending' | 'watch' } {
  if (row.priority === 'p1') return { label: '优先一', tone: 'p1' };
  if (row.priority === 'p2') return { label: '优先二', tone: 'p2' };
  if (row.status === '确认中') return { label: '确认中', tone: 'pending' };
  return { label: '观察', tone: 'watch' };
}

function byRank(rows: StrategyPoolRow[]): StrategyPoolRow[] {
  return [...rows].sort((left, right) => (left.rank ?? 1e9) - (right.rank ?? 1e9));
}

function StrategyRow({
  row,
  index,
  kind,
  onPickName
}: {
  row: StrategyPoolRow;
  index: number;
  kind: 'first' | 'main';
  onPickName: (name: string) => void;
}): ReactElement {
  const name = rowName(row);
  const badge = kind === 'first' ? rating(row) : null;
  return (
    <li>
      <button
        type="button"
        className="strategy-panel__row"
        aria-label={`查看${name}的主升浪轮次`}
        onClick={() => onPickName(`${name}的主升浪轮次`)}
      >
        <span className="strategy-panel__rank">{row.rank ?? index + 1}</span>
        <span className="strategy-panel__who">
          <span className="strategy-panel__name">{name}</span>
          <span className="strategy-panel__code">{row.code}</span>
        </span>
        {badge === null ? null : (
          <span className={`strategy-panel__badge strategy-panel__badge--${badge.tone}`}>{badge.label}</span>
        )}
        <span className="strategy-panel__score">{num(row.score)}</span>
        <span className="strategy-panel__metrics">
          {kind === 'first' ? (
            <>
              <span>第 {num(row.k)} 日</span>
              {row.t_star ? <span>启动 {row.t_star.slice(5)}</span> : <span>未启动</span>}
            </>
          ) : (
            <>
              <span>涨幅 {pct(row.gain)}</span>
              <span>回撤 {pct(row.drawdown)}</span>
              <span>
                MA10 {num(row.ma10_count)} 次{(row.ma10_obs_left ?? 0) > 0 ? ' · 观察中' : ''}
              </span>
            </>
          )}
        </span>
      </button>
    </li>
  );
}

export interface StrategyPanelProps {
  botId: string;
  strategyId: string;
  /** Changes when the bot's task ends; forces one refresh. */
  taskClosedToken: number;
  onPickName: (name: string) => void;
}

export function StrategyPanel({
  botId,
  strategyId,
  taskClosedToken,
  onPickName
}: StrategyPanelProps): ReactElement {
  const [status, setStatus] = useState<Status>('loading');
  const [data, setData] = useState<StrategyPoolsDto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<'first' | 'main'>('first');
  const [limit, setLimit] = useState(PAGE);

  const load = useCallback(
    async (signal: AbortSignal): Promise<void> => {
      try {
        const payload = await fetchStrategyPools(strategyId, botId, undefined, signal);
        if (signal.aborted) return;
        setData(payload);
        setStatus('ready');
        setError(null);
      } catch (caught) {
        if (signal.aborted) return;
        setStatus('error');
        setError(caught instanceof Error ? caught.message : '策略面板没有加载出来');
      }
    },
    [botId, strategyId]
  );

  useEffect(() => {
    const controller = new AbortController();
    setStatus('loading');
    void load(controller.signal);
    return () => controller.abort();
  }, [load, taskClosedToken]);

  if (status === 'loading' && data === null) {
    return (
      <div className="expert-sidebar__skeleton" aria-hidden="true">
        {Array.from({ length: 3 }, (_, index) => (
          <span className="skeleton expert-sidebar__skeleton-row" key={index} />
        ))}
      </div>
    );
  }

  if (status === 'error' && data === null) {
    return (
      <section className="expert-sidebar__section" aria-label={`${strategyLabel(strategyId)}策略面板`}>
        <p className="expert-sidebar__error" role="status">
          {error ?? '策略面板没有加载出来'}
        </p>
      </section>
    );
  }

  const first = byRank(data?.pools.first ?? []);
  const main = byRank(data?.pools.main ?? []);
  const rows = tab === 'first' ? first : main;
  const shown = rows.slice(0, limit);

  return (
    <section className="expert-sidebar__section" aria-label={`${strategyLabel(strategyId)}策略面板`}>
      <div className="strategy-panel__tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'first'}
          className={`strategy-panel__tab${tab === 'first' ? ' is-active' : ''}`}
          onClick={() => {
            setTab('first');
            setLimit(PAGE);
          }}
        >
          候选池 <span>{first.length}</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'main'}
          className={`strategy-panel__tab${tab === 'main' ? ' is-active' : ''}`}
          onClick={() => {
            setTab('main');
            setLimit(PAGE);
          }}
        >
          主升浪池 <span>{main.length}</span>
        </button>
      </div>
      <div className="strategy-panel__meta">
        <span>计算日 {data?.date ?? '—'} · {data?.status ?? '—'}</span>
        <span>{tab === 'first' ? '按评级排序：优先一 → 优先二 → 观察（总分）' : '按分数排序'}</span>
      </div>
      {error === null ? null : (
        <p className="expert-sidebar__error" role="alert">
          {error}
        </p>
      )}
      {rows.length === 0 ? (
        <p className="expert-sidebar__empty">
          {tab === 'first' ? '候选池为空。' : '主升浪池为空。'}
        </p>
      ) : (
        <ul className="strategy-panel__list">
          {shown.map((row, index) => (
            <StrategyRow
              key={`${tab}-${row.code}`}
              row={row}
              index={index}
              kind={tab}
              onPickName={onPickName}
            />
          ))}
        </ul>
      )}
      {rows.length > shown.length ? (
        <button type="button" className="strategy-panel__more" onClick={() => setLimit(limit + PAGE)}>
          显示更多（还有 {rows.length - shown.length} 只）
        </button>
      ) : null}
    </section>
  );
}
