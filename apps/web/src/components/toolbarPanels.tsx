import type { ReactElement, ReactNode } from 'react';
import { ExpertSidebarMarket } from './ExpertSidebarMarket';
import { ExpertSidebarPortfolio } from './ExpertSidebarPortfolio';
import { useExpertSidebarData } from './ExpertSidebarData';
import { WatchesPanel } from './WatchesPanel';

export interface PanelContentProps {
  botId?: string;
  taskClosedToken: number;
  watchRevision: number;
  hidden: boolean;
  onPickName: (name: string) => void;
  onEditWatch: (label: string, botId: string) => void;
  onLocateTask: (taskId: string, botId: string) => void;
  onCancelWatch: (watchId: string) => Promise<void>;
}

interface ToolbarPanel {
  id: string;
  label: string;
  icon: ReactNode;
  Content: (props: PanelContentProps) => ReactElement;
}

// One ordered entry supplies both the shortcut and its on-demand sidebar content.
export const toolbarPanels = [
  {
    id: 'watches', label: '盯盘',
    icon: <><circle cx="8" cy="8" r="4.8"/><circle cx="8" cy="8" r="1.6" fill="currentColor" stroke="none"/><path d="M8 1.2v2M8 12.8v2M1.2 8h2M12.8 8h2"/></>,
    Content: ({ botId, watchRevision, onEditWatch, onLocateTask, onCancelWatch }) =>
      <WatchesPanel botId={botId} revision={watchRevision} onEditWatch={onEditWatch} onLocateTask={onLocateTask} onCancelWatch={onCancelWatch}/>
  },
  {
    id: 'portfolio', label: '持仓',
    icon: <><rect x="2" y="4" width="12" height="9" rx="1.5"/><path d="M2 7h12M10.5 10.5h2"/></>,
    Content: function Portfolio({ taskClosedToken, hidden, onPickName }) {
      const { portfolio } = useExpertSidebarData('portfolio', taskClosedToken);
      return <ExpertSidebarPortfolio state={portfolio} hidden={hidden} onPickName={onPickName}/>;
    }
  },
  {
    id: 'market', label: '行情',
    icon: <><path d="M2 12.5L6 8l3 2.5L14 4" strokeLinecap="round" strokeLinejoin="round"/><path d="M2 2v12h12" strokeLinecap="round" opacity=".55"/></>,
    Content: function Market({ taskClosedToken }) {
      const { market } = useExpertSidebarData('market', taskClosedToken);
      return <ExpertSidebarMarket state={market}/>;
    }
  }
] as const satisfies readonly ToolbarPanel[];

export type ToolbarPanelId = typeof toolbarPanels[number]['id'];
