/** Memory facade: file store, write policy, audit log, injection, and SSE. */

import { existsSync, readdirSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import type { BotMemoryItem, BotMemoryList } from '../api/protocol.js';
import type { EventBus } from '../events/index.js';
import { MemoryAuditLog, sha256 } from './audit.js';
import { buildMemoryInjection } from './injection.js';
import {
  computeExpiresAt,
  evaluateMemoryWrite,
  evaluateUserEdit,
  isExpired,
  isMemoryKind,
  memorySlug,
  policyMessage,
} from './policy.js';
import { MemoryFileStore, serializeMemory } from './store.js';
import type {
  MemoryActor,
  MemoryCandidate,
  MemoryKind,
  MemoryRecord,
  MemoryWriteResult,
  UserMemoryEdit,
} from './types.js';

export interface MemoryServiceOptions {
  dataDir: string;
  now?: () => Date;
  bus?: EventBus;
}

export interface MemoryWriteInput {
  botId: string;
  taskId: string;
  actor: MemoryActor;
  candidate: MemoryCandidate;
  userTexts: readonly string[];
  depth?: number;
}

export interface MemoryUserPatch {
  title?: string;
  body?: string;
  kind?: MemoryKind;
  /** `null` means no expiry; omitted keeps the existing/kind-default value. */
  expiresAt?: string | null;
}

export interface MemoryInjection {
  text: string;
  auditCursor: number;
}

export class MemoryService {
  private readonly dataDir: string;
  private readonly now: () => Date;
  private readonly bus: EventBus | undefined;
  private readonly audit: MemoryAuditLog;
  private readonly stores = new Map<string, MemoryFileStore>();

  constructor(options: MemoryServiceOptions) {
    this.dataDir = options.dataDir;
    this.now = options.now ?? (() => new Date());
    this.bus = options.bus;
    this.audit = new MemoryAuditLog(options.dataDir);
    this.scanBots();
  }

  reloadFromDisk(): void {
    this.stores.clear();
    this.scanBots();
  }

  private scanBots(): void {
    const root = join(this.dataDir, 'bots');
    if (!existsSync(root)) return;
    let entries: string[];
    try {
      entries = readdirSync(root);
    } catch {
      return;
    }
    for (const botId of entries) this.store(botId);
  }

  private store(botId: string): MemoryFileStore | undefined {
    if (!/^[a-z0-9][a-z0-9-]*$/.test(botId)) return undefined;
    const existing = this.stores.get(botId);
    if (existing !== undefined) return existing;
    const store = new MemoryFileStore(this.dataDir, botId);
    this.stores.set(botId, store);
    return store;
  }

  list(botId: string): MemoryRecord[] {
    return this.store(botId)?.list() ?? [];
  }

  get(botId: string, slug: string): MemoryRecord | undefined {
    return this.store(botId)?.get(slug);
  }

  stats(botId: string): { count: number; updatedAt: string | null } {
    return this.store(botId)?.stats() ?? { count: 0, updatedAt: null };
  }

  toDto(record: MemoryRecord): BotMemoryItem {
    return {
      slug: record.slug,
      title: record.title,
      description: record.description,
      kind: record.kind,
      writtenAt: record.writtenAt,
      expiresAt: record.expiresAt,
      expired: isExpired(record.expiresAt, this.now()),
      source: record.source,
      sourceTaskId: record.sourceTaskId,
      body: record.body,
    };
  }

  listDto(botId: string): BotMemoryList {
    const items = this.list(botId).map((record) => this.toDto(record));
    return {
      count: items.length,
      limit: 200,
      items,
      available: true,
      updatedAt: this.stats(botId).updatedAt,
    };
  }

  /** The block placed after `## 你记得的`; empty when nothing is stored. */
  renderInjection(botId: string): string {
    return buildMemoryInjection(this.list(botId), this.now());
  }

  auditCursor(): number {
    return this.audit.cursor;
  }

  /**
   * Returns the `[记忆更新]` block for user edits/deletes after `cursor`, plus
   * the new cursor. The caller stores the cursor on the task, so the block is
   * shown on exactly the next prompt.
   */
  consumeChanges(botId: string, cursor: number | null): MemoryInjection {
    if (cursor === null) return { text: '', auditCursor: this.audit.cursor };
    const { changes, cursor: next } = this.audit.userChanges(botId, cursor);
    if (changes.length === 0) return { text: '', auditCursor: next };
    const seen = new Set<string>();
    const lines: string[] = [];
    for (const change of changes) {
      const key = `${change.action}:${change.slug}`;
      if (seen.has(key)) continue;
      seen.add(key);
      if (change.action === 'delete') {
        lines.push(`- 「${change.title}」不再适用`);
      } else {
        const record = this.get(botId, change.slug);
        if (record === undefined) {
          lines.push(`- 「${change.title}」不再适用`);
        } else {
          lines.push(`- 「${record.title}」改为：${record.body}`);
        }
      }
    }
    return {
      text: ['[记忆更新] 用户刚修改/删除了以下记忆，以此为准：', ...lines].join('\n'),
      auditCursor: next,
    };
  }

  write(input: MemoryWriteInput): MemoryWriteResult {
    const store = this.store(input.botId);
    if (store === undefined) {
      return { ok: false, reason: 'unknown_bot', message: '未知的 bot' };
    }
    const slug = memorySlug(input.candidate.title);
    const current = store.get(slug);
    const decision = evaluateMemoryWrite({
      candidate: input.candidate,
      userTexts: input.userTexts,
      existing: current,
      count: store.stats().count,
      now: this.now(),
      ...(input.depth === undefined ? {} : { depth: input.depth }),
    });
    if (!decision.ok) {
      this.recordAudit({
        bot: input.botId,
        action: 'reject',
        actor: input.actor,
        slug,
        title: input.candidate.title,
        before: null,
        after: null,
        reason: decision.reason,
      });
      return { ok: false, reason: decision.reason, message: decision.message };
    }
    const kind = input.candidate.kind;
    if (!isMemoryKind(kind)) {
      return { ok: false, reason: 'invalid_kind', message: policyMessage('invalid_kind') };
    }
    const now = this.now();
    const record: MemoryRecord = {
      slug: decision.slug,
      title: input.candidate.title.trim(),
      description: (input.candidate.description ?? '').trim(),
      kind,
      writtenAt: now.toISOString(),
      expiresAt: decision.expiresAt,
      source: input.actor,
      sourceTaskId: input.taskId,
      body: input.candidate.body.trim(),
      updatedAt: now.toISOString(),
    };
    const { before } = store.put(record, now);
    const saved = store.get(record.slug) ?? record;
    this.recordAudit({
      bot: input.botId,
      action: current === undefined ? 'create' : 'update',
      actor: input.actor,
      slug: saved.slug,
      title: saved.title,
      before,
      after: serializeMemory(saved),
      reason: null,
    });
    this.publish(input.botId, current === undefined ? 'created' : 'updated', saved);
    return { ok: true, memory: saved };
  }

  updateByUser(botId: string, slug: string, patch: MemoryUserPatch): MemoryWriteResult {
    const store = this.store(botId);
    if (store === undefined) return { ok: false, reason: 'unknown_bot', message: '未知的 bot' };
    const existing = store.get(slug);
    if (existing === undefined) {
      return { ok: false, reason: 'not_found', message: policyMessage('not_found') };
    }
    const kind = patch.kind ?? existing.kind;
    let expiresAt = patch.expiresAt;
    if (expiresAt === undefined) {
      expiresAt =
        patch.kind !== undefined && patch.kind !== existing.kind
          ? computeExpiresAt(kind, undefined, this.now())
          : existing.expiresAt;
    }
    const edit: UserMemoryEdit = {
      title: patch.title ?? existing.title,
      body: patch.body ?? existing.body,
      kind,
      expiresAt,
    };
    const decision = evaluateUserEdit(edit);
    if (!decision.ok) {
      this.recordAudit({
        bot: botId,
        action: 'reject',
        actor: 'user',
        slug,
        title: edit.title,
        before: null,
        after: null,
        reason: decision.reason,
      });
      return { ok: false, reason: decision.reason, message: decision.message };
    }
    const now = this.now();
    const record: MemoryRecord = {
      ...existing,
      title: edit.title.trim(),
      body: edit.body.trim(),
      kind: edit.kind,
      expiresAt: edit.expiresAt,
      source: 'user',
      updatedAt: now.toISOString(),
    };
    const { before } = store.put(record, now);
    const saved = store.get(slug) ?? record;
    this.recordAudit({
      bot: botId,
      action: 'update',
      actor: 'user',
      slug,
      title: saved.title,
      before,
      after: serializeMemory(saved),
      reason: null,
    });
    this.publish(botId, 'updated', saved);
    return { ok: true, memory: saved };
  }

  deleteByUser(botId: string, slug: string): MemoryWriteResult {
    const store = this.store(botId);
    if (store === undefined) return { ok: false, reason: 'unknown_bot', message: '未知的 bot' };
    const existing = store.get(slug);
    if (existing === undefined) {
      return { ok: false, reason: 'not_found', message: policyMessage('not_found') };
    }
    const before = store.delete(slug);
    this.recordAudit({
      bot: botId,
      action: 'delete',
      actor: 'user',
      slug,
      title: existing.title,
      before,
      after: null,
      reason: null,
    });
    this.publish(botId, 'deleted', null);
    return { ok: true };
  }

  retireForReview(botId:string,observed:MemoryRecord,reason:string,job:string){
    const store=this.store(botId),current=store?.get(observed.slug);
    if(!store||!current||serializeMemory(current)!==serializeMemory(observed))return;
    const dir=join(this.dataDir,'user-archive-state','retired-memories',job,botId);
    mkdirSync(dir,{recursive:true,mode:0o700});
    const copy=join(dir,observed.slug+'.md'),source=serializeMemory(current);
    if(!existsSync(copy))writeFileSync(copy,source,{flag:'wx',mode:0o600});
    if(readFileSync(copy,'utf8')!==source)return;
    const before=store.delete(current.slug);
    this.recordAudit({bot:botId,action:'delete',actor:'capture',slug:current.slug,title:current.title,before,after:null,reason});
    this.publish(botId,'deleted',null);
  }

  /** Fuzzy title/description match; an empty topic lists everything. */
  readForTool(botId: string, topic?: string): BotMemoryList {
    const needle = topic?.trim().toLowerCase() ?? '';
    const list = this.listDto(botId);
    if (needle === '') return list;
    const items = list.items.filter(
      (item) =>
        item.title.toLowerCase().includes(needle) ||
        item.description.toLowerCase().includes(needle),
    );
    return { ...list, count: items.length, items };
  }

  private recordAudit(input: {
    bot: string;
    action: 'create' | 'update' | 'delete' | 'reject';
    actor: MemoryActor;
    slug: string;
    title: string;
    before: string | null;
    after: string | null;
    reason: string | null;
  }): void {
    this.audit.append({
      at: this.now().toISOString(),
      bot: input.bot,
      action: input.action,
      actor: input.actor,
      slug: input.slug,
      title: input.title,
      before_sha256: input.before === null ? null : sha256(input.before),
      after_sha256: input.after === null ? null : sha256(input.after),
      reason: input.reason,
    });
  }

  private publish(
    botId: string,
    action: 'created' | 'updated' | 'deleted',
    record: MemoryRecord | null,
  ): void {
    if (this.bus === undefined) return;
    const stats = this.stats(botId);
    this.bus.publish({
      type: 'memory.updated',
      botId,
      action,
      memory: record === null ? null : this.toDto(record),
      count: stats.count,
    });
  }
}
