/** Typed ACP client over one harness process. */

import {
  AcpProtocolError,
  AcpRpcError,
  AcpTimeoutError,
  AcpUnsupportedError,
} from './errors.js';
import { EventNormalizer, type AcpEvent, type ToolCallSnapshot } from './events.js';
import { AcpProcess, type AcpExitInfo, type AcpSpawnSpec } from './process.js';
import type {
  AgentCapabilities,
  InitializeParams,
  InitializeResult,
  ListSessionsResult,
  NewSessionParams,
  NewSessionResult,
  PermissionDecision,
  PermissionHandler,
  PermissionOption,
  PermissionRequest,
  PromptContentBlock,
  PromptResult,
  ResumeSessionParams,
  ResumeSessionResult,
  SessionConfigOption,
  SessionUpdate,
  StopReason,
} from './types.js';

export const ACP_PROTOCOL_VERSION = 1;
export const DEFAULT_PERMISSION_TIMEOUT_MS = 300_000;

const DEFAULT_REQUEST_TIMEOUT_MS = 60_000;
const DEFAULT_INITIALIZE_TIMEOUT_MS = 120_000;
const DEFAULT_CLOSE_GRACE_MS = 2000;

const DEFAULT_CLIENT_CAPABILITIES = {
  fs: { readTextFile: false, writeTextFile: false },
  terminal: false,
} as const;

export interface AcpClientOptions {
  /** Timeout for ordinary requests. Defaults to 60 seconds. */
  requestTimeoutMs?: number;
  /** Timeout for `initialize`. Defaults to 120 seconds. */
  initializeTimeoutMs?: number;
  /** Timeout for a user permission decision. Defaults to 300 seconds. */
  permissionTimeoutMs?: number;
  /** Timeout for `session/prompt`; 0 (default) leaves the pool in control. */
  promptTimeoutMs?: number;
  /** Whether the caller mounted the streaming side-channel plugin. */
  streaming?: boolean;
  /** Maximum stderr lines retained for diagnostics. Defaults to 50. */
  stderrLines?: number;
  /** Grace window used by {@link AcpClient.close}. Defaults to 2 seconds. */
  closeGraceMs?: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function asOptions(value: unknown): PermissionOption[] {
  if (!Array.isArray(value)) return [];
  const options: PermissionOption[] = [];
  for (const entry of value) {
    if (!isRecord(entry)) continue;
    if (typeof entry.optionId !== 'string' || typeof entry.name !== 'string' || typeof entry.kind !== 'string') {
      continue;
    }
    options.push({
      optionId: entry.optionId,
      name: entry.name,
      kind: entry.kind,
      ...(entry.description === undefined ? {} : { description: entry.description }),
    });
  }
  return options;
}

/**
 * One ACP connection to a harness process. All methods are typed; agent
 * capabilities returned by `initialize` gate optional ACP extensions.
 */
export class AcpClient {
  readonly process: AcpProcess;
  readonly streaming: boolean;
  private readonly requestTimeoutMs: number;
  private readonly initializeTimeoutMs: number;
  private readonly permissionTimeoutMs: number;
  private readonly promptTimeoutMs: number;
  private readonly closeGraceMs: number;
  private readonly normalizer = new EventNormalizer();
  private readonly eventListeners = new Set<(event: AcpEvent) => void>();
  private capabilities: AgentCapabilities | undefined;
  private permissionHandler: PermissionHandler | undefined;
  private observedStreaming: boolean | undefined;
  private draftSeenThisTurn = false;

  constructor(spec: AcpSpawnSpec, options: AcpClientOptions = {}) {
    this.streaming = options.streaming ?? false;
    this.requestTimeoutMs = options.requestTimeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS;
    this.initializeTimeoutMs = options.initializeTimeoutMs ?? DEFAULT_INITIALIZE_TIMEOUT_MS;
    this.permissionTimeoutMs = options.permissionTimeoutMs ?? DEFAULT_PERMISSION_TIMEOUT_MS;
    this.promptTimeoutMs = options.promptTimeoutMs ?? 0;
    this.closeGraceMs = options.closeGraceMs ?? DEFAULT_CLOSE_GRACE_MS;
    this.process = new AcpProcess(
      { ...spec, ...(options.stderrLines === undefined ? {} : { stderrLines: options.stderrLines }) },
      {
        onRequest: (method, params) => this.handleAgentRequest(method, params),
        onNotification: (method, params) => this.handleNotification(method, params),
      },
    );
  }

