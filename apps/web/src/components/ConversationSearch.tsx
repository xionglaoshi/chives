import { useEffect, useRef, useState } from 'react';
import type { BotSummary } from '@chives/server/protocol';
import { findConversations, type ConversationHit } from '../api/client';

export function ConversationSearch({bots,onLocate}:{bots:BotSummary[];onLocate:(hit:ConversationHit)=>void}) {
  const [query,setQuery] = useState('');
  const [offset,setOffset] = useState(0);
  const [open,setOpen] = useState(false);
  const [results,setResults] = useState<ConversationHit[]>([]);
  const [more,setMore] = useState(false);
  const [status,setStatus] = useState<'loading'|'ready'|'error'>('loading');
  const root = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const term = query.trim();
  useEffect(()=>{
    if (!open || !term) return;
    const controller = new AbortController();
    setStatus('loading');
    const timer = window.setTimeout(()=>{
      void findConversations(term,offset,controller.signal).then(page=>{
        if (controller.signal.aborted) return;
        setResults(page.hits); setMore(page.more); setStatus('ready');
      }).catch(()=>{ if (!controller.signal.aborted) setStatus('error'); });
    },180);
    return ()=>{clearTimeout(timer);controller.abort();};
  },[term,offset,open]);
  useEffect(()=>{
    if (!open) return;
    const outside=(e:PointerEvent)=>{if (!root.current?.contains(e.target as Node)) setOpen(false);};
    document.addEventListener('pointerdown',outside);
    return ()=>document.removeEventListener('pointerdown',outside);
  },[open]);
  function pick(hit:ConversationHit) {setOpen(false); input.current?.blur(); onLocate(hit);}
  return <div className="conversation-search" ref={root} onKeyDown={e=>{
    if(e.key==='Escape') {setOpen(false);input.current?.blur();}
  }}>
    <label className="conversation-search__field">
      <svg viewBox="0 0 20 20" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.8"/><path d="m13 13 4 4"/></svg>
      <input ref={input} type="search" aria-label="搜索所有 Bot 的历史会话" placeholder="搜索历史会话" maxLength={120} value={query}
        onFocus={()=>setOpen(true)} onChange={e=>{setQuery(e.target.value);setOffset(0);setOpen(true);setStatus('loading');}}
        onKeyDown={e=>{
          if(e.key==='Enter' && !e.nativeEvent.isComposing && open && status==='ready' && results[0]) pick(results[0]);
          if(e.key==='ArrowDown') root.current?.querySelector<HTMLButtonElement>('.conversation-hit')?.focus();
        }}/>
    </label>
    {open && term && <section className="conversation-results" aria-label="跨 Bot 会话搜索结果">
      {status==='loading' ? <p role="status">正在搜索…</p> : status==='error' ? <p role="alert">搜索失败，请稍后再试。</p> : <>
        {!results.length && <p role="status">没有找到相关会话</p>}
        {results.map(hit=>{
          const at=hit.snippet.toLowerCase().indexOf(term.toLowerCase());
          return <button className="conversation-hit" key={hit.messageId} onClick={()=>pick(hit)}>
            <span><strong>{bots.find(b=>b.id===hit.botId)?.name ?? hit.botId}</strong>
              <time dateTime={hit.createdAt}>{new Date(hit.createdAt).toLocaleDateString('zh-CN')}</time></span>
            <span>{at<0 ? hit.snippet : <>{hit.snippet.slice(0,at)}<mark>{hit.snippet.slice(at,at+term.length)}</mark>{hit.snippet.slice(at+term.length)}</>}</span>
          </button>;
        })}
        {(offset>0||more) && <div className="conversation-pages"><button disabled={!offset} onClick={()=>setOffset(offset-25)}>上一页</button><button disabled={!more} onClick={()=>setOffset(offset+25)}>下一页</button></div>}
      </>}
    </section>}
  </div>;
}
