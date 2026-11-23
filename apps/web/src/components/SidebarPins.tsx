import { useEffect, useId, useRef, useState } from 'react';

export function useSidebarPins(group: string, defaults: readonly string[]) {
  const key = 'chives.sidebar.pins.' + (group === 'tools' ? 'tools.v3' : group);
  function read(): string[] {
    try {
      if (group === 'tools' && localStorage.getItem(key) === null) {
        const previous: unknown = JSON.parse(localStorage.getItem('chives.sidebar.pins.tools.v2') ?? 'null');
        if (Array.isArray(previous) && previous.every(id => typeof id === 'string')) return [...new Set([...previous,'watchlist'])];
        const legacy: unknown = JSON.parse(localStorage.getItem('chives.sidebar.pins.tools') ?? 'null');
        if (Array.isArray(legacy) && legacy.every(id => typeof id === 'string')) return [...new Set([...legacy, 'portrait', 'watchlist'])];
      }
      const saved: unknown = JSON.parse(localStorage.getItem(key) ?? 'null');
      if (Array.isArray(saved) && saved.every(id => typeof id === 'string')) return saved;
    } catch { /* Storage may be unavailable in private browsing. */ }
    return [...defaults];
  }
  const [pins, setPins] = useState(read);
  useEffect(() => {
    const sync = (event: StorageEvent) => { if (event.key === key || event.key === null) setPins(read()); };
    window.addEventListener('storage', sync);
    return () => window.removeEventListener('storage', sync);
  }, [key, defaults]);
  function toggle(id: string) {
    const next = pins.includes(id) ? pins.filter(item => item !== id) : [...pins, id];
    setPins(next);
    try { localStorage.setItem(key, JSON.stringify(next)); } catch { /* Retain the selection in this session. */ }
  }
  return { pins, toggle };
}

export function Pin({name, pinned, onClick}: {name:string; pinned:boolean; onClick:()=>void}) {
  const label = (pinned ? '取消固定' : '固定') + name;
  return <button type="button" className="sidebar-pin" aria-label={label} aria-pressed={pinned} title={label} onClick={onClick}>
    <svg viewBox="0 0 24 24" width="15" height="15" fill={pinned ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <g transform="rotate(35 12 12)"><path d="M8 4h8l-1 2v5l3 3v1H6v-1l3-3V6z"/><path d="M12 15v6"/></g>
    </svg>
    {!pinned && '固定'}
  </button>;
}

type Entry = {id:string; name:string};
export function HiddenMenu({label, items, open, pin}: {label:string; items:Entry[]; open:(id:string)=>void; pin:(id:string)=>void}) {
  const id = useId();
  const panel = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  return <div className="sidebar-more">
    <button type="button" ref={trigger} {...{ popovertarget: id }} aria-label={label} title={label} onClick={event => {
      const box = event.currentTarget.getBoundingClientRect();
      if (!panel.current) return;
      const space = window.innerHeight - box.bottom;
      Object.assign(panel.current.style, {
        left: Math.max(8, Math.min(box.left, window.innerWidth - 240)) + 'px',
        top: space >= 180 ? box.bottom + 4 + 'px' : 'auto',
        bottom: space >= 180 ? 'auto' : window.innerHeight - box.top + 4 + 'px',
        maxHeight: Math.min(320, (space >= 180 ? space : box.top) - 12) + 'px'
      });
    }}><b aria-hidden="true">···</b><span>{label}</span></button>
    <div {...{ popover: "auto" }} id={id} ref={panel} className="sidebar-pin-menu" aria-label={label}>
      {items.length === 0 && <p>{label === '更多工具' ? '所有工具均已固定' : '所有 Bot 均已固定'}</p>}
      {items.map(item => <div className="sidebar-pin-row" key={item.id}>
        <button className="sidebar-menu-link" onClick={() => { panel.current?.hidePopover(); open(item.id); }}>{item.name}</button>
        <Pin name={item.name} pinned={false} onClick={() => { pin(item.id); panel.current?.hidePopover(); trigger.current?.focus(); }}/>
      </div>)}
    </div>
  </div>;
}
