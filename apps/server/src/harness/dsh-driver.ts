/** dsh-backed harness: one long-lived ACP process per bot, sessions resume when possible. */

import { botWorkspace } from '../deliverables/files.js';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import {
  HarnessPool,
  type AcpClient,
  type AcpEvent,
  type AcpSpawnSpec,
  type CrashedEvent,
  type DraftEvent,
  type McpServer,
  type PermissionDecision,
  type PermissionRequest,
  type SessionConfigOption,
} from '@chives/acp-client';

import { botHasWatches, type BotManifest } from '../bots/index.js';
import type { TaskRecord } from '../store/index.js';
import {
  buildMcpServers,
  dshSpawnSpec,
  type DshModelRoute,
  type DshModelRuntime,
  type DshSpawnOptions,
} from './dsh.js';
import type { HarnessProcessMonitor } from './process-monitor.js';
import type {
  HarnessDriver,
  HarnessEvent,
  HarnessPromptResult,
  HarnessSink,
  HiddenPromptDriver,
  TemporaryPromptDriver,
  TemporaryPromptOptions,
} from './types.js';


/**
 * MCP env expressions such as `process.env.DSH_HOME || HOME/.dsh` must resolve to the
 * same home the dsh child gets, or the holdings book and profile land in `~/.dsh` while
 * dsh and the sidebar read Chives's home.
 */
export function mcpEnvironment(
  env: Readonly<Record<string, string | undefined>>,
  dshHome: string,
): Record<string, string | undefined> {
  return { ...env, DSH_HOME: dshHome };
}

export interface DshDriverOptions {
  dataDir: string;
  dshHome: string;
  /** Path passed as `--patch`; never opened by the server. */
  modelOverlay: string;
  /** Read at every spawn: the settings-page model endpoint, which replaces `modelOverlay` when set. */
  modelRuntime?: (bot: BotManifest) => DshModelRuntime | undefined;
  repoRoot?: string;
  effectiveBot?: (bot: BotManifest) => BotManifest;
  extraServers?: (bot: BotManifest, api: string, token: string) => McpServer[];
  workspaceWrite?: () => boolean;
  attachmentsRead?: () => boolean;
  env?: Readonly<Record<string, string | undefined>>;
  /** Route-name map forwarded to `buildDshPatch`, e.g. `{ default: ... }`. */
  routes?: Readonly<Record<string, DshModelRoute>>;
  /** Chives Server base URL injected into the built-in `chives` MCP server. */
  chivesApi?: string;
  /** Issues a fresh session token whenever a harness session is established. */
  sessionCredentialFor?: (bot: BotManifest, task: TaskRecord) => string;
  maxProcesses?: number;
  idleMs?: number;
  streaming?: boolean;
  /** Server-side approval timeout; the ACP client waits longer so the server decides first. */
  approvalTimeoutMs?: number;
  /** Replaces `paper_broker`'s `--state-dir` in the ACP MCP declaration. */
  paperStateDir?: string;
  /** Returns shared rules plus this bot's persona for the generated patch. */
  personaTextFor: (bot: BotManifest) => string;
  /** Test seam: bypasses `dshSpawnSpec` (e.g. to point at the fake ACP agent). */
  spawnSpecFor?: (bot: BotManifest) => AcpSpawnSpec;
  /** Receives the `configOptions` of every newly created session. */
  onConfigOptions?: (bot: BotManifest, options: readonly SessionConfigOption[]) => void;
  /** Fires when a new or resumed task session is usable. */
  onSessionEstablished?: (bot: BotManifest) => void;
  /** Model applied after `session/new` for bots whose manifest model is `default`. */
  defaultModel?: () => string | null;
  /** Process state observed by the settings runtime card. */
  processMonitor?: HarnessProcessMonitor;
  onNotice?: (bot: BotManifest, task: TaskRecord, text: string) => void;
  /** Runs until a user decision, timeout, or task cancellation. */
  onPermission?: (
    bot: BotManifest,
    request: PermissionRequest,
    task: TaskRecord,
  ) => PermissionDecision | Promise<PermissionDecision>;
  onCrash?: (bot: BotManifest, event: CrashedEvent) => void;
}

