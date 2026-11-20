import { StrictMode, useState } from 'react';
import { createRoot } from 'react-dom/client';
import type { ReactElement } from 'react';

import type { DeliverableDto } from '@chives/server/protocol';

import { Markdown } from '../components/Markdown';
import { applyAppearance } from '../theme/appearance';
import '../theme/tokens.css';
import '../styles/global.css';
import { SAMPLE_MESSAGE } from './sample';
import './dev.css';

const SAMPLE_REPORT: DeliverableDto = {
  id: 'dev-report',
  taskId: 'dev-task',
  botId: 'expert',
  path: 'reports/liugong_20261117.md',
  kind: 'markdown',
  size: 4096,
  createdAt: '2026-11-17T10:00:00.000Z'
};

type Theme = 'dark' | 'light';

function initialTheme(): Theme {
  const requested = new URLSearchParams(window.location.search).get('theme');
  return requested === 'light' ? 'light' : 'dark';
}

function DevSample(): ReactElement {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  const toggle = (): void => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    applyAppearance({ theme: next, changeColor: 'red-up' });
  };

  return (
    <div className="dev">
      <header className="dev__header">
        <div>
          <div className="dev__title">T148 渲染样例</div>
          <div className="dev__hint">
            图片指向 <code>dev/chart.png</code>
            （bot 工作目录）。服务端没有该文件时显示“图片未找到”卡片；把图片放进
            <code>runtime/bots/expert/workspace/dev/chart.png</code> 后刷新即可看到成图。
          </div>
        </div>
        <button type="button" className="dev__button" onClick={toggle}>
          切换为{theme === 'dark' ? '浅色' : '深色'}
        </button>
      </header>
      <main className="dev__canvas">
        <Markdown
          botId="expert"
          deliverables={[SAMPLE_REPORT]}
          onOpenDeliverable={() => undefined}
        >
          {SAMPLE_MESSAGE}
        </Markdown>
      </main>
    </div>
  );
}

const rootElement = document.getElementById('root');

if (rootElement === null) {
  throw new Error('Root element not found');
}

applyAppearance({ theme: initialTheme(), changeColor: 'red-up' });
createRoot(rootElement).render(
  <StrictMode>
    <DevSample />
  </StrictMode>
);
