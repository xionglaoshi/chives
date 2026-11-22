import { useCallback, useEffect, useId, useRef, useState, useSyncExternalStore } from 'react';
import type { ReactNode } from 'react';

import './ResponsiveNavigation.css';

const phoneQuery = '(max-width: 720px), (pointer: coarse) and (max-width: 960px) and (max-height: 520px)';
function phoneLayout() { return window.matchMedia?.(phoneQuery).matches ?? false; }
function subscribeLayout(notify: () => void) {
  const media = window.matchMedia?.(phoneQuery);
  media?.addEventListener('change', notify);
  return () => media?.removeEventListener('change', notify);
}

interface NavigationProps {
  label: string;
  shortLabel: string;
  closeLabel: string;
  children: (close: () => void, phone: boolean) => ReactNode;
}

/** The same navigation tree is persistent on desktop and modal on a phone. */
export function ResponsiveNavigation({ label, shortLabel, closeLabel, children }: NavigationProps) {
  const phone = useSyncExternalStore(subscribeLayout, phoneLayout, () => false);
  const sheet = useRef<HTMLDialogElement>(null);
  const id = useId();
  const [open, setOpen] = useState(false);
  const close = useCallback(() => sheet.current?.close(), []);
  useEffect(() => {
    if (!phone) { setOpen(false); return; }
    window.addEventListener('hashchange', close);
    return () => window.removeEventListener('hashchange', close);
  }, [phone, close]);

  if (!phone) return <>{children(close, false)}</>;
  return <>
    <button type="button" className="mobile-nav-trigger" aria-label={label} aria-haspopup="dialog"
      aria-controls={id} aria-expanded={open}
      onClick={() => { sheet.current?.showModal(); setOpen(true); }}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden="true">
        <path d="M4 6h16M4 12h12M4 18h16"/>
      </svg>
      <span>{shortLabel}</span>
    </button>
    <dialog id={id} ref={sheet} className="mobile-nav-sheet" aria-label={label}
      onClose={() => setOpen(false)} onClick={event => {
        if (event.target === event.currentTarget) close();
      }}>
      <div className="mobile-nav-sheet__body">
        <button type="button" onClick={close} className="mobile-nav-sheet__close" aria-label={closeLabel}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
            <path d="m6 6 12 12M18 6 6 18"/>
          </svg>
        </button>
        {children(close, true)}
      </div>
    </dialog>
  </>;
}