function eventFromDraft(event: DraftEvent): HarnessEvent {
  if (event.type === 'draft_reset') {
    return event.attemptId === undefined
      ? { type: 'draft_reset' }
      : { type: 'draft_reset', attemptId: event.attemptId };
  }
  if (event.type === 'draft_delta') {
    return {
      type: 'draft_delta',
      kind: event.kind,
      text: event.text,
      ...(event.attemptId === undefined ? {} : { attemptId: event.attemptId }),
    };
  }
  return { type: 'draft_commit', text: event.text };
}

function eventFromAcp(event: AcpEvent): HarnessEvent | undefined {
  switch (event.type) {
    case 'message':
      return { type: 'message', text: event.text };
    case 'thought':
      return { type: 'thought', text: event.text };
    case 'tool_start':
      return {
        type: 'tool_start',
        toolCallId: event.toolCallId,
        title: event.title,
        kind: event.kind,
        rawInput: event.rawInput,
      };
    case 'tool_end':
      return {
        type: 'tool_end',
        toolCallId: event.toolCallId,
        status: event.status,
        output: event.output,
        title: event.title,
        kind: event.kind,
      };
    case 'usage':
      return { type: 'usage', used: event.used, size: event.size };
    default:
      return undefined;
  }
}

/**
 * Drives `dsh --profile acp` through {@link HarnessPool}. A failed
 * `session/resume` falls back to a fresh session and reports a notice; a
 * crashed process is reported to the orchestrator while the pool restarts on
 * the next acquire.
 */
export class DshDriver implements HarnessDriver, TemporaryPromptDriver, HiddenPromptDriver {
  private pool: HarnessPool | undefined;
  private readonly sinks = new Map<string, HarnessSink>();
  /** Sessions already loaded in each harness process; a restarted process gets a new client and starts empty. */
  private readonly liveSessions = new WeakMap<AcpClient, Set<string>>();
  private readonly selections = new WeakMap<AcpSpawnSpec,DshModelRuntime>();
  private readonly spawnSpecs = new Map<string, AcpSpawnSpec>();
  private readonly bots = new Map<string, BotManifest>();
  /** Which task owns each ACP session, so a permission request can be routed. */
  private readonly sessionTasks = new Map<string, TaskRecord>();
  private readonly configured = new WeakSet<AcpClient>();
  private readonly exitWatched = new WeakSet<AcpClient>();
  /** Sessions running a hidden prompt: permissions are rejected and drafts swallowed. */
  private readonly hiddenSessions = new Set<string>();
  /** Prompts in flight per bot, so a model reload never kills a running turn. */
  private readonly busy = new Map<string, number>();
  /** Bots whose process must restart once idle to pick up a new model config. */
  private readonly stale = new Set<string>();

  constructor(private readonly options: DshDriverOptions) {}

  private getPool(spawnSpec: AcpSpawnSpec): HarnessPool {
    if (this.pool === undefined) {
      this.pool = new HarnessPool({
        spawnSpec,
        ...(this.options.maxProcesses === undefined ? {} : { maxProcesses: this.options.maxProcesses }),
        ...(this.options.idleMs === undefined ? {} : { idleMs: this.options.idleMs }),
        streaming: this.options.streaming ?? true,
        clientOptions: {
          // The server timeout must win; the client timeout is only a backstop.
          permissionTimeoutMs: (this.options.approvalTimeoutMs ?? 10 * 60_000) + 60_000,
        },
        onDraft: (event) => {
          this.handleDraft(event);
        },
      });
      this.pool.onCrashed((event) => {
        try {
          this.options.processMonitor?.markError(event.key);
          const bot = this.bots.get(event.key);
          if (bot !== undefined) this.options.onCrash?.(bot, event);
        } catch {
          // Crash reporting must never break pool bookkeeping.
        }
      });
    }
    return this.pool;
  }

  private spawnSpec(bot: BotManifest): AcpSpawnSpec {
    bot = this.options.effectiveBot?.(bot) ?? bot;
    const injected = this.options.spawnSpecFor;
    if (injected !== undefined) return injected(bot);
    const spawnOptions: DshSpawnOptions = {
      personaText: this.options.personaTextFor(bot),
      dataDir: this.options.dataDir,
      dshHome: this.options.dshHome,
      modelOverlay: this.options.modelOverlay,
      ...(this.options.repoRoot === undefined ? {} : { repoRoot: this.options.repoRoot }),
      ...(this.options.env === undefined ? {} : { env: this.options.env }),
      ...(this.options.routes === undefined ? {} : { routes: this.options.routes }),
    };
    if (this.options.attachmentsRead) spawnOptions.attachmentsRead=this.options.attachmentsRead();
    if (this.options.workspaceWrite) spawnOptions.workspaceWrite = this.options.workspaceWrite();
    const runtime = this.options.modelRuntime?.(bot);
    if (runtime !== undefined) {spawnOptions.modelRuntime = runtime; spawnOptions.model = runtime.route;}
    const spec=dshSpawnSpec(bot, spawnOptions);
    if(runtime)this.selections.set(spec,runtime);
    return spec;
  }

