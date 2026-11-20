import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  symlinkSync,
  utimesSync,
  writeFileSync,
} from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { createApp, type ChivesApp } from '../src/app.js';
import type { MessageAccepted, WorkspaceFileList } from '../src/api/protocol.js';
import {
  WORKSPACE_DIRECTORIES,
  cleanupScratch,
  generateWorkspaceMap,
  isDeliverablePath,
  prepareWorkspace,
  writeWorkspaceMap,
} from '../src/deliverables/index.js';
import { FakeDriver, type FakeStep } from '../src/harness/fake.js';
import { closeServer, listen, testConfig, waitFor } from './support.js';

const directories: string[] = [];
const apps: Array<{ app: ChivesApp; baseUrl: string }> = [];

afterEach(async () => {
  for (const entry of apps.splice(0)) {
    entry.app.sse.closeAll();
    await closeServer(entry.app.server);
    await entry.app.close();
  }
  for (const directory of directories.splice(0)) {
    await rm(directory, { recursive: true, force: true });
  }
  vi.restoreAllMocks();
});

async function tempDir(prefix: string): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), prefix));
  directories.push(directory);
  return directory;
}

function workspaceOf(dataDir: string, botId: string): string {
  return join(dataDir, 'bots', botId, 'workspace');
}

function oldDate(daysAgo: number): Date {
  return new Date(Date.now() - daysAgo * 24 * 60 * 60 * 1000);
}

async function startApp(
  dataDir: string,
  script: readonly FakeStep[] = [],
): Promise<{ app: ChivesApp; baseUrl: string }> {
  const driver = new FakeDriver({
    script,
    workspaceDirFor: (bot) => workspaceOf(dataDir, bot.id),
  });
  const app = createApp({ config: testConfig(dataDir), driver });
  const baseUrl = await listen(app.server);
  const entry = { app, baseUrl };
  apps.push(entry);
  return entry;
}

describe('isDeliverablePath', () => {
  it('accepts documents and images outside scripts, scratch, and data', () => {
    expect(isDeliverablePath('reports/000528-柳工/20261117_估值深度分析.md')).toBe(true);
    expect(isDeliverablePath('reports/deck.pptx')).toBe(true);
    expect(isDeliverablePath('charts/000528-柳工/pe.png')).toBe(true);
    expect(isDeliverablePath('charts/000528-柳工/pe.svg')).toBe(true);
    expect(isDeliverablePath('root-report.html')).toBe(true);
    expect(isDeliverablePath('other/topic/note.pdf')).toBe(true);
    expect(isDeliverablePath('notes/table.xlsx')).toBe(true);
    expect(isDeliverablePath('reports/MAP.md')).toBe(true);
  });

  it('rejects code, data, temporary trees, MAP.md, and escapes', () => {
    for (const path of [
      'calc.py',
      'scripts/calc.py',
      'scratch/tmp.json',
      'data/000528-柳工/quotes.csv',
      'reports/notes.json',
      'charts/pe.txt',
      'deep/nested/log.log',
      'MAP.md',
      '../secret.md',
      'reports/../../secret.md',
      '',
    ]) {
      expect(isDeliverablePath(path), path).toBe(false);
    }
  });
});

describe('workspace layout', () => {
  it('creates the conventional directories and keeps an existing MAP.md', async () => {
    const root = await tempDir('chives-layout-');
    const workspace = join(root, 'workspace');
    mkdirSync(workspace, { recursive: true });
    writeFileSync(join(workspace, 'MAP.md'), 'custom map');
    prepareWorkspace(workspace);
    for (const directory of WORKSPACE_DIRECTORIES) {
      expect(existsSync(join(workspace, directory))).toBe(true);
    }
    expect(readFileSync(join(workspace, 'MAP.md'), 'utf8')).toBe('custom map');

    const fresh = join(root, 'fresh');
    prepareWorkspace(fresh, { now: new Date('2026-11-17T08:00:00.000Z') });
    expect(readFileSync(join(fresh, 'MAP.md'), 'utf8')).toContain('# 工作目录地图');
    expect(readFileSync(join(fresh, 'MAP.md'), 'utf8')).toContain('2026-11-17 08:00:00 UTC');
  });

  it('removes only old regular files under scratch and never follows symlinks', async () => {
    const root = await tempDir('chives-scratch-');
    const workspace = join(root, 'workspace');
    prepareWorkspace(workspace);
    const scratch = join(workspace, 'scratch');
    writeFileSync(join(scratch, 'old.json'), 'old');
    writeFileSync(join(scratch, 'recent.json'), 'recent');
    mkdirSync(join(scratch, 'nested'), { recursive: true });
    writeFileSync(join(scratch, 'nested', 'old.txt'), 'old');
    writeFileSync(join(scratch, 'nested', 'keep.md'), 'keep');
    mkdirSync(join(scratch, 'empty'), { recursive: true });
    const old = oldDate(9);
    utimesSync(join(scratch, 'old.json'), old, old);
    utimesSync(join(scratch, 'nested', 'old.txt'), old, old);
    const outside = join(root, 'outside.md');
    writeFileSync(outside, 'outside');
    utimesSync(outside, old, old);
    symlinkSync(outside, join(scratch, 'link.md'));
    symlinkSync(root, join(scratch, 'linkdir'));

    const result = cleanupScratch(workspace, { now: new Date() });

    expect(result.removedFiles).toBe(2);
    expect(existsSync(join(scratch, 'old.json'))).toBe(false);
    expect(existsSync(join(scratch, 'nested', 'old.txt'))).toBe(false);
    expect(existsSync(join(scratch, 'recent.json'))).toBe(true);
    expect(existsSync(join(scratch, 'nested', 'keep.md'))).toBe(true);
    expect(existsSync(join(scratch, 'empty'))).toBe(false);
    expect(existsSync(join(scratch, 'link.md'))).toBe(true);
    expect(existsSync(outside)).toBe(true);
    expect(result.removedDirectories).toBeGreaterThanOrEqual(1);
  });
});

