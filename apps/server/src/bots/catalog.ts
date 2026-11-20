/** Builds the per-bot capability catalog from repository files (never a hard-coded list). */

import { existsSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

import { loadSkillSources } from './skill-links.js';
import { BotLoadError } from './errors.js';
import type { BotCatalog } from './types.js';
import { loadOverlayMcpConfigs } from '../harness/overlays.js';

const OVERLAYS_DECLARATION = /^OVERLAYS\s*=\s*\[([^\]]*)\]/m;

export function buildCatalog(repoRoot: string): BotCatalog {
  const root = resolve(repoRoot);
  const skills = [...loadSkillSources(root).keys()];

  const buildScriptPath = join(root, 'scripts/build-finance-bundle.py');
  const buildScript = readFileSync(buildScriptPath, 'utf8');
  const declaration = OVERLAYS_DECLARATION.exec(buildScript);
  if (declaration === null) {
    throw new BotLoadError([
      { file: buildScriptPath, message: 'OVERLAYS declaration not found; cannot build the MCP catalog' },
    ]);
  }
  const overlayNames = [...(declaration[1] ?? '').matchAll(/"([^"]+)"/g)].map((match) => match[1] ?? '');
  if (overlayNames.length === 0) {
    throw new BotLoadError([{ file: buildScriptPath, message: 'OVERLAYS declaration is empty' }]);
  }
  // The strategy MCP is gated per bot by `strategies`, not by the desktop preset.
  // Include it as soon as its overlay exists so the server can launch it even
  // before the bundle script's OVERLAYS line is updated by the reviewer.
  if (!overlayNames.includes('strategy') && existsSync(join(root, 'overlays', 'strategy.cordis.yml'))) {
    overlayNames.push('strategy');
  }

  const overlays = loadOverlayMcpConfigs(root);
  const mcp: string[] = [];
  for (const name of overlayNames) {
    const overlayPath = join(root, 'overlays', `${name}.cordis.yml`);
    const configs = overlays.byFile.get(overlayPath);
    if (configs === undefined) {
      throw new BotLoadError([{ file: overlayPath, message: 'overlay from OVERLAYS has no readable MCP entry' }]);
    }
    for (const config of configs) {
      if (!mcp.includes(config.serverName)) mcp.push(config.serverName);
    }
  }

  return { skills, mcp };
}