  private mcpServers(bot: BotManifest, task: TaskRecord): McpServer[] {
    bot = this.options.effectiveBot?.(bot) ?? bot;
    const issued = this.options.sessionCredentialFor?.(bot, task);
    const chives = {
      api: this.options.chivesApi ?? 'http://127.0.0.1:8880',
      ...(issued === undefined ? {} : { token: issued }),
      features: [...(botHasWatches(bot) ? ['watches'] : []), ...(bot.id==='ceo'?['coordinator']:[]), ...(bot.can_delegate_to.length?[]:['no-delegates'])],
    };
    const servers = buildMcpServers(
      bot,
      mcpEnvironment(this.options.env ?? process.env, this.options.dshHome),
      this.options.repoRoot,
      chives,
      this.options.paperStateDir === undefined
        ? { strategies: bot.strategies ?? [] }
        : { paperStateDir: this.options.paperStateDir, strategies: bot.strategies ?? [] },
    );
    const extra = this.options.extraServers?.(bot,chives.api,issued ?? '') ?? [];
    const bridge = extra.find(server => server.name === 'bot_assets');
    if (bot.id !== 'ceo' || !bridge || !('env' in bridge)) return servers.concat(extra);
    // Research providers are independent and stateless. Discover them on demand so an
    // offline feed cannot prevent a conversation. The broker retains its native approval path.
    const research = new Set(['cn_market','cn_data','cn_extra','cn_research','tavily','scrape','strategy']);
    const deferred = servers.filter(server => research.has(server.name));
    bridge.env.push({name:'CHIVES_RESEARCH_SERVERS',value:JSON.stringify(deferred)});
    return servers.filter(server => !research.has(server.name)).concat(extra);
  }

  private workspace(bot: BotManifest): string {
    const cwd = botWorkspace(this.options.dataDir, bot.id);
    mkdirSync(cwd, { recursive: true });
    return cwd;
  }

  private configure(bot: BotManifest, client: AcpClient): void {
    if (this.configured.has(client)) return;
    this.configured.add(client);
    if (!this.exitWatched.has(client)) {
      this.exitWatched.add(client);
      client.onExit(() => {
        this.options.processMonitor?.markStopped(bot.id);
      });
    }
    client.onPermission(async (request) => {
      if (this.hiddenSessions.has(request.sessionId)) return 'reject' as const;
      const task = this.sessionTasks.get(request.sessionId);
      if (task === undefined) return 'reject' as const;
      try {
        const decision = await this.options.onPermission?.(bot, request, task);
        return decision === 'allow' || decision === 'reject' || decision === 'cancelled'
          ? decision
          : 'reject';
      } catch {
        return 'reject' as const;
      }
    });
    client.onEvent((event) => {
      const sink = this.sinks.get(event.sessionId);
      if (sink === undefined) return;
      const normalized = eventFromAcp(event);
      if (normalized === undefined) return;
      try {
        sink(normalized);
      } catch {
        // Isolate consumer failures from the ACP connection.
      }
    });
  }

  private handleDraft(event: DraftEvent): void {
    const sink = this.sinks.get(event.sessionId);
    if (sink === undefined) return;
    try {
      sink(eventFromDraft(event));
    } catch {
      // Isolate consumer failures from the side-channel.
    }
  }

  private async applySelection(client:AcpClient, sessionId:string, options:readonly SessionConfigOption[], spec:AcpSpawnSpec) {
    const selected=this.selections.get(spec);
    if(!selected)return options;
    const route=JSON.stringify([selected.route.provider,selected.route.model]);
    const enforce=async(id:string,value:string)=>{
      if(options.find(option=>option.id===id)?.currentValue!==value) {
        options=await client.setConfigOption(sessionId,id,value);
        if(options.find(option=>option.id===id)?.currentValue!==value)
          throw Error('dsh 未采用新的模型设置，请检查连接后重试');
      }
    };
    await enforce('model',route);
    if(selected.reasoningEffort || options.some(option=>option.id==='reasoning_effort'))
      await enforce('reasoning_effort',selected.reasoningEffort??'');
    return options;
  }

