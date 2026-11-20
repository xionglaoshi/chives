#!/usr/bin/env node
/**
 * Minimal fake ACP agent for tests. It speaks newline-delimited JSON-RPC on
 * stdio. FAKE_AGENT_SCENARIO selects the behaviour; FAKE_AGENT_LOG appends every
 * received message so tests can assert exact request shapes.
 */
/* global process, setTimeout, clearTimeout */
import { appendFileSync } from 'node:fs';
import net from 'node:net';
import { createInterface } from 'node:readline';

const scenario = process.env.FAKE_AGENT_SCENARIO ?? 'normal';
const logPath = process.env.FAKE_AGENT_LOG;

const sessions = new Map();
const activePrompts = new Map();
const agentPending = new Map();
let nextSession = 1;
let nextAgentRequest = 1;

function log(message) {
  if (logPath === undefined || logPath === '') return;
  try {
    appendFileSync(logPath, `${JSON.stringify(message)}\n`);
  } catch {
    // tests fail on their own if the log cannot be read
  }
}

function send(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

function respond(id, result) {
  send({ jsonrpc: '2.0', id, result });
}

function respondError(id, code, message) {
  send({ jsonrpc: '2.0', id, error: { code, message } });
}

function notify(method, params) {
  send({ jsonrpc: '2.0', method, params });
}

function update(sessionId, value) {
  notify('session/update', { sessionId, update: value });
}

function message(sessionId, text) {
  update(sessionId, { sessionUpdate: 'agent_message_chunk', messageId: `m-${sessionId}`, content: { type: 'text', text } });
}

function thought(sessionId, text) {
  update(sessionId, { sessionUpdate: 'agent_thought_chunk', messageId: `t-${sessionId}`, content: { type: 'text', text } });
}

function configOptions(session) {
  const model = session?.configs?.model ?? 'fake-model';
  const effort = session?.configs?.reasoning_effort ?? 'low';
  return [
    {
      id: 'model',
      name: 'Model',
      type: 'select',
      currentValue: model,
      options: [{ value: 'fake-model', name: 'Fake model' }],
    },
    {
      id: 'reasoning_effort',
      name: 'Reasoning effort',
      type: 'select',
      currentValue: effort,
      options: [{ value: 'low', name: 'Low' }, { value: 'high', name: 'High' }],
    },
  ];
}

function createSession(cwd) {
  const sessionId = `sess-${nextSession++}`;
  sessions.set(sessionId, { sessionId, cwd, configs: { model: 'fake-model', reasoning_effort: 'low' } });
  return sessions.get(sessionId);
}

function promptText(prompt) {
  if (!Array.isArray(prompt)) return '';
  return prompt
    .filter((block) => block?.type === 'text' && typeof block.text === 'string')
    .map((block) => block.text)
    .join('');
}

function requestClient(method, params) {
  const id = nextAgentRequest++;
  return new Promise((resolve) => {
    agentPending.set(id, resolve);
    send({ jsonrpc: '2.0', id, method, params });
  });
}

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function connectStream() {
  const socketPath = process.env.CHIVES_STREAM_SOCKET;
  if (socketPath === undefined || socketPath === '') return null;
  return new Promise((resolve) => {
    const socket = net.createConnection({ path: socketPath });
    const timer = setTimeout(() => {
      socket.destroy();
      resolve(null);
    }, 1000);
    timer.unref();
    socket.on('connect', () => {
      clearTimeout(timer);
      resolve(socket);
    });
    socket.on('error', () => {
      clearTimeout(timer);
      resolve(null);
    });
  });
}

async function streamFlow(sessionId) {
  const socket = await connectStream();
  if (socket === null) return;
  const frame = (value) => {
    try {
      socket.write(`${JSON.stringify(value)}\n`);
    } catch {
      // the client may have gone away; the committed message still follows
    }
  };
  frame({ session: sessionId, t: 'start', attemptId: 'attempt-1' });
  frame({ session: sessionId, t: 'text-delta', attemptId: 'attempt-1', i: 0, text: 'OLD ' });
  frame({ session: sessionId, t: 'text-delta', attemptId: 'attempt-1', i: 1, text: 'DRAFT' });
  frame({ session: sessionId, t: 'end', attemptId: 'attempt-1', outcome: { kind: 'abandoned' } });
  frame({ session: sessionId, t: 'start', attemptId: 'attempt-2' });
  frame({ session: sessionId, t: 'reasoning-delta', attemptId: 'attempt-2', i: 0, text: 'thinking' });
  frame({ session: sessionId, t: 'text-delta', attemptId: 'attempt-2', i: 1, text: 'NEW ' });
  frame({ session: sessionId, t: 'text-delta', attemptId: 'attempt-2', i: 2, text: 'TEXT' });
  frame({ session: sessionId, t: 'end', attemptId: 'attempt-2', outcome: { kind: 'committed' } });
  await sleep(30);
  socket.end();
}

async function permissionFlow(sessionId, promptId) {
  update(sessionId, {
    sessionUpdate: 'tool_call',
    toolCallId: 'tool-p',
    title: 'paper_place_order',
    kind: 'other',
    status: 'in_progress',
    rawInput: { symbol: '600519.SH', quantity: 100 },
  });
  const response = await requestClient('session/request_permission', {
    sessionId,
    toolCall: { toolCallId: 'tool-p' },
    options: [
      { optionId: 'allow-once', name: 'Allow once', kind: 'allow_once' },
      { optionId: 'reject-once', name: 'Reject', kind: 'reject_once' },
    ],
  });
  const outcome = response?.result?.outcome;
  const optionId = outcome?.outcome === 'selected' ? outcome.optionId : null;
  const status = optionId === 'allow-once' ? 'completed' : 'failed';
  update(sessionId, {
    sessionUpdate: 'tool_call_update',
    toolCallId: 'tool-p',
    status,
    content: [{ type: 'content', content: { type: 'text', text: `permission:${optionId ?? 'cancelled'}` } }],
  });
  message(sessionId, `permission:${optionId ?? 'cancelled'}`);
  respond(promptId, { stopReason: 'end_turn' });
}

async function toolsFlow(sessionId, promptId) {
  update(sessionId, {
    sessionUpdate: 'tool_call',
    toolCallId: 'tool-1',
    title: 'Bash',
    kind: 'other',
    status: 'in_progress',
    rawInput: { command: 'echo hi' },
  });
  await sleep(10);
  update(sessionId, { sessionUpdate: 'tool_call_update', toolCallId: 'tool-1', status: 'in_progress' });
  await sleep(10);
  update(sessionId, {
    sessionUpdate: 'tool_call_update',
    toolCallId: 'tool-1',
    status: 'completed',
    content: [{ type: 'content', content: { type: 'text', text: 'hi\n' } }],
  });
  message(sessionId, 'tool done');
  respond(promptId, { stopReason: 'end_turn' });
}

async function unknownRequestFlow(sessionId, promptId) {
  const response = await requestClient('fs/read_text_file', { path: '/tmp/x' });
  message(sessionId, `error:${String(response?.error?.code)}`);
  respond(promptId, { stopReason: 'end_turn' });
}

async function handlePrompt(id, params) {
  const sessionId = params.sessionId;
  const text = promptText(params.prompt);
  if (!sessions.has(sessionId)) createSession(params.cwd ?? '/tmp');
  log({ method: 'session/prompt', sessionId, prompt: params.prompt });
  switch (scenario) {
    case 'crash':
      process.stderr.write('fake-agent: crashing\n');
      setTimeout(() => process.exit(1), 10);
      return;
    case 'silent':
      activePrompts.set(sessionId, { id });
      return;
    case 'cancel':
      activePrompts.set(sessionId, { id });
      return;
    case 'permission':
      await permissionFlow(sessionId, id);
      return;
    case 'tools':
      await toolsFlow(sessionId, id);
      return;
    case 'unknown-request':
      await unknownRequestFlow(sessionId, id);
      return;
    case 'stream':
      await streamFlow(sessionId);
      thought(sessionId, 'retry committed');
      message(sessionId, 'NEW TEXT');
      respond(id, { stopReason: 'end_turn' });
      return;
    case 'slow':
      await sleep(200);
      message(sessionId, `reply:${text}`);
      respond(id, { stopReason: 'end_turn' });
      return;
    default:
      thought(sessionId, 'thinking');
      message(sessionId, `reply:${text}`);
      respond(id, { stopReason: 'end_turn' });
      return;
  }
}

function handleCancel(params) {
  const sessionId = params.sessionId;
  log({ method: 'session/cancel', sessionId });
  if (scenario === 'silent') return;
  const pending = activePrompts.get(sessionId);
  if (pending === undefined) return;
  activePrompts.delete(sessionId);
  respond(pending.id, { stopReason: 'cancelled' });
}

function handleInitialize(id) {
  const capabilities = scenario === 'minimal'
    ? {}
    : {
      sessionCapabilities: { close: {}, list: {}, resume: {} },
      mcpCapabilities: { http: true },
      promptCapabilities: { image: false, audio: false, embeddedContext: false },
    };
  respond(id, {
    protocolVersion: 1,
    agentInfo: { name: 'fake-agent', version: '0.0.0' },
    authMethods: [],
    agentCapabilities: capabilities,
  });
}

function handleNewSession(id, params) {
  if (typeof params.cwd !== 'string' || !params.cwd.startsWith('/')) {
    respondError(id, -32602, 'cwd must be absolute');
    return;
  }
  const session = createSession(params.cwd);
  respond(id, { sessionId: session.sessionId, configOptions: configOptions(session) });
}

function handleResume(id, params) {
  if (scenario === 'resume-fail') {
    respondError(id, -32602, 'session is not resumable');
    return;
  }
  const session = sessions.get(params.sessionId);
  if (session === undefined) {
    respondError(id, -32602, `session is not resumable: ${params.sessionId}`);
    return;
  }
  respond(id, { configOptions: configOptions(session) });
}

function handleList(id, params) {
  const all = [...sessions.values()]
    .filter((session) => params.cwd === undefined || session.cwd === params.cwd)
    .map((session) => ({ sessionId: session.sessionId, cwd: session.cwd }));
  respond(id, { sessions: all });
}

function handleSetConfig(id, params) {
  const session = sessions.get(params.sessionId);
  if (session === undefined) {
    respondError(id, -32602, 'unknown session');
    return;
  }
  if (params.configId !== 'model' && params.configId !== 'reasoning_effort') {
    respondError(id, -32602, `unknown configId: ${String(params.configId)}`);
    return;
  }
  if (typeof params.value !== 'string') {
    respondError(id, -32602, 'value must be a string');
    return;
  }
  session.configs[params.configId] = params.value;
  respond(id, { configOptions: configOptions(session) });
}

const methods = {
  initialize: (id) => handleInitialize(id),
  'session/new': (id, params) => handleNewSession(id, params),
  'session/resume': (id, params) => handleResume(id, params),
  'session/list': (id, params) => handleList(id, params),
  'session/close': (id) => respond(id, {}),
  'session/set_config_option': (id, params) => handleSetConfig(id, params),
  'session/prompt': (id, params) => {
    void handlePrompt(id, params).catch((error) => {
      respondError(id, -32603, String(error));
    });
  },
};

const reader = createInterface({ input: process.stdin });
reader.on('line', (line) => {
  if (line.trim().length === 0) return;
  let incoming;
  try {
    incoming = JSON.parse(line);
  } catch {
    return;
  }
  log(incoming);
  if (typeof incoming.method === 'string' && incoming.id === undefined) {
    if (incoming.method === 'session/cancel') handleCancel(incoming.params ?? {});
    return;
  }
  if (typeof incoming.method === 'string') {
    const handler = methods[incoming.method];
    if (handler === undefined) {
      respondError(incoming.id, -32601, `method not found: ${incoming.method}`);
      return;
    }
    handler(incoming.id, incoming.params ?? {});
    return;
  }
  if (incoming.id !== undefined) {
    const resolve = agentPending.get(incoming.id);
    if (resolve !== undefined) {
      agentPending.delete(incoming.id);
      resolve(incoming);
    }
  }
});
reader.on('close', () => process.exit(0));
