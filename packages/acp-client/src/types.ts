/** Wire types shared by the client, event normalizer, and stream helpers. */

export type StopReason = 'end_turn' | 'max_tokens' | 'max_turn_requests' | 'refusal' | 'cancelled';

export interface McpNameValue {
  name: string;
  value: string;
}

/** Standard ACP stdio MCP declaration (no `type` field). */
export interface McpStdioServer {
  name: string;
  command: string;
  args?: string[];
  /** Required by ACP; dsh does not mount a stdio server whose declaration omits it. */
  env: McpNameValue[];
}

/** Standard ACP Streamable HTTP MCP declaration. */
export interface McpHttpServer {
  type: 'http';
  name: string;
  url: string;
  headers?: McpNameValue[];
}

export type McpServer = McpStdioServer | McpHttpServer;

export type PromptContentBlock =
  | { type: 'text'; text: string }
  | { type: 'resource_link'; uri: string; name?: string; mimeType?: string; description?: string; size?: number }
  | { type: 'image'; data: string; mimeType: string };

export interface SessionConfigChoice {
  value: string;
  name: string;
  description?: string;
}

export interface SessionConfigOption {
  id: string;
  name?: string;
  description?: string;
  category?: string;
  type?: string;
  currentValue?: string;
  options?: readonly SessionConfigChoice[];
  [key: string]: unknown;
}

export interface AgentSessionCapabilities {
  list?: Record<string, unknown>;
  resume?: Record<string, unknown>;
  close?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface AgentCapabilities {
  sessionCapabilities?: AgentSessionCapabilities;
  mcpCapabilities?: { http?: boolean; sse?: boolean; [key: string]: unknown };
  promptCapabilities?: { image?: boolean; audio?: boolean; embeddedContext?: boolean; [key: string]: unknown };
  loadSession?: boolean;
  [key: string]: unknown;
}

export interface InitializeResult {
  protocolVersion: number;
  agentCapabilities?: AgentCapabilities;
  agentInfo?: { name?: string; version?: string; [key: string]: unknown };
  authMethods?: readonly unknown[];
  [key: string]: unknown;
}

export interface NewSessionResult {
  sessionId: string;
  configOptions?: SessionConfigOption[];
  [key: string]: unknown;
}

export interface ResumeSessionResult {
  configOptions?: SessionConfigOption[];
  [key: string]: unknown;
}

export interface SessionSummary {
  sessionId: string;
  cwd?: string;
  [key: string]: unknown;
}

export interface ListSessionsResult {
  sessions: SessionSummary[];
  nextCursor?: string;
  [key: string]: unknown;
}

export interface PromptResult {
  stopReason: StopReason;
  [key: string]: unknown;
}

export interface PermissionOption {
  optionId: string;
  name: string;
  kind: string;
  [key: string]: unknown;
}

export interface PermissionRequest {
  sessionId: string;
  toolCallId: string;
  title: string | undefined;
  rawInput: unknown;
  options: readonly PermissionOption[];
}

export type PermissionDecision = 'allow' | 'reject' | 'cancelled';
export type PermissionHandler = (
  request: PermissionRequest,
) => PermissionDecision | Promise<PermissionDecision>;

/** Loose view of one `session/update` payload; unknown fields stay available. */
export interface SessionUpdate {
  sessionUpdate: string;
  [key: string]: unknown;
}

export interface InitializeParams {
  protocolVersion?: number;
  clientCapabilities?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface NewSessionParams {
  cwd: string;
  mcpServers?: readonly McpServer[];
  [key: string]: unknown;
}

export interface ResumeSessionParams {
  sessionId: string;
  cwd: string;
  mcpServers?: readonly McpServer[];
  [key: string]: unknown;
}
