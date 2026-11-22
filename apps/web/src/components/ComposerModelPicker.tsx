import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { ComposerModelMenu, ComposerModelState, ModelTuning } from '@chives/server/protocol';
import { readComposerMenu, readComposerSelection, saveComposerModel } from '../api/client';
import { effortNames } from './modelTuning';
import './ComposerModelPicker.css';

function Bolt() {
  return <svg aria-hidden="true" width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M9.3 1.6 3.5 9h4.2l-1 5.4L13 6.7H8.6z" strokeLinejoin="round"/></svg>;
}

function sameModel(a:ComposerModelState,b:ComposerModelState) {
  return a.connection===b.connection && a.model===b.model && a.followsGlobal===b.followsGlobal &&
    a.tuning.reasoningEffort===b.tuning.reasoningEffort && !!a.tuning.fastMode===!!b.tuning.fastMode;
}

function ModelChoices({menu,draft,onSelect,disabled}:{
  menu:ComposerModelMenu; draft:ComposerModelState; onSelect:(selection:ComposerModelState)=>void; disabled:boolean;
}) {
  const [expanded,setExpanded]=useState(false);
  const [query,setQuery]=useState('');
  const trigger=useRef<HTMLButtonElement>(null);
  const list=useRef<HTMLDivElement>(null);
  function close(){setExpanded(false);setQuery('');trigger.current?.focus();}
  const entries=[{label:'跟随全局默认',hint:menu.global.model,selection:menu.global},
    ...menu.choices.map(c=>({label:c.model,hint:c.label===c.model?'':c.label,
      selection:{model:c.model,connection:c.connection,tuning:c.defaults,followsGlobal:false}}))];
  const options=entries.filter(e=>(e.label+' '+e.hint).toLowerCase().includes(query.trim().toLowerCase()));
  return <div className="composer-model__field" onKeyDown={e=>{
    if(!expanded || e.nativeEvent.isComposing) return;
    if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close();return;}
    const buttons=Array.from(list.current?.querySelectorAll<HTMLButtonElement>('[role=option]') ?? []);
    if(!buttons.length)return;
    const index=buttons.indexOf(e.target as HTMLButtonElement);
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){
      e.preventDefault();
      buttons[e.key==='ArrowDown'?(index+1)%buttons.length:index<=0?buttons.length-1:index-1]?.focus();
    } else if(e.key==='Enter' && e.target instanceof HTMLInputElement){e.preventDefault();buttons[0]?.click();}
  }}>
    <button className="composer-model__choice" ref={trigger} aria-label="选择可用模型" aria-haspopup="listbox"
      aria-expanded={expanded} disabled={disabled} onClick={()=>{setExpanded(!expanded);setQuery('');}}>
      <span>模型</span><strong>{draft.model==='default'?'全局默认':draft.model}</strong><span aria-hidden="true">⌄</span>
    </button>
    {expanded && <div className="composer-model__options">
      <input autoFocus type="search" aria-label="查找模型" placeholder="查找模型…" value={query} onChange={e=>setQuery(e.target.value)}/>
      <div ref={list} role="listbox" aria-label="可用模型">{options.map(({label,hint,selection})=>{
        const checked=draft.followsGlobal===selection.followsGlobal && (draft.followsGlobal ||
          (draft.connection===selection.connection && draft.model===selection.model));
        return <button key={(selection.followsGlobal?'global':selection.connection)+'/'+selection.model}
          role="option" aria-selected={checked} onClick={()=>{if(!checked)onSelect(selection);close();}}>
          <span>{label}{hint && <small>{hint}</small>}</span>{checked && <span aria-hidden="true">✓</span>}
        </button>;
      })}</div>
      {!options.length && <small>没有匹配的模型</small>}
    </div>}
  </div>;
}