  async ensureSession(
    bot: BotManifest,
    task: TaskRecord,
    options: { silent?: boolean; onLiveSession?: () => void } = {},
  ): Promise<string> {
    this.bots.set(bot.id, bot);
    const spec = this.spawnSpec(bot);
    this.spawnSpecs.set(bot.id, spec);
    const pool = this.getPool(spec);
    const client = await pool.acquire(bot.id, spec);
    this.configure(bot, client);
    this.options.processMonitor?.markRunning(bot.id);

    const cwd = this.workspace(bot);
    let live = this.liveSessions.get(client);
    if (live === undefined) {
      live = new Set();
      this.liveSessions.set(client, live);
    }
    if (task.harnessSessionId !== null && live.has(task.harnessSessionId)) {
      // Already loaded in this process: dsh rejects a second resume of a live session.
      // Reuse the token the MCP child was started with; issuing here would revoke it.
      this.sessionTasks.set(task.harnessSessionId, task);
      options.onLiveSession?.();
      return task.harnessSessionId;
    }
    // Only a session that is actually established needs a fresh token.
    const mcpServers = this.mcpServers(bot, task);
    if (task.harnessSessionId !== null) {
      const id=task.harnessSessionId;
      const resumed=await client.resumeSession({sessionId:id,cwd,mcpServers}).catch(()=>null);
      if(resumed){
        const config=await this.applySelection(client,id,resumed.configOptions??[],spec);
        live.add(id);
        this.sessionTasks.set(id,task);
        this.options.onSessionEstablished?.(bot);
        try { this.options.onConfigOptions?.(bot,config); } catch { /* Reporting is best-effort. */ }
        return id;
      }
      if(!options.silent)this.options.onNotice?.(bot,task,'上一轮的 harness 会话无法恢复，已为这一轮新建会话。');
    }
    const created = await client.newSession({ cwd, mcpServers });
    const configOptions=await this.applySelection(client,created.sessionId,created.configOptions??[],spec);
    live.add(created.sessionId);
    this.sessionTasks.set(created.sessionId, task);
    this.options.onSessionEstablished?.(bot);
    try {
      this.options.onConfigOptions?.(bot, configOptions);
    } catch {
      // Reporting config options must not break the session.
    }
    if (bot.model === 'default' && !this.selections.has(spec)) {
      let model: string | null;
      try {
        model = this.options.defaultModel?.() ?? null;
      } catch {
        model = null;
      }
      if (model !== null && model !== '') {
        try {
          await client.setConfigOption(created.sessionId, 'model', model);
        } catch {
          try {
            this.options.onNotice?.(
              bot,
              task,
              '默认模型未能应用到新会话，已使用 harness 的默认模型。',
            );
          } catch {
            // Notice delivery is best-effort.
          }
        }
      }
    }
    return created.sessionId;
  }

  async prompt(
    bot: BotManifest,
    sessionId: string,
    text: string,
    sink: HarnessSink,
  ): Promise<HarnessPromptResult> {
    const spec = this.spawnSpecs.get(bot.id) ?? this.spawnSpec(bot);
    const pool = this.getPool(spec);
    const client = await pool.acquire(bot.id, spec);
    this.configure(bot, client);
    this.sinks.set(sessionId, sink);
    try {
      const result = await this.tracked(bot.id, () =>
        pool.prompt(bot.id, sessionId, [{ type: 'text', text }]),
      );
      return { stopReason: result.stopReason };
    } finally {
      this.sinks.delete(sessionId);
    }
  }

