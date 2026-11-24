import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import './theme/tokens.css';
import './styles/global.css';
import { App } from './index';
import {QuestionnairePage} from './components/InterviewForm';
import { loadAndApplyAppearance } from './theme/appearance';
import { syncBrowserState } from './utils/browserState';

const rootElement = document.getElementById('root');

if (rootElement === null) {
  throw new Error('Root element not found');
}

async function start(): Promise<void> {
  // Apply the saved theme before the first paint; use the system preference if settings are unavailable.
  await Promise.all([loadAndApplyAppearance(), syncBrowserState()]);
  createRoot(rootElement as HTMLElement).render(
    <StrictMode>
      {new URLSearchParams(location.search).get('interview')==='1'?<QuestionnairePage/>:<App/>}
    </StrictMode>
  );
}

void start();
