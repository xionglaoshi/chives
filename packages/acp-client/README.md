# @chives/acp-client

Typed, runtime-zero-dependency ACP v1 client for driving a harness process over
newline-delimited JSON-RPC stdio. It is harness-agnostic: command, arguments,
environment, and cwd are supplied by the caller.

## Quick start

```ts
import { AcpClient } from '@chives/acp-client';

const client = new AcpClient({
  command: 'harness',
  args: ['--profile', 'acp'],
  cwd: '/path/to/bot-workspace',
  env: { ...process.env },
});
const caps = await client.initialize();
const { sessionId } = await client.newSession({
  cwd: '/path/to/bot-workspace',
  mcpServers: [{ name: 'data', command: '/abs/python', args: ['-m', 'data_mcp'], env: [] }],
});
client.onEvent((event) => console.log(event.type));
const { stopReason } = await client.prompt(sessionId, [{ type: 'text', text: 'hello' }]);
await client.close();
```

## Methods (`AcpClient`)

| Method | Notes |
|---|---|
| `initialize(params?)` | Records `agentCapabilities` |
| `newSession({ cwd, mcpServers })` | stdio and Streamable HTTP MCP declarations |
| `resumeSession({ sessionId, cwd, mcpServers })` | Requires `sessionCapabilities.resume` |
| `listSessions({ cwd?, cursor? })` | Requires `sessionCapabilities.list` |
| `closeSession(sessionId)` | Requires `sessionCapabilities.close` |
| `prompt(sessionId, blocks)` | Resolves `{ stopReason }` |
| `cancel(sessionId)` | JSON-RPC notification |
| `setConfigOption(sessionId, configId, value)` | Returns the full option state |
| `onEvent(handler)` / `onPermission(handler)` / `onExit(handler)` | Subscription methods |
| `close()` | Ends stdin, then SIGTERM/SIGKILL after the grace window |

Missing optional capabilities raise `AcpUnsupportedError`. Request timeouts raise
`AcpTimeoutError`; an exit rejects all pending requests with
`AcpProcessExitedError` and carries code, signal, and the stderr tail.

## Events

| `type` | Payload |
|---|---|
| `message` | `sessionId, text, messageId?` |
| `thought` | `sessionId, text, messageId?` |
| `tool_start` | `toolCallId, title, kind, rawInput` |
| `tool_end` | `toolCallId, status: completed\|failed, output, title, kind` |
| `usage` | `used, size` |
| `config` | `configOptions` |
| `unknown` | original `session/update` |

Tool updates sharing one `toolCallId` are merged into a single `tool_end` emitted
only on the first terminal update. `onPermission` receives
`{ sessionId, toolCallId, title, rawInput, options }` and returns
`'allow' | 'reject' | 'cancelled'`. `rawInput` is correlated from the earlier
`tool_start`. A throwing or timed-out handler is treated as `reject`; the default
timeout is 300 s.

## Pool (`HarnessPool`)

`acquire(key, spawnSpec?)` starts and initializes a process on demand.
`idleMs` closes idle processes; the next `acquire` reuses the persisted session
through `resumeSession`. An unexpected exit emits `crashed` and the next
`acquire` starts a fresh process. `maxProcesses` queues extra acquires.
`prompt(key, sessionId, blocks)` applies a total timeout (default 15 min): it
cancels first, waits `cancelGraceMs` (default 10 s), then restarts the process and
throws `AcpTimeoutError`.

## Verbatim streaming plugin

dsh only publishes committed messages. `plugin/chives-stream.plugin.mjs` listens
to `agent/assistant-stream` and forwards `start`, `end`, `text-delta`, and
`reasoning-delta` frames as NDJSON. With `CHIVES_STREAM_SOCKET` set it connects to
that Unix socket; otherwise it writes `@@chives-stream {...}` lines to stderr.

```ts
import { StreamChannel, DraftTracker, pluginPath, streamPatchYaml } from '@chives/acp-client';

const channel = new StreamChannel();
const socketPath = await channel.start();      // put in the child's env
const patch = streamPatchYaml(pluginPath());   // write to a .yml and pass --patch
const tracker = new DraftTracker((event) => emit(event)); // draft_reset/delta/commit
channel.onFrame((frame) => {
  client.markDraftActivity();
  tracker.handleFrame(frame);
});
client.onEvent((event) => {
  if (event.type === 'message') tracker.handleCommitted(event.sessionId, event.text);
});
```

`start` frames reset the previous uncommitted draft; retried attempts therefore
discard old text. The committed ACP `message` always wins. `client.streaming`
must be set to `true` when the plugin is mounted; `client.streamingObserved`
becomes `false` if a message arrives in a turn with no delta frames, so the UI can
fall back to whole-message rendering.

## Integration test

Unit tests use `test/fake-agent.mjs` and need no network. The real-harness test is
skipped unless enabled. It reads `DSH_FINANCE_HOME` and `DSH_FINANCE_OVERLAY` only
as paths passed to the child and never reads their contents.

```bash
CHIVES_ACP_INTEGRATION=1 \
DSH_FINANCE_HOME=/path/to/dsh/home \
DSH_FINANCE_OVERLAY=/path/to/model-overlay.cordis.yml \
pnpm --filter @chives/acp-client test:integration
```
