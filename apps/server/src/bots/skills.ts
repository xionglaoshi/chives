/** Reads skill descriptions from SKILL.md frontmatter for the bot profile page. */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { loadSkillSources } from './skill-links.js';

import { parse } from 'yaml';

const FRONTMATTER = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/;

/** First sentence of a text block; falls back to the whole block. */
export function firstSentence(text: string): string {
  const trimmed = text.trim().replace(/\s+/g, ' ');
  if (trimmed === '') return '';
  const boundary = /[。！？]|\.(?=\s|$)/u.exec(trimmed);
  if (boundary === null) return trimmed;
  return trimmed.slice(0, boundary.index + boundary[0].length).trim();
}

function descriptionOf(text: string): string {
  const match = FRONTMATTER.exec(text);
  if (match === null) return '';
  try {
    const parsed: unknown = parse(match[1] ?? '');
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return '';
    const description = (parsed as Record<string, unknown>)['description'];
    return typeof description === 'string' ? firstSentence(description) : '';
  } catch {
    return '';
  }
}

/**
 * Maps skill name → first sentence of its description. Names come from
 * the installed skill directories; files that cannot be read are simply omitted.
 */
export function loadSkillDescriptions(repoRoot: string): ReadonlyMap<string, string> {
  const descriptions = new Map<string, string>();
  let sources;
  try {
    sources = loadSkillSources(repoRoot);
  } catch {
    return descriptions;
  }
  for (const { name, path } of sources.values()) {
    try {
      const text = readFileSync(join(path, 'SKILL.md'), 'utf8');
      descriptions.set(name, descriptionOf(text));
    } catch {
      descriptions.set(name, '');
    }
  }
  return descriptions;
}
