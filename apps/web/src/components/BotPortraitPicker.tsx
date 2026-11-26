import { useEffect, useRef, useState } from 'react';
import type { BotPortraitDto, BotSummary } from '@chives/server/protocol';
import { appPath } from '../appPath';

export function botPortraitUrl(id: string): string {
  return appPath(`/bot-portraits/${encodeURIComponent(id)}.webp`);
}

type Group = BotPortraitDto['group'];
const sections: readonly [Group, string][] = [
  ['man', '男'], ['woman', '女'],
];

export function BotPortraitPicker({ bot, onClose, onSaved }: {
  bot: BotSummary;
  onClose: () => void;
  onSaved: (bot: BotSummary) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [portraits, setPortraits] = useState<BotPortraitDto[]>([]);
  const [selected, setSelected] = useState(bot.portraitId ?? 'man-01');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    const access = new AbortController();
    fetch(appPath('/api/bot-portraits'), { signal: access.signal })
      .then(async response => {
        if (!response.ok) throw new Error('暂时无法读取头像库。');
        const values = await response.json() as BotPortraitDto[];
        if (!values.length) throw new Error('头像库里暂无可选图片。');
        if (!access.signal.aborted) setPortraits(values);
      }).catch(error => { if (!access.signal.aborted) setError(String(error.message)); });
    return () => { access.abort(); element?.close(); };
  }, []);

  async function apply() {
    setBusy(true);
    setError('');
    try {
      const response = await fetch(appPath(`/api/bots/${encodeURIComponent(bot.id)}/portrait`), {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ portraitId: selected }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.message ?? '没能保存头像。');
      onSaved(result as BotSummary);
      onClose();
    } catch (error) {
      setError(error instanceof Error ? error.message : '没能保存头像。');
    } finally {
      setBusy(false);
    }
  }

  return <dialog ref={dialog} className="portrait-picker" aria-labelledby="portrait-picker-title"
    onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <header><h2 id="portrait-picker-title">更换头像</h2><p>{bot.name}</p></header>
    {portraits.length > 0 ? (
      <div className="portrait-picker__groups">
        {sections.map(([id, label]) => (
          <section key={id} className="portrait-picker__column" aria-labelledby={`portrait-group-${id}`}>
            <h3 id={`portrait-group-${id}`}>{label}</h3>
            <div className="portrait-picker__options">
              {portraits.filter(portrait => portrait.group === id).map(portrait => (
                <button type="button" key={portrait.id} aria-pressed={selected === portrait.id}
                  disabled={busy} onClick={() => setSelected(portrait.id)}>
                  <img src={botPortraitUrl(portrait.id)} alt="" loading="lazy" width="144" height="180"/>
                  <span>{portrait.name}</span>
                </button>
              ))}
            </div>
          </section>
        ))}
      </div>
    ) : !error && <p className="portrait-picker__loading" role="status">正在读取头像库…</p>}
    {error && <p className="portrait-picker__error" role="alert">{error}</p>}
    <footer>
      <button type="button" disabled={busy} onClick={onClose}>取消</button>
      <button type="button" disabled={busy || !portraits.some(p => p.id === selected)} onClick={() => void apply()}>
        {busy ? '保存中…' : '使用头像'}</button>
    </footer>
  </dialog>;
}