describe('MAP.md generation', () => {
  it('groups reports by topic, extracts titles, and lists unarchived entries', async () => {
    const root = await tempDir('chives-map-');
    const workspace = join(root, 'workspace');
    prepareWorkspace(workspace);
    mkdirSync(join(workspace, 'reports', '000528-柳工'), { recursive: true });
    mkdirSync(join(workspace, 'reports', '宏观'), { recursive: true });
    mkdirSync(join(workspace, 'charts', '000528-柳工'), { recursive: true });
    mkdirSync(join(workspace, 'data', '000528-柳工'), { recursive: true });
    mkdirSync(join(workspace, 'scripts'), { recursive: true });
    mkdirSync(join(workspace, 'scratch'), { recursive: true });
    mkdirSync(join(workspace, 'old_dir'), { recursive: true });

    const older = join(workspace, 'reports', '000528-柳工', '20261117_估值.md');
    const newer = join(workspace, 'reports', '000528-柳工', '20261118_跟踪.md');
    const macro = join(workspace, 'reports', '宏观', '20261110_周报.md');
    const untitled = join(workspace, 'reports', '无标题.md');
    writeFileSync(older, '# 柳工估值深度分析\n\n正文');
    writeFileSync(newer, '# 柳工跟踪\n');
    writeFileSync(macro, '# 宏观周报\n');
    writeFileSync(untitled, '没有标题');
    writeFileSync(join(workspace, 'charts', '000528-柳工', 'pe.png'), 'png');
    writeFileSync(join(workspace, 'data', '000528-柳工', 'quotes.csv'), 'a,b');
    writeFileSync(join(workspace, 'scripts', 'calc.py'), 'print(1)');
    writeFileSync(join(workspace, 'scratch', 'tmp.json'), '{}');
    writeFileSync(join(workspace, 'calc.py'), 'print(2)');
    writeFileSync(join(workspace, 'old_dir', 'legacy.md'), '# 旧文件');
    utimesSync(older, oldDate(3), oldDate(3));
    utimesSync(newer, oldDate(1), oldDate(1));
    utimesSync(macro, oldDate(5), oldDate(5));

    const map = generateWorkspaceMap(workspace, { now: new Date('2026-11-17T08:00:00.000Z') });

    expect(map).toContain('# 工作目录地图');
    expect(map).toContain('生成时间：2026-11-17 08:00:00 UTC');
    expect(map).toContain('### 000528-柳工');
    expect(map).toContain('### 宏观');
    expect(map).toContain('[柳工估值深度分析](reports/000528-柳工/20261117_估值.md)');
    expect(map).toContain('[柳工跟踪](reports/000528-柳工/20261118_跟踪.md)');
    expect(map).toContain('[宏观周报](reports/宏观/20261110_周报.md)');
    expect(map).toContain('### （未分主题）');
    expect(map).toContain('[无标题.md](reports/无标题.md)');
    expect(map.indexOf('[柳工跟踪]')).toBeLessThan(map.indexOf('[柳工估值深度分析]'));
    expect(map).toContain('### 000528-柳工（1 个文件）');
    expect(map).toContain('[pe.png](charts/000528-柳工/pe.png)');
    expect(map).toContain('[quotes.csv](data/000528-柳工/quotes.csv)');
    expect(map).toContain('[calc.py](scripts/calc.py)');
    expect(map).toContain('共 1 个文件');
    expect(map).toContain('## 未归档');
    expect(map).toContain('- `calc.py`');
    expect(map).toContain('- `old_dir/`（目录）');
    expect(map).not.toContain(workspace);
  });

  it('truncates sections above 500 files and notes the omitted count', async () => {
    const root = await tempDir('chives-map-large-');
    const workspace = join(root, 'workspace');
    prepareWorkspace(workspace);
    const topic = join(workspace, 'reports', '批量');
    mkdirSync(topic, { recursive: true });
    for (let index = 0; index < 501; index += 1) {
      writeFileSync(join(topic, `r${index}.md`), '# 批量报告\n');
    }
    const map = generateWorkspaceMap(workspace);
    expect(map).toContain('另有 401 个报告未列出');
  });

  it('writes MAP.md atomically and logs instead of throwing on failure', async () => {
    const root = await tempDir('chives-map-write-');
    const workspace = join(root, 'workspace');
    prepareWorkspace(workspace);
    writeFileSync(join(workspace, 'app.md'), '# hello');
    expect(writeWorkspaceMap(workspace)).toBe(true);
    expect(readFileSync(join(workspace, 'MAP.md'), 'utf8')).toContain('- `app.md`');
    expect(readdirSync(workspace).filter((name) => name.endsWith('.tmp'))).toEqual([]);

    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    expect(writeWorkspaceMap(join(root, 'missing'))).toBe(false);
    expect(error).toHaveBeenCalled();
  });
});

