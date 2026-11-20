import {
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  readlinkSync,
  realpathSync,
  rmSync,
  statSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import {
  botSkillsDir,
  loadSkillSources,
  syncAllBotSkills,
  syncBotSkills,
} from '../src/bots/index.js';
import { makeBot } from './support.js';

const tempDirs: string[] = [];

function tempDir(): string {
  const dir = mkdtempSync(join(tmpdir(), 'chives-skill-links-'));
  tempDirs.push(dir);
  return dir;
}

afterEach(() => {
  for (const dir of tempDirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});

function makeRepo(skills: readonly string[]): string {
  const root = tempDir();
  mkdirSync(join(root, 'skills'));
  for (const name of skills) {
    mkdirSync(join(root, 'skills', name), { recursive: true });
    writeFileSync(
      join(root, 'skills', name, 'SKILL.md'),
      `---\nname: ${name}\ndescription: test skill\n---\n`,
      'utf8',
    );
  }
  return root;
}

describe('loadSkillSources', () => {
  it('discovers new flat packages without a config update and ignores incomplete or linked entries', () => {
    const root = makeRepo(['beta', 'alpha', 'category/nested']);
    const skills = join(root, 'skills');
    symlinkSync(join(skills,'beta'), join(skills,'alias'));
    mkdirSync(join(skills,'future'));
    expect([...loadSkillSources(root).keys()]).toEqual(['alpha','beta']);
    writeFileSync(join(skills,'future/SKILL.md'),'new skill');
    expect([...loadSkillSources(root).keys()]).toEqual(['alpha','beta','future']);
  });
});

describe('syncBotSkills', () => {
  it('links every manifest skill to the flat source directory', () => {
    const repoRoot = makeRepo(['alpha', 'beta']);
    const dataDir = tempDir();
    const bot = makeBot({ id: 'bot-a', skills: ['alpha', 'beta'] });

    const dir = syncBotSkills(bot, { repoRoot, dataDir });

    expect(dir).toBe(botSkillsDir(dataDir, 'bot-a'));
    expect(statSync(dir).isDirectory()).toBe(true);
    expect(readdirSync(dir).sort()).toEqual(['alpha', 'beta']);
    for (const name of ['alpha', 'beta']) {
      const link = join(dir, name);
      expect(lstatSync(link).isSymbolicLink()).toBe(true);
      expect(realpathSync(link)).toBe(realpathSync(join(repoRoot, 'skills', name)));
      expect(readlinkSync(link)).toBe(join(repoRoot, 'skills', name));
    }
  });

  it('deletes stale links while leaving real files and directories alone', () => {
    const repoRoot = makeRepo(['alpha']);
    const dataDir = tempDir();
    const dir = botSkillsDir(dataDir, 'bot-a');
    mkdirSync(dir, { recursive: true });
    symlinkSync(join(repoRoot, 'skills/alpha'), join(dir, 'stale'), 'dir');
    writeFileSync(join(dir, 'notes.txt'), 'keep me', 'utf8');
    mkdirSync(join(dir, 'real-dir'));

    syncBotSkills(makeBot({ id: 'bot-a', skills: ['alpha'] }), { repoRoot, dataDir });

    expect(readdirSync(dir).sort()).toEqual(['alpha', 'notes.txt', 'real-dir']);
    expect(readFileSync(join(dir, 'notes.txt'), 'utf8')).toBe('keep me');
    expect(statSync(join(dir, 'real-dir')).isDirectory()).toBe(true);
    expect(lstatSync(join(dir, 'alpha')).isSymbolicLink()).toBe(true);
  });

  it('refuses to overwrite a real file that occupies a requested skill name', () => {
    const repoRoot = makeRepo(['alpha']);
    const dataDir = tempDir();
    const dir = botSkillsDir(dataDir, 'bot-a');
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, 'alpha'), 'real file', 'utf8');

    expect(() =>
      syncBotSkills(makeBot({ id: 'bot-a', skills: ['alpha'] }), { repoRoot, dataDir }),
    ).toThrow(/exists and is not a symbolic link/);
    expect(readFileSync(join(dir, 'alpha'), 'utf8')).toBe('real file');
  });

  it('replaces a link that points at the wrong target', () => {
    const repoRoot = makeRepo(['alpha']);
    const dataDir = tempDir();
    const dir = botSkillsDir(dataDir, 'bot-a');
    mkdirSync(dir, { recursive: true });
    symlinkSync(join(repoRoot, 'skills', 'legacy-group', 'alpha'), join(dir, 'alpha'), 'dir');

    syncBotSkills(makeBot({ id: 'bot-a', skills: ['alpha'] }), { repoRoot, dataDir });

    expect(realpathSync(join(dir, 'alpha'))).toBe(realpathSync(join(repoRoot, 'skills/alpha')));
  });

  it('gives a bot with no skills an empty directory', () => {
    const repoRoot = makeRepo(['alpha']);
    const dataDir = tempDir();
    const dir = syncBotSkills(makeBot({ id: 'bot-empty', skills: [] }), { repoRoot, dataDir });
    expect(readdirSync(dir)).toEqual([]);
  });

  it('reports a skill source that is not a directory', () => {
    const repoRoot = makeRepo([]);
    const dataDir = tempDir();
    expect(() =>
      syncBotSkills(makeBot({ id: 'bot-a', skills: ['alpha'] }), { repoRoot, dataDir }),
    ).toThrow(/no valid package/);
  });
});

describe('syncAllBotSkills', () => {
  it('reconciles every bot with one discovered catalog', () => {
    const repoRoot = makeRepo(['alpha', 'beta']);
    const dataDir = tempDir();
    syncAllBotSkills(
      [
        makeBot({ id: 'bot-a', skills: ['alpha'] }),
        makeBot({ id: 'bot-b', skills: ['beta'] }),
        makeBot({ id: 'bot-empty', skills: [] }),
      ],
      { repoRoot, dataDir },
    );

    expect(readdirSync(botSkillsDir(dataDir, 'bot-a'))).toEqual(['alpha']);
    expect(readdirSync(botSkillsDir(dataDir, 'bot-b'))).toEqual(['beta']);
    expect(readdirSync(botSkillsDir(dataDir, 'bot-empty'))).toEqual([]);
  });
});
