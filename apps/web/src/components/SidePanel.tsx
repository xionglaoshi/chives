import { useCallback, useEffect, useLayoutEffect, useState } from 'react';
import type { ReactElement } from 'react';

import { toolbarPanels, type PanelContentProps, type ToolbarPanelId } from './toolbarPanels';
import './ExpertSidebar.css';

const NARROW_WIDTH = 960;
const HIDE_AMOUNTS_KEY = 'chives.expertSidebar.hideAmounts';

function isNarrow(): boolean {
  return window.innerWidth < NARROW_WIDTH;
}

function readBool(key: string, fallback: boolean): boolean {
  try {
    const raw = window.localStorage.getItem(key);
    if (raw === '1') return true;
    if (raw === '0') return false;
    return fallback;
  } catch {
    return fallback;
  }
}

function writeBool(key: string, value: boolean): void {
  try {
    window.localStorage.setItem(key, value ? '1' : '0');
  } catch {
    // A blocked localStorage must not break the panel.
  }
}

export interface SidePanelState {
  open: ToolbarPanelId[];
  narrow: boolean;
  toggle: (panel: ToolbarPanelId) => void;
}

export function useSidePanelState(conversationId: string | null): SidePanelState {
  const [narrow, setNarrow] = useState(isNarrow);
  const [open, setOpen] = useState<ToolbarPanelId[]>([]);
  useLayoutEffect(() => {
    if (conversationId !== null) setOpen([]);
  }, [conversationId]);
  useEffect(() => {
    const onResize = (): void => setNarrow(isNarrow());
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  const toggle = (panel: ToolbarPanelId): void => {
    setOpen(current => toolbarPanels.map(entry => entry.id).filter(id =>
      id === panel ? !current.includes(id) : current.includes(id)));
  };
  return { open, narrow, toggle };
}

interface SectionProps extends Omit<PanelContentProps, 'hidden'> {
  entry: typeof toolbarPanels[number];
}

function SidePanelSection({ entry, ...props }: SectionProps): ReactElement {
  const [hidden, setHidden] = useState<boolean>(() => readBool(HIDE_AMOUNTS_KEY, false));
  const title = entry.label;

  const toggleHidden = useCallback((): void => {
    setHidden((current) => {
      writeBool(HIDE_AMOUNTS_KEY, !current);
      return !current;
    });
  }, []);

  return (
    <section className="expert-sidebar__block" aria-label={`${title}面板`}>
      <header className="expert-sidebar__header">
        <span className="expert-sidebar__title">{title}</span>
        <div className="expert-sidebar__actions">
          {entry.id === 'portfolio' ? (
            <label>
              隐藏金额
              <input type="checkbox" role="switch" checked={hidden} onChange={toggleHidden} />
            </label>
          ) : null}
        </div>
      </header>
      <div className="expert-sidebar__block-body"><entry.Content {...props} hidden={hidden}/></div>
    </section>
  );
}

export interface SidePanelProps extends Omit<SectionProps, 'entry'> {
  /** Open panels, top to bottom. */
  panels: readonly ToolbarPanelId[];
  narrow: boolean;
}

export function SidePanel({ panels, narrow, ...section }: SidePanelProps): ReactElement {
  return (
    <aside
      className={`expert-sidebar${narrow ? ' expert-sidebar--overlay' : ''}`}
      aria-label="右侧面板"
    >
      <div className="expert-sidebar__stack">
        {toolbarPanels.filter(entry => panels.includes(entry.id)).map(entry => (
          <SidePanelSection key={entry.id} entry={entry} {...section} />
        ))}
      </div>
    </aside>
  );
}
