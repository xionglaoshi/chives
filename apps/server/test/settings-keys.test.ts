import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { namesWithValues } from '../src/settings/service.js';

describe('namesWithValues', () => {
  it('returns only names with non-empty values and never the values', () => {
    const dir = mkdtempSync(join(tmpdir(), 'chives-keys-'));
    const file = join(dir, 'secrets.env');
    writeFileSync(file, 'TAVILY_API_KEY=tvly-secret-value\nGILDATA_TOKEN=\n# comment\nexport X_BEARER_TOKEN="abc"\nEMPTY=""\n');
    const names = namesWithValues(file);
    expect([...names].sort()).toEqual(['TAVILY_API_KEY', 'X_BEARER_TOKEN']);
    expect(JSON.stringify([...names])).not.toContain('secret-value');
  });

  it('returns an empty set when the file is missing', () => {
    expect(namesWithValues(join(tmpdir(), 'does-not-exist', 'secrets.env')).size).toBe(0);
  });
});
