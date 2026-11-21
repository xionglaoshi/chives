import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { ConfigError, DEFAULT_PORT, loadConfig } from '../src/config.js';

describe('loadConfig', () => {
  it('uses local-only defaults', () => {
    const config = loadConfig({});
    expect(config.port).toBe(DEFAULT_PORT);
    expect(config.harness).toBe('dsh');
    expect(config.maxProcesses).toBe(5);
    expect(config.idleMs).toBe(600_000);
    expect(config.approvalTimeoutMs).toBe(600_000);
    expect(config.paperStateDir).toBeUndefined();
    expect(config.dataDir).toBe(join(config.repoRoot, 'data'));
    expect(loadConfig({ CHIVES_DATA_DIR: '  ' }).dataDir).toBe(config.dataDir);
    expect(config.gatewayUrl).toBe('http://127.0.0.1:8868');
  });

  it('reads fake mode, data dir, port, and route', () => {
    const config = loadConfig({
      CHIVES_HARNESS: 'fake',
      CHIVES_DATA_DIR: '/tmp/chives-test-data',
      CHIVES_PORT: '8790',
      CHIVES_DEFAULT_ROUTE: 'provider/model-x',
      CHIVES_MAX_PROCESSES: '2',
      CHIVES_IDLE_MS: '1000',
      CHIVES_APPROVAL_TIMEOUT_MS: '1234',
      CHIVES_PAPER_STATE_DIR: '/tmp/paper-state',
      DSH_FINANCE_HOME: '/tmp/dsh-home',
      DSH_FINANCE_OVERLAY: '/tmp/overlay.yml',
    });
    expect(config.harness).toBe('fake');
    expect(config.dataDir).toBe('/tmp/chives-test-data');
    expect(config.port).toBe(8790);
    expect(config.defaultRoute).toEqual({ provider: 'provider', model: 'model-x' });
    expect(config.maxProcesses).toBe(2);
    expect(config.idleMs).toBe(1000);
    expect(config.approvalTimeoutMs).toBe(1234);
    expect(config.paperStateDir).toBe('/tmp/paper-state');
    expect(config.dshHome).toBe('/tmp/dsh-home');
    expect(config.dshOverlay).toBe('/tmp/overlay.yml');
  });

  it('reads CHIVES_GATEWAY_URL and normalizes the trailing slash', () => {
    const config = loadConfig({ CHIVES_GATEWAY_URL: 'http://127.0.0.1:9001/' });
    expect(config.gatewayUrl).toBe('http://127.0.0.1:9001');
  });

  it('rejects invalid values', () => {
    expect(() => loadConfig({ CHIVES_PORT: '0' })).toThrow(ConfigError);
    expect(() => loadConfig({ CHIVES_PORT: 'abc' })).toThrow(ConfigError);
    expect(() => loadConfig({ CHIVES_HARNESS: 'other' })).toThrow(ConfigError);
    expect(() => loadConfig({ CHIVES_DEFAULT_ROUTE: 'missing-slash' })).toThrow(ConfigError);
    expect(() => loadConfig({ CHIVES_MAX_PROCESSES: '0' })).toThrow(ConfigError);
    expect(() => loadConfig({ CHIVES_APPROVAL_TIMEOUT_MS: '0' })).toThrow(ConfigError);
    expect(() => loadConfig({ CHIVES_GATEWAY_URL: 'not a url' })).toThrow(ConfigError);
    expect(() => loadConfig({ CHIVES_GATEWAY_URL: 'ftp://127.0.0.1' })).toThrow(ConfigError);
  });
});
