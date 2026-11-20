import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactElement } from 'react';

import type { WatchDto } from '@chives/server/protocol';

import { fetchWatch, fetchWatches } from '../api/client';
import { displayWatchCondition } from './WatchCard';
import { formatTime } from '../utils/format';
import './ExpertSidebar.css';

const RECENT_TRIGGER_WINDOW_MS = 7 * 86_400_000;

const ENGINE_TEXT: Record<string, string> = {
  observe: '等待中',
  await_confirm: '部分满足',
  execute: '已满足',
  abandon: '已满足',
  exit: '已满足'
};

const TRIGGER_REASON: Record<string, string> = {
  execute: '达到执行条件',
  abandon: '达到放弃条件',
  exit: '达到退出条件'
};

function engineText(watch: WatchDto): string {
  if (watch.status === 'triggered') return '已触发';
  return watch.engineState === null ? '等待中' : (ENGINE_TEXT[watch.engineState] ?? '等待中');
}

function triggerReason(watch: WatchDto, reasons: Readonly<Record<string, string>>): string {
  const detail = reasons[watch.id];
  if (detail !== undefined && detail !== '') return detail;
  if (watch.engineState === null) return '条件已满足';
  return TRIGGER_REASON[watch.engineState] ?? '条件已满足';
}

function expiryDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso.slice(0, 10);
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).format(date);
}

