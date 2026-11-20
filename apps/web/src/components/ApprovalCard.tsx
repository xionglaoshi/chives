import { useState } from 'react';
import type { ReactElement } from 'react';

import type { ApprovalDecision, MessageDto } from '@chives/server/protocol';

import { formatTime } from '../utils/format';
import './ApprovalCard.css';

export interface ApprovalCardData {
  id: string;
  title: string | null;
  rawInput: unknown;
  sourceBotName: string;
  delegated: boolean;
  decision: ApprovalDecision | null;
  decidedAt: string | null;
  decidedBy: string | null;
}

const TOOL_TITLES: Record<string, string> = {
  paper_place_order: '模拟盘下单',
  paper_cancel_order: '撤销模拟盘委托',
  paper_get_account: '查看模拟盘账户',
  paper_list_orders: '查看模拟盘委托'
};

const PARAM_LABELS: Record<string, string> = {
  symbol: '标的',
  side: '方向',
  qty: '数量',
  quantity: '数量',
  price: '价格',
  order_type: '委托类型',
  type: '类型'
};

const PARAM_ORDER = ['symbol', 'side', 'qty', 'quantity', 'price', 'order_type', 'type'];

const SIDE_LABELS: Record<string, string> = {
  buy: '买入',
  sell: '卖出',
  long: '买入',
  short: '卖出'
};

const ORDER_TYPE_LABELS: Record<string, string> = {
  market: '市价',
  limit: '限价'
};

function bareToolName(title: string): string {
  if (!title.startsWith('mcp__')) return title;
  const parts = title.split('__');
  return parts.length > 2 ? parts.slice(2).join('__') : title;
}

export function humanToolName(title: string | null): string {
  if (title === null || title.trim() === '') return '工具调用';
  const bare = bareToolName(title);
  return TOOL_TITLES[bare] ?? bare;
}

function decisionLabel(decision: ApprovalDecision, decidedBy: string | null): string {
  if (decision === 'allow') return '已允许';
  if (decision === 'cancelled') return '已取消';
  return decidedBy === 'timeout' ? '超时已拒绝' : '已拒绝';
}

function formatValue(key: string, value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (Array.isArray(value) || typeof value === 'object') return JSON.stringify(value);
  if (typeof value === 'boolean') return value ? '是' : '否';
  const text = String(value);
  if (key === 'side') return SIDE_LABELS[text.toLowerCase()] ?? text;
  if (key === 'order_type' || key === 'type') return ORDER_TYPE_LABELS[text.toLowerCase()] ?? text;
  return text;
}

function paramEntries(rawInput: unknown): Array<[string, unknown]> {
  if (typeof rawInput !== 'object' || rawInput === null || Array.isArray(rawInput)) return [];
  const entries = Object.entries(rawInput as Record<string, unknown>);
  return entries.sort(([left], [right]) => {
    const leftIndex = PARAM_ORDER.indexOf(left);
    const rightIndex = PARAM_ORDER.indexOf(right);
    if (leftIndex === -1 && rightIndex === -1) return left.localeCompare(right);
    if (leftIndex === -1) return 1;
    if (rightIndex === -1) return -1;
    return leftIndex - rightIndex;
  });
}

function metaString(meta: Record<string, unknown> | null, key: string): string | null {
  const value = meta?.[key];
  return typeof value === 'string' ? value : null;
}

/** Reads the card data persisted in a `kind=approval` message's `meta`. */
export function approvalFromMessage(message: MessageDto): ApprovalCardData | null {
  const meta = message.meta;
  if (message.kind !== 'approval' || meta === null) return null;
  const id = metaString(meta, 'approvalId');
  if (id === null) return null;
  const decision = meta.decision;
  return {
    id,
    title: metaString(meta, 'title'),
    rawInput: meta.rawInput ?? null,
    sourceBotName:
      metaString(meta, 'sourceBotName') ??
      metaString(meta, 'sourceBotId') ??
      metaString(meta, 'botId') ??
      '未知 Bot',
    delegated: meta.delegated === true,
    decision:
      decision === 'allow' || decision === 'reject' || decision === 'cancelled' ? decision : null,
    decidedAt: metaString(meta, 'decidedAt'),
    decidedBy: metaString(meta, 'decidedBy')
  };
}

export interface ApprovalCardProps {
  approval: ApprovalCardData;
  onDecide: (approvalId: string, decision: 'allow' | 'reject') => Promise<void>;
}

export function ApprovalCard({ approval, onDecide }: ApprovalCardProps): ReactElement {
  const [submitting, setSubmitting] = useState<'allow' | 'reject' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const title = humanToolName(approval.title);
  const entries = paramEntries(approval.rawInput);
  const pending = approval.decision === null;

  const decide = async (decision: 'allow' | 'reject'): Promise<void> => {
    if (submitting !== null) return;
    setSubmitting(decision);
    setError(null);
    try {
      await onDecide(approval.id, decision);
    } catch {
      setError('提交失败，请重试');
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <section
      className={`approval-card${pending ? ' approval-card--pending' : ''}`}
      aria-label={`需要你批准：${title}`}
      aria-busy={submitting !== null}
    >
      <div className="approval-card__head">
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M8 1.5l5.5 2v4.2c0 3.2-2.3 5.6-5.5 6.8-3.2-1.2-5.5-3.6-5.5-6.8V3.5z" strokeLinejoin="round" />
        </svg>
        <span>需要你批准：{title}</span>
      </div>
      <div className="approval-card__source">
        来自 {approval.sourceBotName}
        {approval.delegated ? '（委派）' : ''}
      </div>

      {entries.length > 0 ? (
        <dl className="approval-card__params">
          {entries.map(([key, value]) => (
            <div className="approval-card__param" key={key}>
              <dt>{PARAM_LABELS[key] ?? key}</dt>
              <dd>{formatValue(key, value)}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <div className="approval-card__empty">该工具没有参数</div>
      )}

      {pending ? (
        <div className="approval-card__actions">
          <button
            type="button"
            className="approval-card__allow"
            disabled={submitting !== null}
            onClick={() => void decide('allow')}
          >
            {submitting === 'allow' ? '提交中…' : '允许这一次'}
          </button>
          <button
            type="button"
            className="approval-card__reject"
            disabled={submitting !== null}
            onClick={() => void decide('reject')}
          >
            {submitting === 'reject' ? '提交中…' : '拒绝'}
          </button>
        </div>
      ) : (
        <div className="approval-card__status" role="status">
          <span>{decisionLabel(approval.decision ?? 'reject', approval.decidedBy)}</span>
          {approval.decidedAt !== null ? <span>{formatTime(approval.decidedAt)}</span> : null}
        </div>
      )}

      {error !== null ? (
        <div className="approval-card__error" role="alert">
          {error}
        </div>
      ) : null}
    </section>
  );
}
