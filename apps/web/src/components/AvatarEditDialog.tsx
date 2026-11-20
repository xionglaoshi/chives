import { useEffect, useId, useRef, useState } from 'react';
import type { KeyboardEvent, ReactElement } from 'react';

import type { BotSummary } from '@chives/server/protocol';

import {
  BotAvatar,
  EMBLEMS,
  EMBLEM_LABELS,
  isEmblem,
  isTone,
  type Emblem
} from '../brand/BotAvatar';
import type { BotPatch } from '../api/client';
import './AvatarEditDialog.css';

const EMBLEM_COLUMNS = 6;

export interface AvatarEditDialogProps {
  bot: BotSummary;
  defaults: { name: string; avatar: { emblem: string; tone: string } };
  onClose: () => void;
  onSave: (patch: BotPatch) => Promise<BotSummary>;
  onSaved: (bot: BotSummary) => void;
}

function moveFocus(
  event: KeyboardEvent<HTMLButtonElement>,
  values: readonly string[],
  current: string,
  columns: number,
  onPick: (value: string) => void,
  refs: Map<string, HTMLButtonElement>
): void {
  const index = values.indexOf(current);
  if (index < 0) return;
  let next: number;
  if (event.key === 'ArrowRight') next = (index + 1) % values.length;
  else if (event.key === 'ArrowLeft') next = (index - 1 + values.length) % values.length;
  else if (event.key === 'ArrowDown') next = (index + columns) % values.length;
  else if (event.key === 'ArrowUp') next = (index - columns + values.length) % values.length;
  else if (event.key === 'Home') next = 0;
  else if (event.key === 'End') next = values.length - 1;
  else return;
  event.preventDefault();
  const value = values[next];
  if (value === undefined) return;
  onPick(value);
  refs.get(value)?.focus();
}

export function AvatarEditDialog({
  bot,
  defaults,
  onClose,
  onSave,
  onSaved
}: AvatarEditDialogProps): ReactElement {
  const [name, setName] = useState(bot.name);
  const [emblem, setEmblem] = useState<Emblem>(
    isEmblem(bot.avatar.emblem) ? bot.avatar.emblem : 'crown'
  );
  const tone = isTone(bot.avatar.tone) ? bot.avatar.tone : 'gold';
  const [query,setQuery] = useState('');
  const term = query.trim().toLowerCase();
  const choices = EMBLEMS.filter(id => EMBLEM_LABELS[id].includes(term) || id.includes(term));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const titleId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const emblemRefs = useRef(new Map<string, HTMLButtonElement>());

  useEffect(() => {
    inputRef.current?.focus();
    const handleKeyDown = (event: globalThis.KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const save = async (patch: BotPatch): Promise<void> => {
    setSaving(true);
    setError(null);
    try {
      const saved = await onSave(patch);
      onSaved(saved);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '保存失败，请稍后再试');
    } finally {
      setSaving(false);
    }
  };

  const handleSave = (): void => {
    const trimmed = name.trim();
    if (/[\r\n]/.test(name)) {
      setError('称呼不能包含换行');
      return;
    }
    if ([...trimmed].length < 1 || [...trimmed].length > 12) {
      setError('称呼需要 1–12 个字符');
      return;
    }
    void save({ displayName: trimmed, avatar: { emblem, tone } });
  };

  const handleRestore = (): void => {
    void save({ displayName: null, avatar: null });
  };

  return (
    <div className="avatar-dialog__backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <div
        className="avatar-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <header className="avatar-dialog__header">
          <h2 className="avatar-dialog__title" id={titleId}>
            编辑头像与称呼
          </h2>
          <button
            type="button"
            className="avatar-dialog__close"
            onClick={onClose}
            aria-label="关闭"
          >
            ×
          </button>
        </header>

        <div className="avatar-dialog__preview">
          <BotAvatar emblem={emblem} tone={tone} size={72} name={name.trim() || bot.name} />
          <div className="avatar-dialog__preview-name">{name.trim() || defaults.name}</div>
        </div>

        <label className="avatar-dialog__label" htmlFor={`${titleId}-name`}>
          称呼
        </label>
        <input
          ref={inputRef}
          id={`${titleId}-name`}
          className="avatar-dialog__input"
          type="text"
          value={name}
          maxLength={12}
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              handleSave();
            }
          }}
          aria-describedby={`${titleId}-hint`}
        />
        <div className="avatar-dialog__hint" id={`${titleId}-hint`}>
          1–12 个字符；只影响显示，不改变它的能力与委派身份。
        </div>

        <div
          className="avatar-dialog__group"
          role="radiogroup"
          aria-label="选择 Bot 图标"
        >
          <label className="avatar-dialog__group-label" htmlFor={titleId+'-icons'}>Bot 图标库 · {choices.length} 款</label>
          <input id={titleId+'-icons'} className="avatar-dialog__input" type="search" placeholder="搜索图标，如「折线图」" value={query} onChange={e=>setQuery(e.target.value)}/>
          {!choices.length && <span role="status">没有匹配的图标</span>}
          <div className="avatar-dialog__emblems">
            {choices.map((value) => (
              <button
                key={value}
                ref={(element) => {
                  if (element === null) emblemRefs.current.delete(value);
                  else emblemRefs.current.set(value, element);
                }}
                type="button"
                role="radio"
                aria-checked={emblem === value}
                aria-label={EMBLEM_LABELS[value]}
                tabIndex={(choices.includes(emblem) ? emblem === value : choices[0] === value) ? 0 : -1}
                className={`avatar-dialog__emblem${
                  emblem === value ? ' avatar-dialog__emblem--selected' : ''
                }`}
                onClick={() => setEmblem(value)}
                onKeyDown={(event) =>
                  moveFocus(
                    event,
                    choices,
                    emblem,
                    EMBLEM_COLUMNS,
                    (next) => {
                      if (isEmblem(next)) setEmblem(next);
                    },
                    emblemRefs.current
                  )
                }
              >
                <BotAvatar emblem={value} tone={tone} size={18} />
                <span>{EMBLEM_LABELS[value]}</span>
              </button>
            ))}
          </div>
        </div>

        {error !== null ? (
          <div className="avatar-dialog__error" role="alert">
            {error}
          </div>
        ) : null}

        <footer className="avatar-dialog__footer">
          <button
            type="button"
            className="avatar-dialog__button avatar-dialog__button--primary"
            onClick={handleSave}
            disabled={saving}
          >
            保存
          </button>
          <button
            type="button"
            className="avatar-dialog__button"
            onClick={handleRestore}
            disabled={saving}
          >
            恢复默认
          </button>
          <button
            type="button"
            className="avatar-dialog__button avatar-dialog__button--quiet"
            onClick={onClose}
            disabled={saving}
          >
            取消
          </button>
        </footer>
      </div>
    </div>
  );
}
