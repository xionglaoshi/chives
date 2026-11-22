import { existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { stringify } from 'yaml';
import { z } from 'zod';
import { AppError } from '../errors.js';
import { DEFAULT_ENTRY_BOT_ID, loadBots, type BotRegistry } from './registry.js';
import type { BotCatalog, BotManifest } from './types.js';

export { DEFAULT_ENTRY_BOT_ID as coordinatorId } from './registry.js';
export const specialistPersona = 'bots/_shared/specialist.md';

const edit = z.object({
  id: z.string().regex(/^[a-z][a-z0-9-]{0,47}$/),
  name: z.string().trim().min(1).max(60).optional(),
  role: z.string().trim().min(1).max(2000).optional(),
}).strict();

export function writeExpert(action: 'create' | 'edit', input: unknown, root: string, data: string,
  registry: BotRegistry, catalog: BotCatalog, busy: (id: string) => boolean): BotManifest {
  const parsed = edit.safeParse(input);
  if (!parsed.success) throw new AppError(400, 'invalid_expert', '请提供有效的 Bot ID、名称或职责');
  const { id, name, role } = parsed.data;
  if (id === DEFAULT_ENTRY_BOT_ID) throw new AppError(403, 'protected_expert', '此工具用于管理其他 Bot');
  const current = registry.get(id);
  const dir = join(root, id);
  const file = join(dir, 'bot.yaml');
  if (action === 'create') {
    if (!name || !role) throw new AppError(400, 'invalid_expert', '新建 Bot 需要名称与职责');
    if (current || existsSync(dir) || existsSync(join(data,'bots',id))) throw new AppError(409, 'expert_exists', '该 ID 已有 Bot 或留存档案');
  } else {
    if (!current) throw new AppError(404, 'unknown_expert', '未找到 Bot');
    if (!name && !role) throw new AppError(400, 'invalid_expert', '请指定要修改的名称或职责');
    if (busy(id)) throw new AppError(409, 'bot_busy', '请等 Bot 完成当前任务');
    if (!lstatSync(dir).isDirectory() || !lstatSync(file).isFile()) throw new AppError(400, 'invalid_expert', 'Bot 清单路径异常');
  }
  const manifest = current ? { ...current, name: name ?? current.name, role: role ?? current.role } : {
    id, name, role, persona: specialistPersona, avatar: { emblem: 'lens', tone: 'jade' },
    skills: [], mcp: [], tools: { code: 'sandboxed', write: 'workspace-only' }, model: 'default',
    can_delegate_to: [], routines: [], memory: { user: 'read', bot: 'read-write' },
    background: false, trading_guard: true,
  };
  const prior = current ? readFileSync(file) : undefined;
  const temp = current ? join(dir, '_bot-'+randomUUID()) : mkdtempSync(join(root,'_new-'));
  let published = false;
  try {
    writeFileSync(current ? temp : join(temp,'bot.yaml'), stringify(manifest), {mode:0o600});
    renameSync(temp, current ? file : dir);
    published = true;
    registry.replaceWith(loadBots(root,catalog));
    return registry.get(id)!;
  } catch (error) {
    if (published && prior) { writeFileSync(temp, prior); renameSync(temp,file); }
    else if (published) rmSync(dir,{recursive:true});
    throw error;
  } finally {
    rmSync(temp,{force:true,recursive:true});
  }
}

/** Remove a dismissed manifest from discovery; the owner's files remain recoverable. */
export function retireBot(id:string, root:string, registry:BotRegistry, catalog:BotCatalog) {
  if (id === DEFAULT_ENTRY_BOT_ID) throw new AppError(403,'permanent_bot','总调度为常驻成员。');
  if (!/^[a-z][a-z0-9-]{0,47}$/.test(id) || !registry.get(id)) throw new AppError(404,'unknown_bot','未找到成员。');
  if (registry.isHired(id)) throw new AppError(409,'bot_hired','请先解聘该成员。');
  const dependants=registry.list().filter(bot=>bot.id!==DEFAULT_ENTRY_BOT_ID && bot.can_delegate_to.includes(id));
  if (dependants.length) throw new AppError(409,'delegation_in_use','请先调整以下成员的委派名单：'+dependants.map(bot=>bot.name).join('、'));
  const src=join(root,id), archive=join(root,'_retired');
  mkdirSync(archive,{recursive:true,mode:0o700});
  const dest=join(archive,id+'-'+randomUUID());
  renameSync(src,dest);
  try { registry.replaceWith(loadBots(root,catalog)); }
  catch (err) { renameSync(dest,src); throw err; }
}
