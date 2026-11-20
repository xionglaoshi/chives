import { useState } from 'react';
import type { ReactElement } from 'react';

import type { MessageDto } from '@chives/server/protocol';

import { formatShanghaiDate } from '../utils/format';
import './WatchCard.css';

export interface WatchCardData {
  watchId: string;
  action: 'created' | 'updated' | 'deleted';
  code: string;
  label: string;
  conditionText: string;
  expiresAt: string;
  status: string;
  diff: string;
  repeat: boolean;
}

function metaString(meta: Record<string, unknown> | null, key: string): string {
  const value = meta?.[key];
  return typeof value === 'string' ? value : '';
}

/** Reads the watch card persisted on an `approval` message's meta. */
export function watchFromMessage(message: MessageDto): WatchCardData | null {
  if (message.kind !== 'approval' || message.meta?.['approvalKind'] !== 'watch') return null;
  const watchId = metaString(message.meta, 'watchId');
  if (watchId === '') return null;
  const rawAction = message.meta['watchAction'];
  const action =
    rawAction === 'created' || rawAction === 'updated' || rawAction === 'deleted'
      ? rawAction
      : 'created';
  return {
    watchId,
    action,
    code: metaString(message.meta, 'code'),
    label: metaString(message.meta, 'label'),
    conditionText: metaString(message.meta, 'conditionText'),
    expiresAt: metaString(message.meta, 'expiresAt'),
    status: metaString(message.meta, 'status'),
    diff: metaString(message.meta, 'diff'),
    repeat: message.meta['repeat'] === true
  };
}

const STATUS_TEXT: Record<string, string> = {
  active: '生效中',
  triggered: '已触发',
  expired: '已过期',
  cancelled: '已删除'
};

/** Drops the `name code：` prefix and trailing expiry; the card already shows both. */
export function displayWatchCondition(conditionText: string): string {
  return conditionText.replace(/^[^：]*：/, '').replace(/，至 \d{1,2}-\d{1,2}$/, '');
}

export interface WatchCardProps {
  card: WatchCardData;
  onDelete?: (watchId: string) => Promise<void>;
}

export function WatchCard({ card, onDelete }: WatchCardProps): ReactElement {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleted, setDeleted] = useState(card.action === 'deleted' || card.status === 'cancelled');
  const active = !deleted && card.status === 'active';

  const remove = async (): Promise<void> => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (onDelete === undefined) {
        setError('这里不能删除，请到资料页操作');
      } else {
        await onDelete(card.watchId);
        setDeleted(true);
      }
    } catch {
      setError('删除失败，请重试');
    } finally {
      setBusy(false);
    }
  };

  const heading =
    card.action === 'deleted' || deleted
      ? '已删除盯盘'
      : card.action === 'updated'
        ? `已修改盯盘：${card.label}`
        : `已创建盯盘：${card.label}`;
  const statusText = deleted ? '已删除' : (STATUS_TEXT[card.status] ?? card.status);

  // The label is already in the heading, so drop the 「名称 代码：」 prefix and the trailing
  // expiry from the condition line; both are shown once in the meta row.
  const condition = displayWatchCondition(card.conditionText);

  return (
    <section
      className={`watch-card${active ? '' : ' watch-card--muted'}`}
      aria-label={heading}
      aria-busy={busy}
    >
      <div className="watch-card__head">
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M3.5 7a4.5 4.5 0 019 0c0 3 1.5 4 1.5 4H2s1.5-1 1.5-4z" strokeLinejoin="round" />
          <path d="M6.5 13a1.5 1.5 0 003 0" strokeLinecap="round" />
        </svg>
        <span className="watch-card__title">{heading}</span>
        <span className={`watch-card__status watch-card__status--${deleted ? 'cancelled' : card.status}`}>
          {statusText}
        </span>
        {active ? (
          <button
            type="button"
            className="watch-card__delete"
            disabled={busy}
            onClick={() => void remove()}
          >
            {busy ? '删除中…' : '删除'}
          </button>
        ) : null}
      </div>
      <div className="watch-card__meta">
        <span className="watch-card__condition">{condition}</span>
        <span>{card.code}</span>
        {card.expiresAt === '' ? null : <span>至 {formatShanghaiDate(card.expiresAt)}</span>}
        <span>{card.repeat ? '触发后继续盯' : '只触发一次'}</span>
        <span className="watch-card__hint" title="到条件时会唤醒 bot 分析，需要时它才通知你">
          只唤醒分析，不会下单
        </span>
      </div>
      {card.diff === '' ? null : <div className="watch-card__diff">{card.diff}</div>}
      {error === null ? null : (
        <div className="watch-card__error" role="alert">
          {error}
        </div>
      )}
    </section>
  );
}
