#!/usr/bin/env node
/* Minimal stdio MCP profile server for tests. It never touches a profile file. */
/* global process */
import { appendFileSync } from 'node:fs';

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';

const logPath = process.env.FAKE_PROFILE_LOG;
if (logPath !== undefined && logPath !== '') {
  appendFileSync(logPath, `${JSON.stringify({ DSH_HOME: process.env.DSH_HOME ?? null })}\n`);
}

let fields = {};
let timestamps = {};
let updatedAt = null;

function now() {
  return new Date().toISOString();
}

function envelope(data, status = 'ready') {
  return {
    ok: true,
    source: 'profile',
    as_of: now(),
    status,
    data,
    warnings: [],
  };
}

function errorEnvelope(code, message) {
  return {
    ok: false,
    source: 'profile',
    as_of: now(),
    status: 'error',
    data: {},
    warnings: [],
    error: { code, message },
  };
}

function snapshot() {
  return {
    profile: { ...fields },
    fields: { ...fields },
    timestamps: { ...timestamps },
    field_records: Object.fromEntries(
      Object.entries(fields).map(([name, value]) => [name, { value, updated_at: timestamps[name] ?? null }]),
    ),
    updated_at: updatedAt,
    empty: Object.keys(fields).length === 0,
  };
}

const server = new Server(
  { name: 'fake-profile', version: '0.0.0' },
  { capabilities: { tools: {} } },
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    { name: 'profile_get', description: 'get', inputSchema: { type: 'object' } },
    { name: 'profile_update', description: 'update', inputSchema: { type: 'object' } },
    { name: 'profile_clear', description: 'clear', inputSchema: { type: 'object' } },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const name = request.params.name;
  const args = request.params.arguments ?? {};
  let payload;
  if (name === 'profile_get') {
    payload = envelope(snapshot(), Object.keys(fields).length === 0 ? 'empty' : 'ready');
  } else if (name === 'profile_update') {
    const next = args.fields;
    if (typeof next !== 'object' || next === null || Array.isArray(next)) {
      payload = errorEnvelope('invalid_argument', 'fields must be an object');
    } else if (next.risk_level !== undefined && !['conservative', 'balanced', 'aggressive'].includes(next.risk_level)) {
      payload = errorEnvelope('invalid_value', 'risk_level must be one of: conservative, balanced, aggressive');
    } else {
      const at = now();
      for (const [key, value] of Object.entries(next)) {
        fields[key] = value;
        timestamps[key] = at;
      }
      updatedAt = at;
      payload = envelope({
        before: {},
        after: { ...fields },
        changed: Object.keys(next),
        timestamps: { ...timestamps },
        updated_at: at,
        empty: Object.keys(fields).length === 0,
      });
    }
  } else if (name === 'profile_clear') {
    const names = args.fields;
    const at = now();
    if (Array.isArray(names)) {
      for (const key of names) {
        delete fields[key];
        delete timestamps[key];
      }
    } else {
      fields = {};
      timestamps = {};
    }
    updatedAt = at;
    payload = envelope(snapshot());
  } else {
    payload = errorEnvelope('unknown_tool', `unknown tool: ${name}`);
  }
  return { content: [{ type: 'text', text: JSON.stringify(payload) }] };
});

await server.connect(new StdioServerTransport());
