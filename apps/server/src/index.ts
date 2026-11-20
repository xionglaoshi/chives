import type { Server } from 'node:http';

import { createApp, type ChivesApp } from './app.js';
import { loadConfig, type ChivesConfig } from './config.js';

export const CHIVES_SERVER_HOST = '127.0.0.1' as const;
export const CHIVES_SERVER_PORT = 8880 as const;

export { createApp } from './app.js';
export type { CreateAppOptions, ChivesApp } from './app.js';
export { loadConfig, ConfigError } from './config.js';
export type { HarnessKind, ChivesConfig, ChivesModelRoute } from './config.js';
export { DelegationService, SessionTokenRegistry } from './delegations/index.js';
export type {
  DelegationError,
  DelegationMode,
  DelegationResult,
  DelegationStartInput,
  DelegationWaitInput,
  SessionIdentity,
} from './delegations/index.js';
export { EventBus, SseHub } from './events/index.js';
export { Orchestrator, chooseTask } from './orchestrator.js';
export { SearchService, tokenizeQuery } from './search/index.js';
export { Store } from './store/index.js';
export type { HarnessDriver } from './harness/types.js';

/**
 * Compatibility helper for callers that only need an HTTP server. Closing the
 * server also closes the store and harness processes.
 */
export function createServer(config: ChivesConfig = loadConfig()): Server {
  const app: ChivesApp = createApp({ config });
  app.server.on('close', () => {
    void app.close();
  });
  return app.server;
}
