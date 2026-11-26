import { useRef } from 'react';
import type { KeyboardEvent, ReactElement } from 'react';

import type { BotSummary } from '@chives/server/protocol';

import { botPortraitUrl } from './BotPortraitPicker';
import { BOT_STATUS_TONES, botStatusLabel } from '../utils/bots';
import './BotList.css';

const STATUS_TONES = BOT_STATUS_TONES;
const SIDEBAR_DESCRIPTIONS: Readonly<Partial<Record<string, string>>> = {
  ceo: '回答您的一切疑问',
  cio: '发现新的投资机会',
  cro: '揭示风险、控制回撤',
  trader: '实时汇报个股交易动态',
  analyst: '深入研究个股价值',
};

function sidebarStatusLabel(bot: BotSummary): string {
  return bot.status === 'working' ? '思考' : botStatusLabel(bot);
}

export function approvalCount(bot: Pick<BotSummary, 'status' | 'pendingApprovals'>): number {
  if (typeof bot.pendingApprovals === 'number') return bot.pendingApprovals;
  return bot.status === 'awaiting_approval' ? 1 : 0;
}

export interface BotRowProps {
  bot: BotSummary;
  selected: boolean;
  onSelect: (botId: string) => void;
  onKeyDown: (event: KeyboardEvent<HTMLButtonElement>, botId: string) => void;
  onMove?: ((source:string,target:string)=>void) | undefined;
  buttonRef: (element: HTMLButtonElement | null) => void;
}

export function BotRow({ bot, selected, onSelect, onKeyDown, buttonRef, onMove }: BotRowProps): ReactElement {
  const canMove = Boolean(onMove) && bot.id !== 'ceo';
  const suppressClick = useRef(false);
  const jobTitle = bot.name;
  const statusLabel = sidebarStatusLabel(bot);
  const idle = bot.status === 'idle' && !(bot.waitingDelegations ?? 0);
  const count = approvalCount(bot);
  const unread = bot.unreadNotifications ?? 0;
  const classes = ['bot-row', `bot-row--${bot.status}`, `bot-row--${bot.background ? 'background' : 'foreground'}`];
  if (selected) classes.push('bot-row--selected');

  return (
    <li className="bot-list__item" data-dot-id={bot.id}
      draggable={canMove}
      onPointerDown={() => { suppressClick.current = false; }}
      onDragStart={e=>{e.dataTransfer.setData('text/chives-dot',bot.id);e.dataTransfer.effectAllowed='move';}}
      onDragOver={e=>{if(bot.id!=='ceo' && e.dataTransfer.types.includes('text/chives-dot')) e.preventDefault();}}
      onDrop={e=>{e.preventDefault(); const id=e.dataTransfer.getData('text/chives-dot');if(id) onMove?.(id,bot.id);}}>
      <button
        ref={buttonRef}
        type="button"
        className={classes.join(' ')}
        onClick={() => { if (!suppressClick.current) onSelect(bot.id); suppressClick.current = false; }}
        onKeyDown={(event) => onKeyDown(event, bot.id)}
        aria-current={selected ? 'page' : undefined}
        aria-label={`${jobTitle}，${statusLabel}${count > 0 ? `，${count} 项待你批准` : ''}${unread > 0 ? `，${unread} 条未读通知` : ''}`}
        title={canMove ? jobTitle + ' · 拖动排序，或按 Alt 加上下方向键' : jobTitle}
      >
        <span className="bot-row__body">
          <span className="bot-row__line">
            <span className="bot-row__identity">
              <span className="bot-row__name"
                onPointerDown={event => {
                  if (canMove && event.pointerType === 'touch') event.currentTarget.setPointerCapture(event.pointerId);
                }}
                onPointerUp={event => {
                  if (!canMove || event.pointerType !== 'touch' ||
                      !event.currentTarget.hasPointerCapture(event.pointerId)) return;
                  const target = document.elementFromPoint(event.clientX, event.clientY)
                    ?.closest<HTMLElement>('[data-dot-id]')?.dataset.dotId;
                  if (target === bot.id) return;
                  suppressClick.current = true;
                  if (target && target !== 'ceo') onMove?.(bot.id, target);
                }}>{jobTitle}</span>
              {unread > 0 && <span className="bot-row__unread" aria-hidden="true">（{unread}）</span>}
            </span>
            <span className={`bot-row__status bot-row__status--${STATUS_TONES[bot.status]}`}>
              <span className="bot-row__dot" aria-hidden="true" />
              <span className={idle ? "bot-row__status-label bot-row__status-label--idle" : "bot-row__status-label"}>{statusLabel}</span>
            </span>
          </span>
          <span className="bot-row__role">
            {SIDEBAR_DESCRIPTIONS[bot.id] ?? bot.role}
          </span>
        </span>
        {count > 0 ? (
          <span className="bot-row__badge" aria-label={`${count} 项待你批准`}>
            {count}
          </span>
        ) : null}
      </button>
    </li>
  );
}