  get agentCapabilities(): AgentCapabilities | undefined {
    return this.capabilities;
  }

  /** `undefined` until a committed message decides it; `false` means no deltas were seen. */
  get streamingObserved(): boolean | undefined {
    return this.observedStreaming;
  }

  onEvent(listener: (event: AcpEvent) => void): () => void {
    this.eventListeners.add(listener);
    return () => {
      this.eventListeners.delete(listener);
    };
  }

  onPermission(handler: PermissionHandler | undefined): void {
    this.permissionHandler = handler;
  }

  onExit(listener: (info: AcpExitInfo) => void): () => void {
    return this.process.onExit(listener);
  }

  /** Called by the stream wiring whenever a side-channel delta frame arrives. */
  markDraftActivity(): void {
    this.draftSeenThisTurn = true;
    this.observedStreaming = true;
  }

  async initialize(params: InitializeParams = {}): Promise<InitializeResult> {
    const request: InitializeParams = {
      protocolVersion: ACP_PROTOCOL_VERSION,
      clientCapabilities: DEFAULT_CLIENT_CAPABILITIES,
      ...params,
    };
    const raw = await this.process.request('initialize', request, this.initializeTimeoutMs);
    if (!isRecord(raw) || typeof raw.protocolVersion !== 'number') {
      throw new AcpProtocolError('initialize: response is missing protocolVersion');
    }
    const result = raw as InitializeResult;
    this.capabilities = result.agentCapabilities;
    return result;
  }

  async newSession(params: NewSessionParams): Promise<NewSessionResult> {
    const raw = await this.process.request('session/new', {
      cwd: params.cwd,
      mcpServers: params.mcpServers ?? [],
    }, this.requestTimeoutMs);
    if (!isRecord(raw) || typeof raw.sessionId !== 'string') {
      throw new AcpProtocolError('session/new: response is missing sessionId');
    }
    return raw as NewSessionResult;
  }

  async resumeSession(params: ResumeSessionParams): Promise<ResumeSessionResult> {
    this.requireCapability('session/resume', 'resume');
    const raw = await this.process.request('session/resume', {
      sessionId: params.sessionId,
      cwd: params.cwd,
      mcpServers: params.mcpServers ?? [],
    }, this.requestTimeoutMs);
    if (!isRecord(raw)) throw new AcpProtocolError('session/resume: response is not an object');
    return raw as ResumeSessionResult;
  }

  async listSessions(params: { cwd?: string; cursor?: string } = {}): Promise<ListSessionsResult> {
    this.requireCapability('session/list', 'list');
    const request: Record<string, unknown> = {};
    if (params.cwd !== undefined) request.cwd = params.cwd;
    if (params.cursor !== undefined) request.cursor = params.cursor;
    const raw = await this.process.request('session/list', request, this.requestTimeoutMs);
    if (!isRecord(raw) || !Array.isArray(raw.sessions)) {
      throw new AcpProtocolError('session/list: response is missing sessions');
    }
    return raw as ListSessionsResult;
  }

  async closeSession(sessionId: string): Promise<void> {
    this.requireCapability('session/close', 'close');
    await this.process.request('session/close', { sessionId }, this.requestTimeoutMs);
  }

  async prompt(sessionId: string, blocks: readonly PromptContentBlock[]): Promise<PromptResult> {
    this.draftSeenThisTurn = false;
    const raw = await this.process.request('session/prompt', {
      sessionId,
      prompt: blocks,
    }, this.promptTimeoutMs);
    if (!isRecord(raw) || typeof raw.stopReason !== 'string') {
      throw new AcpProtocolError('session/prompt: response is missing stopReason');
    }
    return { ...raw, stopReason: raw.stopReason as StopReason };
  }

