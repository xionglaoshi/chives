import { useEffect, useRef, useState, type ReactElement } from 'react';
import { desk } from './deskApi';

import type { BotSummary } from '@chives/server/protocol';

import { BotPortraitPicker, botPortraitUrl } from './BotPortraitPicker';
import './BotsOverview.css';

export interface BotsOverviewProps {
  bots: BotSummary[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onEmploymentSaved?: (changes: ReadonlyMap<string, boolean>) => void;
  onPortraitSaved: (bot: BotSummary) => void;
  onOpenProfile: (botId: string, view: 'data' | 'tools') => void;
}

export function BotsOverview({
  bots,
  loading,
  error,
  onRetry,
  onEmploymentSaved,
  onPortraitSaved,
  onOpenProfile
}: BotsOverviewProps): ReactElement {
  const [portraitBot, setPortraitBot] = useState<BotSummary | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const [employmentBot, setEmploymentBot] = useState<BotSummary | null>(null);
  const [confirmHire, setConfirmHire] = useState<boolean | null>(null);
  const employmentDialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = employmentDialog.current;
    if (employmentBot && !dialog?.open) dialog?.showModal();
  }, [employmentBot]);

  function closeEmployment() {
    employmentDialog.current?.close();
    setEmploymentBot(null);
    setConfirmHire(null);
  }

  async function changeHire(bot: BotSummary, hire: boolean) {
    if (saving !== null || (bot.permanent ?? (bot.id === 'ceo'))) return;
    if ((bot.hired !== false) === hire) return;
    setSaving(bot.id);
    closeEmployment();
    setNotice('');
    const expected = Object.fromEntries(bots.map(b => [b.id, b.hired !== false]));
    const hiredIds = bots.filter(b => b.id === bot.id ? hire : b.hired !== false).map(b => b.id);
    try {
      const roster = await desk<{id:string; hired:boolean}[]>('employment','PUT',{expected,hiredIds});
      onEmploymentSaved?.(new Map(roster.map(b => [b.id,b.hired])));
      setNotice((hire ? '已聘用' : '已解雇') + bot.name);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '名册未保存，请重试。');
      onRetry();
    } finally {
      setSaving(null);
    }
  }
  const hiredCount = bots.filter(bot => bot.hired !== false).length;

  return (
    <div className="bots-overview">
      <header className="bots-overview__header">
        <h1 className="bots-overview__title">Bot市场</h1>
        {(!loading || bots.length > 0) && (error === null || bots.length > 0) && (
          <div className="bots-overview__stats" role="group" aria-label="Bot 在岗概览">
            <span>共 <strong>{bots.length}</strong> 位</span>
            <span className="bots-overview__on-duty"><strong>{hiredCount}</strong> 位在岗</span>
          </div>
        )}
      </header>

      {notice && <p role="status">{notice}</p>}
      {loading && bots.length === 0 ? (
        <div className="bots-overview__skeleton" role="status" aria-label="Bot 列表加载中">
          {Array.from({ length: 4 }, (_, index) => (
            <span className="skeleton bots-overview__skeleton-card" key={index} />
          ))}
        </div>
      ) : null}

      {!loading && bots.length === 0 ? (
        <div className="bots-overview__empty" role="status">
          {error === null ? '还没有可用的 Bot。' : `Bot 列表没有加载出来：${error}`}
          {error === null ? null : (
            <button type="button" className="bots-overview__retry" onClick={onRetry}>
              重试
            </button>
          )}
        </div>
      ) : null}

      <div className="bots-overview__grid">
        {bots.map((bot) => {
          const jobTitle = bot.name;
          return (
            <article
              className={`bots-overview__card${
                bot.background ? ' bots-overview__card--background' : ''
              }`}
              key={bot.id}
              aria-label={`${jobTitle} 资料卡`}
            >
              <div className="bots-overview__dossier">
                <div className="bots-overview__portrait">
                  <img src={botPortraitUrl(bot.portraitId ?? 'man-01')}
                    alt={`${jobTitle}的头像`} width={540} height={675}/>
                  <button type="button" aria-label={`更换${jobTitle}的头像`}
                    aria-haspopup="dialog" title="更换头像" onClick={() => setPortraitBot(bot)}>
                    <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                      <circle cx="8" cy="8" r="8" fill="#fff" />
                      <circle cx="8" cy="5.5" r="2.5" fill="#000" />
                      <path d="M3.5 12.5a4.5 4 0 0 1 9 0z" fill="#000" />
                    </svg>
                  </button>
                </div>
                <div className="bots-overview__identity">
                  <div className="bots-overview__identity-heading">
                    <h2 className="bots-overview__name">{jobTitle}</h2>
                    {bot.permanent ? <span className="bots-overview__employment is-hired" title="始终启用">常驻</span> : <button type="button"
                      className={`bots-overview__employment ${bot.hired === false ? 'is-unhired' : 'is-hired'}`}
                      aria-label={`${jobTitle} · ${bot.hired === false ? '未聘用' : '已聘用'}`}
                      aria-haspopup="dialog" disabled={saving !== null} onClick={() => setEmploymentBot(bot)}>
                      {bot.hired === false ? '未聘用' : '已聘用'}
                    </button>}
                  </div>
                  <p className="bots-overview__role">{bot.role}</p>
                </div>
              </div>

              <div className="bots-overview__actions">
                <a className="bots-overview__action bots-overview__tasks-link"
                  href={`#/settings?tab=tasks&bot=${encodeURIComponent(bot.id)}`}
                  aria-label={`${jobTitle}的现有任务`}>
                  现有任务
                </a>

                <button
                  type="button"
                  className="bots-overview__action"
                  onClick={() => onOpenProfile(bot.id, 'data')}
                >
                  Bot 数据
                </button>
                <button type="button" className="bots-overview__action" onClick={() => onOpenProfile(bot.id, 'tools')}>
                  工具管理
                </button>
              </div>
            </article>
          );
        })}
      </div>
      <dialog ref={employmentDialog} className="bots-overview__employment-dialog"
        aria-labelledby="bot-employment-title" onCancel={event => { event.preventDefault(); closeEmployment(); }}>
        {employmentBot && <>
          <h2 id="bot-employment-title">{confirmHire === null ? employmentBot.name : (confirmHire ? '确认雇佣' : '确认解雇')}</h2>
          {confirmHire === null ? (
            (employmentBot.permanent ?? (employmentBot.id === 'ceo')) ? <p>该岗位是常驻 Bot。</p> : null
          ) : <p>确定{confirmHire ? '雇佣' : '解雇'}「{employmentBot.name}」？</p>}
          <div className="bots-overview__employment-options">
            <button type="button" onClick={closeEmployment}>取消</button>
            {confirmHire === null ? <>
              <button type="button" disabled={employmentBot.hired !== false} onClick={() => setConfirmHire(true)}>雇佣</button>
              <button type="button" disabled={employmentBot.hired === false || (employmentBot.permanent ?? employmentBot.id === 'ceo')}
                onClick={() => setConfirmHire(false)}>解雇</button>
            </> : <button type="button" onClick={() => void changeHire(employmentBot, confirmHire)}>
              确认{confirmHire ? '雇佣' : '解雇'}
            </button>}
          </div>
        </>}
      </dialog>
      {portraitBot && <BotPortraitPicker key={portraitBot.id} bot={portraitBot}
        onClose={() => setPortraitBot(null)} onSaved={onPortraitSaved}/>}
    </div>
  );
}
