/** Latest observed state of each bot's harness process, for the settings runtime card. */

export type HarnessProcessState = 'running' | 'not_started' | 'error';

export interface HarnessProcessMonitor {
  markRunning(botId: string): void;
  markStopped(botId: string): void;
  markError(botId: string): void;
  state(botId: string): HarnessProcessState | undefined;
  anyRunning(): boolean;
}

export class ProcessMonitor implements HarnessProcessMonitor {
  private readonly states = new Map<string, HarnessProcessState>();

  markRunning(botId: string): void {
    this.states.set(botId, 'running');
  }

  markStopped(botId: string): void {
    if (this.states.get(botId) !== 'error') this.states.set(botId, 'not_started');
  }

  markError(botId: string): void {
    this.states.set(botId, 'error');
  }

  state(botId: string): HarnessProcessState | undefined {
    return this.states.get(botId);
  }

  anyRunning(): boolean {
    for (const state of this.states.values()) {
      if (state === 'running') return true;
    }
    return false;
  }
}