  cancel(sessionId: string): void {
    this.process.notify('session/cancel', { sessionId });
  }

  async setConfigOption(
    sessionId: string,
    configId: string,
    value: string,
  ): Promise<SessionConfigOption[]> {
    const raw = await this.process.request('session/set_config_option', {
      sessionId,
      configId,
      value,
    }, this.requestTimeoutMs);
    if (!isRecord(raw) || !Array.isArray(raw.configOptions)) {
      throw new AcpProtocolError('session/set_config_option: response is missing configOptions');
    }
    return raw.configOptions as SessionConfigOption[];
  }

  toolCall(toolCallId: string): ToolCallSnapshot | undefined {
    return this.normalizer.toolCall(toolCallId);
  }

  async close(): Promise<AcpExitInfo> {
    return this.process.close(this.closeGraceMs);
  }

  private requireCapability(method: string, capability: string): void {
    const sessionCapabilities = this.capabilities?.sessionCapabilities;
    if (!isRecord(sessionCapabilities) || sessionCapabilities[capability] === undefined) {
      throw new AcpUnsupportedError(method, `sessionCapabilities.${capability}`);
    }
  }

  private handleNotification(method: string, params: unknown): void {
    if (method !== 'session/update' || !isRecord(params)) return;
    const sessionId = params.sessionId;
    const update = params.update;
    if (typeof sessionId !== 'string' || !isRecord(update) || typeof update.sessionUpdate !== 'string') {
      return;
    }
    const event = this.normalizer.normalize(sessionId, update as SessionUpdate);
    if (event === undefined) return;
    if (event.type === 'message' && !this.draftSeenThisTurn) {
      this.observedStreaming = false;
    }
    for (const listener of [...this.eventListeners]) listener(event);
  }

  private async handleAgentRequest(method: string, params: unknown): Promise<unknown> {
    if (method === 'session/request_permission') return this.handlePermission(params);
    throw new AcpRpcError(-32601, `method not supported by this client: ${method}`);
  }

  private async handlePermission(params: unknown): Promise<unknown> {
    if (!isRecord(params) || typeof params.sessionId !== 'string' || !isRecord(params.toolCall)) {
      throw new AcpRpcError(-32602, 'session/request_permission: invalid params');
    }
    const toolCall = params.toolCall;
    if (typeof toolCall.toolCallId !== 'string') {
      throw new AcpRpcError(-32602, 'session/request_permission: missing toolCallId');
    }
    const snapshot = this.normalizer.toolCall(toolCall.toolCallId);
    const request: PermissionRequest = {
      sessionId: params.sessionId,
      toolCallId: toolCall.toolCallId,
      title: snapshot?.title
        ?? (typeof toolCall.title === 'string' ? toolCall.title : undefined),
      rawInput: snapshot?.rawInput,
      options: asOptions(params.options),
    };
    let decision: PermissionDecision = 'reject';
    const handler = this.permissionHandler;
    if (handler !== undefined) {
      try {
        decision = await this.decide(handler, request);
      } catch {
        decision = 'reject';
      }
    }
    if (decision === 'cancelled') return { outcome: { outcome: 'cancelled' } };
    const prefix = decision === 'allow' ? 'allow' : 'reject';
    const option = request.options.find((entry) => entry.kind.startsWith(prefix));
    if (option === undefined) return { outcome: { outcome: 'cancelled' } };
    return { outcome: { outcome: 'selected', optionId: option.optionId } };
  }

  private async decide(
    handler: PermissionHandler,
    request: PermissionRequest,
  ): Promise<PermissionDecision> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const timeout = new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => {
          reject(new AcpTimeoutError('session/request_permission', this.permissionTimeoutMs));
        }, this.permissionTimeoutMs);
        timer.unref();
      });
      const decision = await Promise.race([Promise.resolve(handler(request)), timeout]);
      return decision === 'allow' || decision === 'reject' || decision === 'cancelled'
        ? decision
        : 'reject';
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
  }
}