export function ComposerModelPicker({botId,running,disabled}:{botId:string;running:boolean;disabled:boolean}) {
  const trigger=useRef<HTMLButtonElement>(null);
  const dialog=useRef<HTMLDialogElement>(null);
  const [current,setCurrent]=useState<ComposerModelState|null>(null);
  const [open,setOpen]=useState(false);
  const [menu,setMenu]=useState<ComposerModelMenu|null>(null);
  const [draft,setDraft]=useState<ComposerModelState|null>(null);
  const [error,setError]=useState('');
  const [saving,setSaving]=useState(false);
  const [retry,refresh]=useState(0);

  useEffect(()=>{
    if(open) return;
    let pending:AbortController | undefined;
    function refreshCurrent() {
      pending?.abort();
      const abort=new AbortController();pending=abort;
      void readComposerSelection(botId,abort.signal).then(result=>{
        if(!abort.signal.aborted) setCurrent(result.current);
      }).catch(()=>{});
    }
    refreshCurrent();
    window.addEventListener('focus',refreshCurrent);
    return ()=>{pending?.abort();window.removeEventListener('focus',refreshCurrent);};
  },[botId,open]);

  useEffect(()=>{
    if(!open) return;
    const abort=new AbortController();
    setError(''); setMenu(null); setDraft(null);
    void readComposerMenu(botId,abort.signal).then(result=>{
      if(abort.signal.aborted) return;
      setMenu(result); setDraft(result.current); setCurrent(result.current);
    }).catch(cause=>{if(!abort.signal.aborted)setError(cause.message);});
    return ()=>abort.abort();
  },[open,botId,retry]);

  useLayoutEffect(()=>{
    if(!open || !dialog.current || !trigger.current) return;
    const popup=dialog.current, button=trigger.current;
    function position(){
      const rect=button.getBoundingClientRect(), gap=8;
      const above=rect.top-gap, below=window.innerHeight-rect.bottom-gap;
      const up=above>=Math.min(350,below);
      popup.style.maxHeight=Math.max(80,(up?above:below)-gap)+'px';
      popup.style.left=Math.max(gap,Math.min(rect.right-popup.offsetWidth,window.innerWidth-popup.offsetWidth-gap))+'px';
      popup.style.top=up?'auto':rect.bottom+gap+'px';
      popup.style.bottom=up?window.innerHeight-rect.top+gap+'px':'auto';
    }
    popup.showModal();
    position();
    window.addEventListener('resize',position);
    window.addEventListener('scroll',position,true);
    return ()=>{
      window.removeEventListener('resize',position);
      window.removeEventListener('scroll',position,true);
      popup.close();
    };
  },[open]);

  const choice=menu?.choices.find(c=>c.connection===draft?.connection && c.model===draft?.model);
  const receipt=choice?.subscription && menu?.receipt?.requestedModel===choice.model ? menu.receipt : null;
  const tier=(value:string|null)=>value==='priority' || value==='fast' ? '快速' : value==='default' ? '标准' : value || '未报告';
  const dirty=!!(menu && draft && !sameModel(draft,menu.current));
  function tune(tuning:ModelTuning) {
    if(draft) {setError('');setDraft({...draft,tuning,followsGlobal:false});}
  }
  async function apply() {
    if(!draft || !dirty || saving || running) return;
    setSaving(true);setError('');
    try {
      const result=await saveComposerModel(botId,draft.followsGlobal ? {followGlobal:true} :
        {connection:draft.connection,model:draft.model,tuning:draft.tuning});
      setCurrent(result);setOpen(false);
    } catch(cause) {setError(cause instanceof Error?cause.message:'保存失败，请重试');}
    finally {setSaving(false);}
  }
  const modelName=current?.model && current.model!=='default' ? current.model : '模型';
  const label=current?.tuning.reasoningEffort ? effortNames[current.tuning.reasoningEffort] : '';
  return <>
    <button ref={trigger} type="button" className="composer-model__trigger" aria-label={'选择模型与思考强度，当前'+modelName}
      aria-haspopup="dialog" aria-expanded={open} disabled={disabled}
      title={[modelName,label && label+'强度',current?.tuning.fastMode && '快速模式'].filter(Boolean).join(' · ')}
      onClick={()=>{setMenu(null);setDraft(null);setError('');setOpen(true);}}>
      <span className="composer-model__name">{modelName}</span>{label && <span className="composer-model__effort">{label}</span>}
      {current?.tuning.fastMode && <Bolt/>}
      <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true"><path d="m3 5 3 3 3-3" strokeLinecap="round" strokeLinejoin="round"/></svg>
    </button>
    {open && createPortal(<dialog ref={dialog} className="composer-model__popup" aria-label="对话模型"
      onCancel={e=>{e.preventDefault();if(!saving)setOpen(false);}}
      onClick={e=>{
        if(e.target!==dialog.current || saving)return;
        const r=e.currentTarget.getBoundingClientRect();
        if(e.clientX<r.left || e.clientX>r.right || e.clientY<r.top || e.clientY>r.bottom)setOpen(false);
      }}>
      <header><strong>对话模型</strong><button aria-label="关闭模型菜单" disabled={saving} onClick={()=>setOpen(false)}>×</button></header>
      {menu && draft ? <>
        <ModelChoices menu={menu} draft={draft} disabled={saving} onSelect={selected=>{setError('');setDraft(selected);}}/>
        {choice && choice.efforts.length>0 && <fieldset disabled={saving} className="composer-model__levels">
          <legend>思考强度</legend>
          {[undefined,...choice.efforts].map(level=><label key={level ?? 'auto'}>
            <input type="radio" name="composer-effort" checked={draft.tuning.reasoningEffort===level}
              onChange={()=>tune({...(draft.tuning.fastMode ? {fastMode:true} : {}),...(level ? {reasoningEffort:level} : {})})}/>
            <span>{level ? effortNames[level] : '自动'}</span></label>)}
        </fieldset>}
        {choice?.fast && <label className="composer-model__speed">
          <span><Bolt/>快速模式</span><input type="checkbox" role="switch" checked={!!draft.tuning.fastMode}
            disabled={saving} onChange={e=>tune({...draft.tuning,fastMode:e.target.checked})}/>
        </label>}
        {choice?.fast && <small className="composer-model__speed-note">
          {receipt ? <>上次请求{tier(receipt.requestedTier ?? 'default')}，服务端回报{tier(receipt.tier)}。</> : '快速模式请求优先处理，可能消耗更多订阅额度。'}
        </small>}
        {menu.subscriptionUnavailable && <small>Codex 订阅目录暂不可用，可在模型设置中检查授权。</small>}
        {!menu.choices.length && <a href="#/settings?tab=models" onClick={()=>setOpen(false)}>去设置模型连接</a>}
        <footer><small>{running?'当前任务结束后可切换':'仅此 Bot · 下条消息生效'}</small>
          <button className="composer-model__apply" disabled={!dirty || saving || running} onClick={()=>void apply()}>{saving?'保存中…':'应用'}</button></footer>
      </> : !error && <small role="status">正在读取可用模型…</small>}
      {error && <div role="alert" className="composer-model__error">{error} <button disabled={saving} onClick={()=>refresh(n=>n+1)}>重新读取</button></div>}
    </dialog>,document.body)}
  </>;
}
