/** Public API for the Chives ACP client. */

export {
  AcpError,
  AcpProcessExitedError,
  AcpProtocolError,
  AcpRpcError,
  AcpTimeoutError,
  AcpUnsupportedError,
} from './errors.js';

export {
  AcpClient,
  ACP_PROTOCOL_VERSION,
  DEFAULT_PERMISSION_TIMEOUT_MS,
} from './client.js';
export type { AcpClientOptions } from './client.js';

export { AcpProcess } from './process.js';
export type { AcpExitInfo, AcpProcessOptions, AcpSpawnSpec } from './process.js';

export { EventNormalizer } from './events.js';
export type {
  AcpConfigEvent,
  AcpEvent,
  AcpMessageEvent,
  AcpThoughtEvent,
  AcpToolEndEvent,
  AcpToolStartEvent,
  AcpUnknownEvent,
  AcpUsageEvent,
  ToolCallSnapshot,
} from './events.js';

export { HarnessPool } from './pool.js';
export type { CrashedEvent, HarnessPoolOptions, PoolPromptOptions } from './pool.js';

export { DraftTracker, pluginPath, STREAM_SOCKET_ENV, StreamChannel, streamPatchYaml } from './stream/index.js';
export type {
  DraftEvent,
  DraftSnapshot,
  StreamFrame,
  StreamFrameType,
} from './stream/index.js';

export type {
  AgentCapabilities,
  AgentSessionCapabilities,
  InitializeParams,
  InitializeResult,
  ListSessionsResult,
  McpHttpServer,
  McpNameValue,
  McpServer,
  McpStdioServer,
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
  SessionConfigChoice,
  SessionConfigOption,
  SessionSummary,
  SessionUpdate,
  StopReason,
} from './types.js';
