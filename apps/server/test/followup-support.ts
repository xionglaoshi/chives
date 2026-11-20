import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { createApp, type ChivesApp } from '../src/app.js';
import type { BotManifest } from '../src/bots/index.js';
import { FakeDriver, type FakeStep } from '../src/harness/fake.js';
import type { HarnessDriver, HarnessPromptResult, HarnessSink } from '../src/harness/types.js';
import type { TaskRecord } from '../src/store/index.js';
import { closeServer, listen, testConfig } from './support.js';

/** Per-bot scripts, as `FakeDriver` but lets a test read every prompt text. */
export class RecordingDriver implements HarnessDriver {
  readonly prompts: Array<{ botId: string; text: string }> = [];
  private readonly drivers = new Map<string, FakeDriver>();

  constructor(
    private readonly scripts: Record<string, readonly FakeStep[]>,
    private readonly workspaceDirFor?: (bot: BotManifest) => string,
  ) {}

  private forBot(bot: BotManifest): FakeDriver {
    let driver = this.drivers.get(bot.id);
    if (driver === undefined) {
      driver = new FakeDriver({
        script: this.scripts[bot.id] ?? [{ type: 'message', text: 'ok' }],
        ...(this.workspaceDirFor === undefined
          ? {}
          : { workspaceDirFor: this.workspaceDirFor }),
      });
      this.drivers.set(bot.id, driver);
    }
    return driver;
  }

  ensureSession(bot: BotManifest, task: TaskRecord): Promise<string> {
    return this.forBot(bot).ensureSession(bot, task);
  }

  prompt(
    bot: BotManifest,
    sessionId: string,
    text: string,
    sink: HarnessSink,
  ): Promise<HarnessPromptResult> {
    this.prompts.push({ botId: bot.id, text });
    return this.forBot(bot).prompt(bot, sessionId, text, sink);
  }

  cancel(bot: BotManifest, sessionId: string): void {
    this.forBot(bot).cancel(bot, sessionId);
  }

  async shutdown(): Promise<void> {
    for (const driver of this.drivers.values()) await driver.shutdown();
  }
}

export interface FollowupHarness {
  app: ChivesApp;
  baseUrl: string;
  dataDir: string;
  driver: RecordingDriver;
}

const harnesses: FollowupHarness[] = [];

export async function startFollowupApp(options: {
  dataDir?: string;
  scripts?: Record<string, readonly FakeStep[]>;
  followupMaxMs?: number;
  childTimeoutMs?: number;
  withWorkspace?: boolean;
} = {}): Promise<FollowupHarness> {
  const dataDir = options.dataDir ?? (await mkdtemp(join(tmpdir(), 'chives-followup-')));
  const config = testConfig(dataDir);
  const driver = new RecordingDriver(
    options.scripts ?? {
      expert: [{ type: 'delay', ms: 50 }, { type: 'message', text: 'expert answer' }],
      research: [{ type: 'delay', ms: 100 }, { type: 'message', text: 'dataset ready' }],
    },
    options.withWorkspace === true
      ? (bot) => join(dataDir, 'bots', bot.id, 'workspace')
      : undefined,
  );
  const app = createApp({
    config,
    driver,
    ...(options.followupMaxMs === undefined
      ? {}
      : { delegationFollowupMaxMs: options.followupMaxMs }),
    ...(options.childTimeoutMs === undefined ? {} : { delegationChildTimeoutMs: options.childTimeoutMs }),
  });
  const baseUrl = await listen(app.server);
  const harness = { app, baseUrl, dataDir, driver };
  harnesses.push(harness);
  return harness;
}

export async function stopFollowupApp(
  harness: FollowupHarness,
  remove: boolean,
  drain = true,
): Promise<void> {
  const index = harnesses.indexOf(harness);
  if (index >= 0) harnesses.splice(index, 1);
  if (drain) {
    const started = Date.now();
    while (harness.app.store.tasks.listRunning().length > 0 && Date.now() - started < 3000) {
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
  }
  harness.app.sse.closeAll();
  await closeServer(harness.app.server);
  await harness.app.close();
  if (remove) await rm(harness.dataDir, { recursive: true, force: true });
}

export async function closeFollowupHarnesses(): Promise<void> {
  for (const harness of harnesses.splice(0)) await stopFollowupApp(harness, true);
}

export function followupMessages(harness: FollowupHarness, taskId: string): string[] {
  return harness.app.store.messages
    .listByTask(taskId)
    .filter((message) => message.kind === 'proactive' && message.meta?.['followup'] === true)
    .map((message) => message.content);
}