  /**
   * A throwaway session in this bot's process, without MCP, used by the task
   * classifier. Nothing it emits reaches the timeline; the session is closed
   * afterwards.
   */
  async temporaryPrompt(
    bot: BotManifest,
    text: string,
    options: TemporaryPromptOptions = {},
  ): Promise<string | null> {
    const spec = this.spawnSpec(bot);
    this.spawnSpecs.set(bot.id, spec);
    const pool = this.getPool(spec);
    const client = await pool.acquire(bot.id, spec);
    this.configure(bot, client);
    const created = await client.newSession({ cwd: this.workspace(bot), mcpServers: [] });
    const sessionId = created.sessionId;
    const parts: string[] = [];
    try {
      await this.applySelection(client,sessionId,created.configOptions??[],spec);
      for (const [configId, value] of Object.entries(options.config ?? {})) {
        try {
          await client.setConfigOption(sessionId, configId, value);
        } catch {
          // Older harnesses may not expose this config; the prompt still works.
        }
      }
      this.sinks.set(sessionId, (event) => {
        if (event.type === 'message') parts.push(event.text);
      });
      const run = this.tracked(bot.id, () =>
        pool.prompt(bot.id, sessionId, [{ type: 'text', text }]),
      ).then(() => true, () => false);
      const completed = await this.raceTimeout(run, options.timeoutMs ?? 15_000);
      if (completed === null) {
        try {
          client.cancel(sessionId);
        } catch {
          // Timeout fallback happens in the caller either way.
        }
        return null;
      }
      return parts.join('');
    } finally {
      this.sinks.delete(sessionId);
      try {
        await client.closeSession(sessionId);
      } catch {
        // Closing a throwaway session is best-effort.
      }
    }
  }

  /**
   * Appends a hidden prompt to an existing task session. Drafts and tool
   * events are swallowed; permission requests are rejected without creating an
   * approval card.
   */
  async hiddenPrompt(
    bot: BotManifest,
    task: TaskRecord,
    text: string,
    timeoutMs: number,
  ): Promise<string | null> {
    const sessionId = await this.ensureSession(bot, task, { silent: true });
    const spec = this.spawnSpecs.get(bot.id) ?? this.spawnSpec(bot);
    const pool = this.getPool(spec);
    const parts: string[] = [];
    this.hiddenSessions.add(sessionId);
    this.sinks.set(sessionId, (event) => {
      if (event.type === 'message') parts.push(event.text);
    });
    try {
      const run = this.tracked(bot.id, () =>
        pool.prompt(bot.id, sessionId, [{ type: 'text', text }]),
      ).then(() => true, () => false);
      const completed = await this.raceTimeout(run, timeoutMs);
      if (completed === null) {
        try {
          pool.cancel(bot.id, sessionId);
        } catch {
          // The caller still falls back to a deterministic summary.
        }
        return null;
      }
      return parts.join('');
    } finally {
      this.sinks.delete(sessionId);
      this.hiddenSessions.delete(sessionId);
    }
  }

  private raceTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T | null> {
    return new Promise((resolve) => {
      let settled = false;
      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        resolve(null);
      }, timeoutMs);
      timer.unref();
      promise.then(
        (value) => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          resolve(value);
        },
        () => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          resolve(null);
        },
      );
    });
  }

  cancel(bot: BotManifest, sessionId: string): void {
    this.pool?.cancel(bot.id, sessionId);
  }

  /**
   * Restarts bot processes so the next turn uses the current model config. Idle processes close now;
   * a process with a prompt in flight closes when that prompt ends. Sessions resume from disk.
   */
  async reloadModel(id?: string): Promise<void> {
    if (id) this.spawnSpecs.delete(id);
    else this.spawnSpecs.clear();
    const idle: string[] = [];
    for (const botId of this.bots.keys()) {
      if (id && botId !== id) continue;
      if ((this.busy.get(botId) ?? 0) > 0) this.stale.add(botId);
      else idle.push(botId);
    }
    await Promise.all(idle.map((botId) => this.restart(botId)));
  }

  private async tracked<T>(botId: string, run: () => Promise<T>): Promise<T> {
    this.busy.set(botId, (this.busy.get(botId) ?? 0) + 1);
    try {
      return await run();
    } finally {
      const left = (this.busy.get(botId) ?? 1) - 1;
      if (left > 0) this.busy.set(botId, left);
      else {
        this.busy.delete(botId);
        if (this.stale.delete(botId)) void this.restart(botId);
      }
    }
  }

  private async restart(botId: string): Promise<void> {
    if (this.pool === undefined) return;
    try {
      await this.pool.release(botId);
      this.options.processMonitor?.markStopped(botId);
    } catch {
      // A failed close leaves the old process; the idle timer still retires it.
    }
  }

  async shutdown(): Promise<void> {
    this.sinks.clear();
    this.sessionTasks.clear();
    for (const botId of this.bots.keys()) this.options.processMonitor?.markStopped(botId);
    await this.pool?.stopAll();
  }
}
