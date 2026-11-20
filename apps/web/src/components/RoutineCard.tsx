import { useState } from 'react';
import type { ReactElement } from 'react';

import type { MessageDto } from '@chives/server/protocol';

import { formatTime } from '../utils/format';
import './ApprovalCard.css';
import './RoutineCard.css';

export interface RoutineCardData {
  routineId: string;
  title: string;
  scheduleText: string;
  promptSummary: string;
  decision: 'allow' | 'reject' | null;
  decidedAt: string | null;
}

function metaString(meta: Record<string, unknown> | null, key: string): string {
  const value = meta?.[key];
  return typeof value === 'string' ? value : '';
}

/** Reads the confirmation card persisted on a `kind=approval` message's meta. */
export function routineFromMessage(message: MessageDto): RoutineCardData | null {
  if (message.kind !== 'approval' || message.meta?.['approvalKind'] !== 'routine') return null;
  const routineId = metaString(message.meta, 'routineId');
  if (routineId === '') return null;
  const decision = message.meta['decision'];
  return {
    routineId,
    title: metaString(message.meta, 'title'),
    scheduleText: metaString(message.meta, 'scheduleText'),
    promptSummary: metaString(message.meta, 'promptSummary'),
    decision: decision === 'allow' || decision === 'reject' ? decision : null,
    decidedAt: metaString(message.meta, 'decidedAt') || null
  };
}

export interface RoutineCardProps {
  card: RoutineCardData;
  onEnable: (routineId: string) => Promise<void>;
  onDismiss: (routineId: string) => Promise<void>;
}

export function RoutineCard({ card, onEnable, onDismiss }: RoutineCardProps): ReactElement {
  const [submitting, setSubmitting] = useState<'allow' | 'reject' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pending = card.decision === null;

  const decide = async (decision: 'allow' | 'reject'): Promise<void> => {
    if (submitting !== null) return;
    setSubmitting(decision);
    setError(null);
    try {
      if (decision === 'allow') await onEnable(card.routineId);
      else await onDismiss(card.routineId);
    } catch {
      setError('提交失败，请重试');
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <section
      className={`approval-card routine-card${pending ? ' approval-card--pending' : ''}`}
      aria-label={`主动任务确认：${card.title}`}
      aria-busy={submitting !== null}
    >
      <div className="approval-card__head">
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5">
          <circle cx="8" cy="8" r="6" />
          <path d="M8 4.5V8l2.2 1.6" strokeLinecap="round" />
        </svg>
        <span>要创建主动任务：{card.title}</span>
      </div>
      <div className="routine-card__schedule">{card.scheduleText}</div>
      <div className="routine-card__prompt">{card.promptSummary}</div>
      <div className="routine-card__hint">启用后它会在时间表到点时自己发消息；默认不启用。</div>

      {pending ? (
        <div className="approval-card__actions">
          <button
            type="button"
            className="approval-card__allow"
            disabled={submitting !== null}
            onClick={() => void decide('allow')}
          >
            {submitting === 'allow' ? '提交中…' : '启用'}
          </button>
          <button
            type="button"
            className="approval-card__reject"
            disabled={submitting !== null}
            onClick={() => void decide('reject')}
          >
            {submitting === 'reject' ? '提交中…' : '不要'}
          </button>
        </div>
      ) : (
        <div className="approval-card__status" role="status">
          <span>{card.decision === 'allow' ? '已启用' : '已取消'}</span>
          {card.decidedAt === null ? null : <span>{formatTime(card.decidedAt)}</span>}
        </div>
      )}

      {error === null ? null : (
        <div className="approval-card__error" role="alert">
          {error}
        </div>
      )}
    </section>
  );
}