describe('workspace API and task capture', () => {
  it('records only deliverables, rewrites MAP.md, and serves it as text', async () => {
    const dataDir = await tempDir('chives-workspace-api-');
    const workspace = workspaceOf(dataDir, 'expert');
    prepareWorkspace(workspace);
    const stale = join(workspace, 'scratch', 'stale.json');
    writeFileSync(stale, '{}');
    utimesSync(stale, oldDate(9), oldDate(9));
    writeFileSync(join(workspace, 'scratch', 'recent.json'), '{}');

    const { app, baseUrl } = await startApp(dataDir, [
      {
        type: 'write',
        path: 'reports/000528-柳工/20261117_估值.md',
        content: '# 柳工估值\n',
      },
      { type: 'write', path: 'charts/000528-柳工/pe.png', content: 'png-bytes' },
      { type: 'write', path: 'calc.py', content: 'print(1)' },
      { type: 'write', path: 'data/000528-柳工/quotes.csv', content: 'a,b\n1,2\n' },
      { type: 'write', path: 'scratch/tmp.json', content: '{}' },
      { type: 'message', text: '完成' },
    ]);

    const accepted = (await (
      await fetch(`${baseUrl}/api/bots/expert/messages`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: '写报告' }),
      })
    ).json()) as MessageAccepted;
    await waitFor(() => app.store.tasks.get(accepted.taskId)?.status === 'done');

    const rows = app.store.deliverables.listByTask(accepted.taskId);
    expect(rows.map((row) => row.path).sort()).toEqual([
      'charts/000528-柳工/pe.png',
      'reports/000528-柳工/20261117_估值.md',
    ]);
    expect(existsSync(stale)).toBe(false);
    expect(existsSync(join(workspace, 'scratch', 'recent.json'))).toBe(true);

    const map = readFileSync(join(workspace, 'MAP.md'), 'utf8');
    expect(map).toContain('[柳工估值](reports/000528-柳工/20261117_估值.md)');
    expect(map).toContain('共 2 个文件');

    const listed = (await (
      await fetch(`${baseUrl}/api/bots/expert/files?recursive=1`)
    ).json()) as WorkspaceFileList;
    const paths = listed.files.map((file) => file.path);
    expect(paths).toContain('reports/000528-柳工/20261117_估值.md');
    expect(paths).toContain('calc.py');
    expect(paths).not.toContain('MAP.md');

    const text = await fetch(`${baseUrl}/api/bots/expert/files/text?path=MAP.md`);
    expect(text.status).toBe(200);
    expect(text.headers.get('content-type')).toBe('text/markdown; charset=utf-8');
    expect(await text.text()).toContain('# 工作目录地图');

    expect(
      (await fetch(`${baseUrl}/api/bots/expert/files/text?path=calc.py`)).status,
    ).toBe(400);
  });

  it('creates the layout when the profile file list is first opened', async () => {
    const dataDir = await tempDir('chives-workspace-first-');
    const { baseUrl } = await startApp(dataDir);
    const response = await fetch(`${baseUrl}/api/bots/expert/files`);
    expect(response.status).toBe(200);
    const workspace = workspaceOf(dataDir, 'expert');
    expect(existsSync(join(workspace, 'MAP.md'))).toBe(true);
    expect(readdirSync(workspace).filter((name) => name === 'MAP.md')).toHaveLength(1);
  });
});