/** The first `跌破/站上` price in a human condition, used for distance-to-trigger. */
export function triggerPriceFromCondition(conditionText: string): number | null {
  const match = /(?:跌破|站上)\s*([0-9]+(?:\.[0-9]+)?)/.exec(conditionText);
  if (match === null) return null;
  const value = Number(match[1]);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function distanceText(watch: WatchDto): string | null {
  if (watch.lastPrice === null) return null;
  const trigger = triggerPriceFromCondition(watch.conditionText);
  if (trigger === null) return null;
  const pct = ((watch.lastPrice - trigger) / trigger) * 100;
  const sign = pct > 0 ? '+' : '';
  return `距触发价 ${sign}${pct.toFixed(2)}%`;
}

function syncText(error: string): string {
  return error === 'engine_unreachable'
    ? '盯盘引擎没有启动，启动后自动生效'
    : `同步异常：${error}`;
}

export interface WatchesPanelProps {
  botId: string;
  /** Bumped on any watch SSE event. */
  revision: number;
  onEditWatch: (label: string) => void;
  onLocateTask: (taskId: string) => void;
  onCancelWatch: (watchId: string) => Promise<void>;
}

export function WatchesPanel({
  botId,
  revision,
  onEditWatch,
  onLocateTask,
  onCancelWatch
}: WatchesPanelProps): ReactElement {
  const [watches, setWatches] = useState<WatchDto[]>([]);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [reasons, setReasons] = useState<Record<string, string>>({});

  const enrichReasons = useCallback(async (list: WatchDto[], signal: AbortSignal): Promise<void> => {
    const since = Date.now() - RECENT_TRIGGER_WINDOW_MS;
    const recent = list.filter((watch) => {
      if (watch.triggeredAt === null) return false;
      const at = Date.parse(watch.triggeredAt);
      return Number.isFinite(at) && at >= since;
    });
    const entries = await Promise.all(
      recent.map(async (watch): Promise<readonly [string, string]> => {
        try {
          const detail = await fetchWatch(watch.id, signal);
          const event = detail.history.filter((entry) => entry.kind === 'triggered').at(-1);
          return [watch.id, event?.detail ?? ''];
        } catch {
          return [watch.id, ''];
        }
      })
    );
    if (signal.aborted) return;
    setReasons(Object.fromEntries(entries));
  }, []);

  const load = useCallback(
    async (signal: AbortSignal): Promise<void> => {
      try {
        const list = await fetchWatches(botId, 'all', signal);
        if (signal.aborted) return;
        setWatches(list);
        setStatus('ready');
        setError(null);
        void enrichReasons(list, signal);
      } catch {
        if (signal.aborted) return;
        setStatus('error');
        setError('盯盘没有加载出来');
      }
    },
    [botId, enrichReasons]
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, revision]);

  const active = useMemo(
    () => watches.filter((watch) => watch.status === 'active'),
    [watches]
  );
  const recent = useMemo(() => {
    const since = Date.now() - RECENT_TRIGGER_WINDOW_MS;
    return watches
      .filter((watch) => {
        if (watch.triggeredAt === null) return false;
        const at = Date.parse(watch.triggeredAt);
        return Number.isFinite(at) && at >= since;
      })
      .sort((left, right) => (right.triggeredAt ?? '').localeCompare(left.triggeredAt ?? ''));
  }, [watches]);

  const remove = async (watch: WatchDto): Promise<void> => {
    if (busyId !== null) return;
    if (confirmId !== watch.id) {
      setConfirmId(watch.id);
      setError(null);
      return;
    }
    setBusyId(watch.id);
    setError(null);
    try {
      await onCancelWatch(watch.id);
      setWatches((current) => current.filter((entry) => entry.id !== watch.id));
      setConfirmId(null);
    } catch {
      setError('删除失败，请重试');
    } finally {
      setBusyId(null);
    }
  };

  if (status === 'loading' && watches.length === 0) {
    return (
      <div className="expert-sidebar__skeleton" aria-hidden="true">
        {Array.from({ length: 3 }, (_, index) => (
          <span className="skeleton expert-sidebar__skeleton-row" key={index} />
        ))}
      </div>
    );
  }

  return (
    <section className="expert-sidebar__section" aria-label="盯盘">
      <h3 className="expert-sidebar__heading">生效中</h3>
      {status === 'error' ? (
        <p className="expert-sidebar__error" role="status">
          {error ?? '盯盘没有加载出来'}
        </p>
      ) : null}
      {error !== null && status !== 'error' ? (
        <p className="expert-sidebar__error" role="alert">
          {error}
        </p>
      ) : null}
      {status !== 'error' && active.length === 0 ? (
        <p className="expert-sidebar__empty">
          还没有盯盘。直接在对话里说，如&apos;柳工跌破 7.7 叫我&apos;。
        </p>
      ) : null}
      {active.length === 0 ? null : (
        <ul className="expert-sidebar__watches">
          {active.map((watch) => {
            const distance = distanceText(watch);
            return (
              <li key={watch.id} className="expert-sidebar__watch">
                <div className="expert-sidebar__watch-line">
                  <span className="expert-sidebar__watch-label">{watch.label}</span>
                  <span className="expert-sidebar__watch-state">{engineText(watch)}</span>
                </div>
                <p className="expert-sidebar__watch-condition">
                  {displayWatchCondition(watch.conditionText)}
                </p>
                <div className="expert-sidebar__watch-meta">
                  <span>最近价 {watch.lastPrice ?? '—'}</span>
                  {distance === null ? null : <span>{distance}</span>}
                  <span>至 {expiryDate(watch.expiresAt)}</span>
                </div>
                {watch.syncError === null ? null : (
                  <p className="expert-sidebar__watch-sync">{syncText(watch.syncError)}</p>
                )}
                <div className="expert-sidebar__watch-actions">
                  <button
                    type="button"
                    className="expert-sidebar__watch-button"
                    onClick={() => onEditWatch(watch.label)}
                  >
                    修改
                  </button>
                  <button
                    type="button"
                    className="expert-sidebar__watch-button expert-sidebar__watch-button--danger"
                    disabled={busyId !== null}
                    onClick={() => void remove(watch)}
                  >
                    {busyId === watch.id
                      ? '删除中…'
                      : confirmId === watch.id
                        ? '确认删除'
                        : '删除'}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <h3 className="expert-sidebar__heading">最近触发</h3>
      {recent.length === 0 ? (
        <p className="expert-sidebar__empty">最近 7 天没有触发。</p>
      ) : (
        <ul className="expert-sidebar__triggers">
          {recent.map((watch) => (
            <li key={watch.id}>
              <button
                type="button"
                className="expert-sidebar__trigger"
                disabled={watch.triggerTaskId === null}
                onClick={() => {
                  if (watch.triggerTaskId !== null) onLocateTask(watch.triggerTaskId);
                }}
              >
                <span className="expert-sidebar__trigger-time">
                  {expiryDate(watch.triggeredAt ?? '')} {formatTime(watch.triggeredAt ?? '')}
                </span>
                <span className="expert-sidebar__trigger-label">{watch.label}</span>
                <span className="expert-sidebar__trigger-reason">{triggerReason(watch, reasons)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
