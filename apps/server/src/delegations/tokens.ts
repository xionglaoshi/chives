/** In-memory harness session tokens binding each chives-mcp call to one task. */

import { randomUUID } from 'node:crypto';

export interface SessionIdentity {
  botId: string;
  taskId: string;
  /** 0 for a user task, +1 per delegation hop. */
  depth: number;
}

interface TokenEntry {
  identity: SessionIdentity;
  issuedAt: number;
}

/**
 * Tokens live in the server process only: a restart invalidates every prior
 * token, and the next `ensureSession` issues a fresh one. A task has at most
 * one live token, so reconnecting a harness session cannot leave a stale
 * credential usable.
 */
export class SessionTokenRegistry {
  private readonly tokens = new Map<string, TokenEntry>();
  private readonly byTask = new Map<string, string>();

  issue(identity: SessionIdentity): string {
    const previous = this.byTask.get(identity.taskId);
    if (previous !== undefined) this.tokens.delete(previous);
    const token = randomUUID();
    this.tokens.set(token, { identity: { ...identity }, issuedAt: Date.now() });
    this.byTask.set(identity.taskId, token);
    return token;
  }

  verify(token: string | undefined): SessionIdentity | undefined {
    if (token === undefined || token === '') return undefined;
    return this.tokens.get(token)?.identity;
  }

  /** Used by tests and by a task that reaches a terminal state. */
  revokeTask(taskId: string): void {
    const token = this.byTask.get(taskId);
    if (token !== undefined) this.tokens.delete(token);
    this.byTask.delete(taskId);
  }

  get size(): number {
    return this.tokens.size;
  }
}
