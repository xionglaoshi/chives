import { useCallback, useEffect, useState } from 'react';
import type { ReactElement, ReactNode } from 'react';

import type { BotPanel } from '@chives/server/protocol';

import { useExpertSidebarData } from './ExpertSidebarData';
import { ExpertSidebarMarket } from './ExpertSidebarMarket';
import { ExpertSidebarPortfolio } from './ExpertSidebarPortfolio';
import { StrategyPanel } from './StrategyPanel';
import { WatchesPanel } from './WatchesPanel';
import { panelLabel, strategyIdOfPanel } from '../utils/panels';
import './ExpertSidebar.css';

const NARROW_WIDTH = 960;
// v2: earlier builds stored partial choices that left panels closed; start everyone from "all open".
const PANEL_KEY_PREFIX = 'chives.panel.v2.';
const HIDE_AMOUNTS_KEY = 'chives.expertSidebar.hideAmounts';

/** Base labels kept for callers that only deal with the built-in panels. */
export const PANEL_LABELS: Record<string, string> = {
  market: '行情',
  portfolio: '持仓',
  watches: '盯盘'
};

function isNarrow(): boolean {
  return window.innerWidth < NARROW_WIDTH;
}

function panelKey(botId: string): string {
  return `${PANEL_KEY_PREFIX}${botId}`;
}

function readStoredPanels(botId: string | null, panels: readonly BotPanel[]): BotPanel[] {
  if (botId === null || isNarrow()) return [];
  try {
    const raw = window.localStorage.getItem(panelKey(botId));
    // First visit to this bot: show all of its panels; after that, keep the user's choice.
    if (raw === null) return [...panels];
    const stored = raw.split(',').filter((entry) => entry.length > 0);
    return panels.filter((panel) => stored.includes(panel));
  } catch {
    return [];
  }
}

function writeStoredPanels(botId: string | null, open: readonly BotPanel[]): void {
  if (botId === null) return;
  try {
    if (open.length === 0) window.localStorage.removeItem(panelKey(botId));
    else window.localStorage.setItem(panelKey(botId), open.join(','));
  } catch {
    // A blocked localStorage must not break the panel.
  }
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
  /** Open panels in the bot's configured order; several can be open at once. */
  open: BotPanel[];
  /** Below 960px the panels float over the chat instead of taking a column. */
  narrow: boolean;
  toggle: (panel: BotPanel) => void;
  close: () => void;
}

/**
 * Each header button opens or closes its own panel; open panels stack in one
 * column. Remembered per bot; a narrow window starts with none open.
 */
export function useSidePanelState(
  botId: string | null,
  panels: readonly BotPanel[]
): SidePanelState {
  const panelsKey = panels.join(',');
  const [narrow, setNarrow] = useState<boolean>(isNarrow);
  const [open, setOpen] = useState<BotPanel[]>(() => readStoredPanels(botId, panels));

  useEffect(() => {
    if (botId === null) return;
    setOpen(readStoredPanels(botId, panels));
  }, [botId, panelsKey]);

  useEffect(() => {
    if (open.some((panel) => !panels.includes(panel))) {
      const kept = open.filter((panel) => panels.includes(panel));
      setOpen(kept);
      writeStoredPanels(botId, kept);
    }
  }, [botId, panelsKey, open, panels]);

  useEffect(() => {
    const onResize = (): void => setNarrow(isNarrow());
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const toggle = useCallback(
    (panel: BotPanel): void => {
      setOpen((current) => {
        const wanted = current.includes(panel)
          ? current.filter((entry) => entry !== panel)
          : [...current, panel];
        const next = panels.filter((entry) => wanted.includes(entry));
        writeStoredPanels(botId, next);
        return next;
      });
    },
    [botId, panelsKey]
  );

  const close = useCallback((): void => {
    setOpen([]);
    writeStoredPanels(botId, []);
  }, [botId]);

  return { open, narrow, toggle, close };
}

interface SectionProps {
  botId: string;
  panel: BotPanel;
  taskClosedToken: number;
  watchRevision: number;
  onPickName: (name: string) => void;
  onEditWatch: (label: string) => void;
  onLocateTask: (taskId: string) => void;
  onCancelWatch: (watchId: string) => Promise<void>;
}

/** One panel block; each has its own data hook, so only open panels fetch and poll. */
function SidePanelSection({
  botId,
  panel,
  taskClosedToken,
  watchRevision,
  onPickName,
  onEditWatch,
  onLocateTask,
  onCancelWatch
}: SectionProps): ReactElement {
  const [hidden, setHidden] = useState<boolean>(() => readBool(HIDE_AMOUNTS_KEY, false));
  const data = useExpertSidebarData(panel, taskClosedToken);
  const title = panelLabel(panel);
  const strategyId = strategyIdOfPanel(panel);

  const toggleHidden = useCallback((): void => {
    setHidden((current) => {
      writeBool(HIDE_AMOUNTS_KEY, !current);
      return !current;
    });
  }, []);

  let body: ReactNode;
  if (strategyId !== null) {
    body = (
      <StrategyPanel
        botId={botId}
        strategyId={strategyId}
        taskClosedToken={taskClosedToken}
        onPickName={onPickName}
      />
    );
  } else if (panel === 'market') {
    body = <ExpertSidebarMarket state={data.market} />;
  } else if (panel === 'portfolio') {
    body = (
      <ExpertSidebarPortfolio state={data.portfolio} hidden={hidden} onPickName={onPickName} />
    );
  } else {
    body = (
      <WatchesPanel
        botId={botId}
        revision={watchRevision}
        onEditWatch={onEditWatch}
        onLocateTask={onLocateTask}
        onCancelWatch={onCancelWatch}
      />
    );
  }

  return (
    <section className="expert-sidebar__block" aria-label={`${title}面板`}>
      <header className="expert-sidebar__header">
        <span className="expert-sidebar__title">{title}</span>
        <div className="expert-sidebar__actions">
          {panel === 'portfolio' ? (
            <label>
              隐藏金额
              <input type="checkbox" role="switch" checked={hidden} onChange={toggleHidden} />
            </label>
          ) : null}
        </div>
      </header>
      <div className="expert-sidebar__block-body">{body}</div>
    </section>
  );
}

export interface SidePanelProps extends Omit<SectionProps, 'panel'> {
  /** Open panels, top to bottom. */
  panels: readonly BotPanel[];
  narrow: boolean;
}

export function SidePanel({ panels, narrow, ...section }: SidePanelProps): ReactElement {
  return (
    <aside
      className={`expert-sidebar${narrow ? ' expert-sidebar--overlay' : ''}`}
      aria-label="右侧面板"
    >
      <div className="expert-sidebar__stack">
        {panels.map((panel) => (
          <SidePanelSection key={panel} panel={panel} {...section} />
        ))}
      </div>
    </aside>
  );
}
