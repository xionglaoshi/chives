/** User overrides for bot display name and avatar. The bot catalog stays elsewhere. */

import type { DatabaseSync } from 'node:sqlite';

import type { BotOverride, BotOverrideUpdate } from './types.js';

interface BotOverrideRow {
  id: string;
  display_name: string | null;
  avatar_emblem: string | null;
  avatar_tone: string | null;
  updated_at: string;
}

function toOverride(row: BotOverrideRow): BotOverride {
  return {
    id: row.id,
    displayName: row.display_name,
    avatarEmblem: row.avatar_emblem,
    avatarTone: row.avatar_tone,
    updatedAt: row.updated_at,
  };
}

export class BotOverrideRepository {
  constructor(private readonly db: DatabaseSync) {}

  get(id: string): BotOverride | undefined {
    const row = this.db.prepare('SELECT * FROM bots WHERE id = ?').get(id) as
      | BotOverrideRow
      | undefined;
    return row === undefined ? undefined : toOverride(row);
  }

  list(): BotOverride[] {
    const rows = this.db.prepare('SELECT * FROM bots ORDER BY id').all() as unknown as BotOverrideRow[];
    return rows.map(toOverride);
  }

  /** Inserts or patches one bot's overrides; omitted fields keep their value. */
  upsert(id: string, update: BotOverrideUpdate, now = new Date()): BotOverride {
    const existing = this.get(id);
    const displayName = update.displayName === undefined ? existing?.displayName ?? null : update.displayName;
    const avatarEmblem =
      update.avatarEmblem === undefined ? existing?.avatarEmblem ?? null : update.avatarEmblem;
    const avatarTone = update.avatarTone === undefined ? existing?.avatarTone ?? null : update.avatarTone;
    this.db
      .prepare(
        `INSERT INTO bots (id, display_name, avatar_emblem, avatar_tone, updated_at)
         VALUES (?, ?, ?, ?, ?)
         ON CONFLICT (id) DO UPDATE SET
           display_name = excluded.display_name,
           avatar_emblem = excluded.avatar_emblem,
           avatar_tone = excluded.avatar_tone,
           updated_at = excluded.updated_at`,
      )
      .run(id, displayName, avatarEmblem, avatarTone, now.toISOString());
    const saved = this.get(id);
    if (saved === undefined) throw new Error(`failed to persist bot override for "${id}"`);
    return saved;
  }
}