export interface BotListProps {
  bots: BotSummary[];
  selectedId: string | null;
  onSelect: (botId: string) => void;
}

export function BotList({ bots, selectedId, onSelect, onMove }: BotListProps & {onMove?:(source:string,target:string)=>void}): ReactElement {
  const refs = useRef(new Map<string, HTMLButtonElement>());
  const ordered = [...bots.filter(bot=>bot.id==='ceo'),...bots.filter(bot=>bot.id!=='ceo')];

  const move = (botId: string, offset: number): void => {
    const index = ordered.findIndex((bot) => bot.id === botId);
    if (index === -1 || ordered.length === 0) return;
    const next = ordered[(index + offset + ordered.length) % ordered.length];
    if (next === undefined) return;
    onSelect(next.id);
    refs.current.get(next.id)?.focus();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>, botId: string): void => {
    if (event.altKey && (event.key==='ArrowUp' || event.key==='ArrowDown')) {
      event.preventDefault();
      const target=ordered[ordered.findIndex(bot=>bot.id===botId)+(event.key==='ArrowUp' ? -1 : 1)];
      if (onMove && target && target.id!=='ceo' && botId!=='ceo') onMove(botId,target.id);
      return;
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      move(botId, 1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      move(botId, -1);
    } else if (event.key === 'Home') {
      event.preventDefault();
      const first = ordered[0];
      if (first !== undefined) {
        onSelect(first.id);
        refs.current.get(first.id)?.focus();
      }
    } else if (event.key === 'End') {
      event.preventDefault();
      const last = ordered.at(-1);
      if (last !== undefined) {
        onSelect(last.id);
        refs.current.get(last.id)?.focus();
      }
    }
  };

  return <div className="bot-list">
    <h2 className="bot-list__heading">已在岗Bot</h2>
    <ul className="bot-list__list">{ordered.map(bot=><BotRow key={bot.id} bot={bot}
      selected={bot.id===selectedId} onSelect={onSelect} onKeyDown={handleKeyDown} onMove={onMove}
      buttonRef={el=>{if (el) refs.current.set(bot.id,el); else refs.current.delete(bot.id);}}/>)}</ul>
  </div>;
}

export interface BotRailProps {
  bots: BotSummary[];
  selectedId: string | null;
  onSelect: (botId: string) => void;
}

/** Avatar-only list used beside an open deliverable preview (画板 07). */
export function BotRail({ bots, selectedId, onSelect }: BotRailProps): ReactElement {
  return (
    <ul className="bot-rail" aria-label="Bot 列表（头像栏）">
      {bots.map((bot) => {
        const jobTitle = bot.name;
        const count = approvalCount(bot);
        const selected = bot.id === selectedId;
        return (
          <li key={bot.id} className="bot-rail__item">
            <button
              type="button"
              className={`bot-rail__button bot-rail__button--${bot.status}${
                selected ? ' bot-rail__button--selected' : ''
              }`}
              onClick={() => onSelect(bot.id)}
              aria-current={selected ? 'page' : undefined}
              aria-label={`${jobTitle}，${sidebarStatusLabel(bot)}${
                count > 0 ? `，${count} 项待你批准` : ''
              }`}
              title={jobTitle}
            >
              <img className="bot-rail__portrait" src={botPortraitUrl(bot.portraitId ?? 'man-01')} alt="" width={24} height={24} />
              <span
                className={`bot-rail__status bot-rail__status--${STATUS_TONES[bot.status]}`}
                aria-hidden="true"
              />
              {count > 0 ? (
                <span className="bot-rail__badge" aria-hidden="true">
                  {count}
                </span>
              ) : null}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
