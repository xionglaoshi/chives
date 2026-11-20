import { describe, expect, it } from 'vitest';

import {
  ACP_PROTOCOL_VERSION,
  AcpClient,
  AcpProcess,
  DraftTracker,
  HarnessPool,
  StreamChannel,
  pluginPath,
  streamPatchYaml,
} from '../src/index.js';

describe('public API', () => {
  it('exports the protocol version and the client building blocks', () => {
    expect(ACP_PROTOCOL_VERSION).toBe(1);
    expect(typeof AcpClient).toBe('function');
    expect(typeof AcpProcess).toBe('function');
    expect(typeof HarnessPool).toBe('function');
    expect(typeof StreamChannel).toBe('function');
    expect(typeof DraftTracker).toBe('function');
    expect(pluginPath()).toContain('chives-stream.plugin.mjs');
    expect(streamPatchYaml('/tmp/x')).toContain('chives-stream');
  });
});
