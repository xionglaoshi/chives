/** Locates the shipped plugin and renders its Cordis patch. */

import { fileURLToPath } from 'node:url';

export const STREAM_SOCKET_ENV = 'CHIVES_STREAM_SOCKET';

/** Absolute path to the published plain-JS plugin (never compiled). */
export function pluginPath(): string {
  return fileURLToPath(new URL('../../plugin/chives-stream.plugin.mjs', import.meta.url));
}

function yamlScalar(value: string): string {
  return /^[A-Za-z0-9_./@+-]+$/.test(value) ? value : JSON.stringify(value);
}

/** Equivalent of `fixtures/acp-probe/stream.cordis.yml` with an absolute path. */
export function streamPatchYaml(path: string = pluginPath()): string {
  return [
    '- insert:',
    '    - id: chives-stream',
    `      name: ${yamlScalar(path)}`,
    '      config:',
    '        verbose: true',
    '',
  ].join('\n');
}
