import { randomUUID } from 'node:crypto';
import { existsSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

export const retiredBotIds = { emma: 'cio', noah: 'cro', jerry: 'trader', luna: 'analyst' } as const;

export function migrateRoleFiles(dataDir: string, workspaceRoot?: string): void {
  const directories = new Set([join(dataDir, 'bots'), ...(workspaceRoot ? [join(workspaceRoot, 'bots')] : [])]);
  const moves = [...directories].flatMap(dir => Object.entries(retiredBotIds).map(([from, to]) =>
    [join(dir, from), join(dir, to)] as const)).filter(([from]) => existsSync(from));
  for (const [from, to] of moves) {
    if (existsSync(to)) throw new Error(`岗位目录同时存在，请核对 ${from} 与 ${to}`);
  }
  for (const [from, to] of moves) renameSync(from, to);
  for (const name of ['bot-employment.json', 'sidebar-order.json']) {
    const file = join(dataDir, 'profile', name);
    if (!existsSync(file)) continue;
    const prior: unknown = JSON.parse(readFileSync(file, 'utf8'));
    if (!Array.isArray(prior)) continue;
    const next = [...new Set(prior.map(id => Object.hasOwn(retiredBotIds, id)
      ? retiredBotIds[id as keyof typeof retiredBotIds] : id))];
    if (JSON.stringify(prior) === JSON.stringify(next)) continue;
    const temp = file + '.' + randomUUID();
    try {
      writeFileSync(temp, JSON.stringify(next, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
      renameSync(temp, file);
    } finally { rmSync(temp, { force: true }); }
  }
}

/** Preserve the existing Bot profile and portable settings when upgrading an installation. */
export function migrateCeoFiles(dataDir: string, workspaceRoot?: string): void {
  if (workspaceRoot) {
    const previousWorkspace = join(workspaceRoot, 'bots', 'operator');
    const currentWorkspace = join(workspaceRoot, 'bots', 'ceo');
    if (existsSync(previousWorkspace)) {
      if (existsSync(currentWorkspace)) throw new Error('总经理的新旧工作目录同时存在，请核对后再启动。');
      renameSync(previousWorkspace, currentWorkspace);
    }
  }
  const previous = join(dataDir, 'bots', 'operator');
  const current = join(dataDir, 'bots', 'ceo');
  const proposal = join(dataDir, 'profile', 'pending-operator.json');
  const currentProposal = join(dataDir, 'profile', 'pending-ceo.json');
  if (existsSync(previous) && existsSync(current) || existsSync(proposal) && existsSync(currentProposal)) {
    throw new Error('总经理数据迁移遇到两份现有记录，请核对数据目录后再启动。');
  }
  if (existsSync(previous)) renameSync(previous, current);
  if (existsSync(proposal)) renameSync(proposal, currentProposal);
  for (const name of ['bot-employment.json', 'sidebar-order.json']) {
    const file = join(dataDir, 'profile', name);
    if (!existsSync(file)) continue;
    const ids: unknown = JSON.parse(readFileSync(file, 'utf8'));
    if (!Array.isArray(ids) || !ids.includes('operator')) continue;
    const temp = file + '.' + randomUUID();
    try {
      writeFileSync(temp, JSON.stringify([...new Set(ids.map(id => id === 'operator' ? 'ceo' : id))], null, 2) + '\n',
        { mode: 0o600, flag: 'wx' });
      renameSync(temp, file);
    } finally { rmSync(temp, { force: true }); }
  }
}
