import { useRef } from 'react';
import type { KeyboardEvent, ReactElement } from 'react';

import type { BotSummary } from '@chives/server/protocol';

import { BotAvatar } from '../brand/BotAvatar';
import { BOT_STATUS_TONES, botStatusLabel } from '../utils/bots';
import { Pin } from './SidebarPins';
import './BotList.css';

const STATUS_TONES = BOT_STATUS_TONES;

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
  onPin?: ((id:string)=>void) | undefined;
  buttonRef: (element: HTMLButtonElement | null) => void;
}

export function BotRow({ bot, selected, onSelect, onKeyDown, buttonRef, onMove, onPin }: BotRowProps): ReactElement {
  const statusLabel = botStatusLabel(bot);
  const count = approvalCount(bot);
  const watchCount = bot.watchCount ?? 0;
  const unread = bot.unreadNotifications ?? 0;
  const classes = ['bot-row', `bot-row--${bot.status}`, `bot-row--${bot.background ? 'background' : 'foreground'}`];
  if (selected) classes.push('bot-row--selected');

  return (
    <li className="bot-list__item" data-dot-id={bot.id}
      draggable={Boolean(onMove) && bot.id!=='chives'}
      onDragStart={e=>{e.dataTransfer.setData('text/chives-dot',bot.id);e.dataTransfer.effectAllowed='move';}}
      onDragOver={e=>{if(bot.id!=='chives' && e.dataTransfer.types.includes('text/chives-dot')) e.preventDefault();}}
      onDrop={e=>{e.preventDefault(); const id=e.dataTransfer.getData('text/chives-dot');if(id) onMove?.(id,bot.id);}}>
      <button
        ref={buttonRef}
        type="button"
        className={classes.join(' ')}
        onClick={() => onSelect(bot.id)}
        onKeyDown={(event) => onKeyDown(event, bot.id)}
        aria-current={selected ? 'page' : undefined}
        aria-label={`${bot.name}，${statusLabel}${count > 0 ? `，${count} 项待你批准` : ''}${
          watchCount > 0 ? `，${watchCount} 条盯盘` : ''
        }${unread > 0 ? `，${unread} 条未读通知` : ''}`}
        title={bot.name}
      >
        <BotAvatar
          emblem={bot.avatar.emblem}
          tone={bot.avatar.tone}
          size={18}
        />
        {unread > 0 ? <span className="bot-row__unread" aria-hidden="true" /> : null}
        <span className="bot-row__body">
          <span className="bot-row__line">
            <span className="bot-row__name">{bot.name}</span>
            <span className={`bot-row__status bot-row__status--${STATUS_TONES[bot.status]}`}>
              <span className="bot-row__dot" aria-hidden="true" />
              <span className="bot-row__status-label">{statusLabel}</span>
            </span>
          </span>
          <span className="bot-row__role">
            {bot.role}
            {watchCount > 0 ? <span className="bot-row__watch">盯盘 {watchCount}</span> : null}
          </span>
        </span>
        {count > 0 ? (
          <span className="bot-row__badge" aria-label={`${count} 项待你批准`}>
            {count}
          </span>
        ) : null}
      </button>
      <div className="bot-row-actions">
      {onMove && bot.id!=='chives' && <span className="dot-grip" title="拖动调整顺序，键盘可按 Alt 加上下方向键" aria-hidden="true"
        onPointerDown={e=>{if(e.pointerType!=='mouse') e.currentTarget.setPointerCapture(e.pointerId);}}
        onPointerUp={e=>{
          if(e.pointerType==='mouse') return;
          const target=document.elementFromPoint(e.clientX,e.clientY)?.closest<HTMLElement>('[data-dot-id]')?.dataset.dotId;
          if(target) onMove(bot.id,target);
        }}>⠿</span>}
      {onPin && <Pin name={bot.name} pinned onClick={() => onPin(bot.id)}/>}
      </div>
    </li>
  );
}

export interface BotListProps {
  bots: BotSummary[];
  selectedId: string | null;
  onSelect: (botId: string) => void;
}

export function BotList({ bots, selectedId, onSelect, onMove, onPin }: BotListProps & {onPin?:(id:string)=>void;onMove?:(source:string,target:string)=>void}): ReactElement {
  const refs = useRef(new Map<string, HTMLButtonElement>());
  const ordered = [...bots.filter(bot=>bot.id==='chives'),...bots.filter(bot=>bot.id!=='chives')];

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
      if (onMove && target && target.id!=='chives' && botId!=='chives') onMove(botId,target.id);
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
    <ul className="bot-list__list">{ordered.map(bot=><BotRow key={bot.id} bot={bot} onPin={onPin}
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
              aria-label={`${bot.name}，${botStatusLabel(bot)}${
                count > 0 ? `，${count} 项待你批准` : ''
              }`}
              title={bot.name}
            >
              <BotAvatar emblem={bot.avatar.emblem} tone={bot.avatar.tone} size={18} />
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
