import { useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import type { BotSummary } from '@chives/server/protocol';
import { findConversations, type ConversationHit } from '../api/client';
import { searchEntries, type SearchEntry, type SearchGroup } from '../utils/globalSearch';
import { Markdown } from './Markdown';

interface Props {
  bots: BotSummary[];
  currentBot: BotSummary | null;
  onClose: () => void;
  onTimeline: () => void;
  onLocate: (hit: ConversationHit) => void;
}

const commandPages: Record<string, [string, string]> = {
  '/model':['打开模型设置','#/settings?tab=models'], '/settings':['打开设置','#/settings'],
  '/help':['打开技术文档','#/settings?tab=help']
};

const groups = ['全部','历史会话','设置','帮助文档','命令','工作台','Bot'] as const;
type Filter = typeof groups[number];

export default function GlobalSearch({bots, currentBot, onClose, onTimeline, onLocate}: Props) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<Filter>('全部');
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<{hits:ConversationHit[]; more:boolean} | null>(null);
  const [failed, setFailed] = useState(false);
  const [detail, setDetail] = useState<SearchEntry | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const back = useRef<HTMLButtonElement>(null);
  const term = query.trim();
  const includeHistory = filter === '全部' || filter === '历史会话';
  const sections = useMemo(() => {
    const matches = new Map<SearchGroup, SearchEntry[]>();
    for (const entry of searchEntries(term || (filter === '全部' || filter === '历史会话' ? '' : filter), bots)) {
      if (filter !== '全部' && filter !== entry.group) continue;
      const items = matches.get(entry.group);
      if (items) items.push(entry);
      else matches.set(entry.group,[entry]);
    }
    return Array.from(matches);
  }, [term, bots, filter]);

  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (typeof node.showModal === 'function') node.showModal();
    else node.setAttribute('open','');
    return () => { if (typeof node.close === 'function') node.close(); else node.removeAttribute('open'); };
  }, []);
  useEffect(() => {
    if (detail) back.current?.focus(); else input.current?.focus();
  }, [detail]);
  useEffect(() => {
    if (!term || !includeHistory) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void findConversations(term, offset, controller.signal).then(result => {
        if (!controller.signal.aborted) setPage(result);
      }).catch(() => { if (!controller.signal.aborted) setFailed(true); });
    }, 180);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [term, offset, includeHistory]);

  function clearPage() { setPage(null); setFailed(false); }
  function open(entry: SearchEntry) {
    if ('hash' in entry.destination) { onClose(); window.location.hash = entry.destination.hash; }
    else setDetail(entry);
  }
  function keyDown(event: KeyboardEvent<HTMLDialogElement>) {
    if (event.nativeEvent.isComposing) return;
    if (event.key === 'Escape') {
      event.preventDefault(); event.stopPropagation();
      if (detail) setDetail(null); else onClose();
      return;
    }
    if (detail) return;
    const buttons = Array.from(dialog.current?.querySelectorAll<HTMLButtonElement>('[data-search-result]') ?? []);
    const index = buttons.indexOf(event.target as HTMLButtonElement);
    if (!buttons.length || (event.target !== input.current && index < 0)) return;
    if (event.key === 'Enter' && index < 0) {
      event.preventDefault(); buttons[0]?.click();
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const next = event.key === 'ArrowDown' ? (index+1)%buttons.length : (index<1 ? buttons.length-1 : index-1);
      buttons[next]?.focus();
    }
  }
  const destination = detail?.destination;
  const webShortcut = destination && 'command' in destination
    ? commandPages[destination.command] : undefined;
  const noHistory = !includeHistory || page?.hits.length === 0;
  return <dialog className="global-search" ref={dialog} aria-label="全局搜索" onKeyDownCapture={keyDown}
    onCancel={event => {event.preventDefault(); if (detail) setDetail(null); else onClose();}}
    onClick={event => {
      if (event.target !== dialog.current) return;
      const rect = event.currentTarget.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose();
    }}>
    {detail && destination ? <>
      <header className="global-search__head">
        <button ref={back} type="button" className="global-search__back" onClick={() => setDetail(null)}>‹ 返回搜索结果</button>
        <button className="search-layer__close" onClick={onClose}>关闭</button>
      </header>
      <article className="global-search__detail">
        <small>{detail.group} · {'source' in destination ? destination.source : 'Chives CLI'}</small>
        <h2>{detail.title}</h2>
        {'body' in destination && <><Markdown>{destination.body}</Markdown>
          {destination.source.endsWith('.md') && <a href={'https://github.com/xionglaoshi/chives/blob/main/'+destination.source} target="_blank" rel="noopener noreferrer">查看完整文档</a>}</>}
        {'command' in destination && <><p>{detail.summary}</p><p>{destination.terminal ? '在系统终端输入' : '进入 Chives 终端的 Bot 对话后输入'}</p><pre><code>{destination.command}</code></pre>
          {webShortcut && <a href={webShortcut[1]} onClick={onClose}>{webShortcut[0]}</a>}</>}
      </article>
    </> : <>
      <header className="global-search__head"><input ref={input} type="search" className="search-layer__input"
        aria-label="搜索会话、设置、帮助和命令" placeholder="搜索会话、设置、帮助和命令…" maxLength={120} value={query}
        onChange={event => { const value = event.target.value;
          setQuery(value);
          if (value.trim() !== term) { setOffset(0); clearPage(); } }}/>
        <button className="search-layer__close" onClick={onClose}>关闭</button></header>
      <div className="global-search__filters" role="group" aria-label="搜索范围">
        {groups.map(name => <button key={name} aria-pressed={filter === name} onClick={() => {
          if (includeHistory !== (name === '全部' || name === '历史会话')) { clearPage(); setOffset(0); }
          setFilter(name); input.current?.focus();
        }}>{name}</button>)}
      </div>
      <div className="global-search__results">
        {!term && !sections.length && <p className="global-search__hint">试试股票名称、「思考强度」或 /model。</p>}
        {sections.map(([group, entries]) => <section key={group} aria-label={group+'搜索结果'}>
          <h3>{group}</h3>
          {entries.map(entry => <button data-search-result key={entry.title+entry.summary} className="global-search__result"
            onClick={() => open(entry)}><strong>{entry.title}</strong><small>{entry.summary}</small></button>)}
        </section>)}
        {term && includeHistory && <section aria-label="历史会话搜索结果">
          <h3>历史会话</h3>
          {failed ? <p role="status">暂时无法读取历史会话。</p> : !page ? <p role="status">正在搜索所有 Bot 的会话…</p> : <>
            {page.hits.length === 0 && sections.length > 0 && <p>没有匹配的会话。</p>}
            {page.hits.map(hit => {
              const at = hit.snippet.toLowerCase().indexOf(term.toLowerCase());
              return <button data-search-result className="conversation-hit" key={hit.botId+':'+hit.messageId} onClick={() => onLocate(hit)}>
                <span><strong>{bots.find(bot => bot.id === hit.botId)?.name ?? hit.botId}</strong>
                  <time dateTime={hit.createdAt}>{new Date(hit.createdAt).toLocaleDateString('zh-CN')}</time></span>
                <span>{at < 0 ? hit.snippet : <>{hit.snippet.slice(0, at)}<mark>{hit.snippet.slice(at, at+term.length)}</mark>{hit.snippet.slice(at+term.length)}</>}</span>
              </button>;
            })}
            {(offset > 0 || page.more) && <div className="conversation-pages">
              <button disabled={!offset} onClick={() => {clearPage();setOffset(offset-25);}}>上一页</button>
              <button disabled={!page.more} onClick={() => {clearPage();setOffset(offset+25);}}>下一页</button>
            </div>}
          </>}
        </section>}
        {term && !sections.length && noHistory && <p role="status">没有匹配的结果。</p>}
      </div>
      {currentBot && <button type="button" className="global-search__scope" onClick={onTimeline}>搜索与{currentBot.name}的时间线</button>}
    </>}
  </dialog>;
}
