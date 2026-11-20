/** Bot-level memory records and the values accepted by the write policy. */

export type MemoryKind = 'preference' | 'view' | 'fact' | 'note';
export type MemorySource = 'capture' | 'tool' | 'user';
export type MemoryActor = MemorySource;
export type MemoryAction = 'create' | 'update' | 'delete' | 'reject';

export const MEMORY_KINDS: readonly MemoryKind[] = ['preference', 'view', 'fact', 'note'];
export const MEMORY_MAX_PER_BOT = 200;
export const MEMORY_MAX_BODY_CHARS = 800;
export const MEMORY_MAX_TITLE_CHARS = 80;
export const MEMORY_MAX_DESCRIPTION_CHARS = 160;
/** `view` and `fact` entries become stale; preferences and notes do not. */
export const DEFAULT_EXPIRY_DAYS: Readonly<Record<MemoryKind, number | null>> = {
  preference: null,
  view: 90,
  fact: 180,
  note: null,
};

export interface MemoryRecord {
  slug: string;
  title: string;
  description: string;
  kind: MemoryKind;
  /** ISO timestamp written to the file; user edits keep the original value. */
  writtenAt: string;
  expiresAt: string | null;
  source: MemorySource;
  sourceTaskId: string | null;
  body: string;
  /** File mtime, used by the overview card's "recent update". */
  updatedAt: string;
}

export interface MemoryCandidate {
  title: string;
  description?: string;
  /** Validated by the policy; capture JSON is untrusted input. */
  kind: string;
  body: string;
  /** A verbatim quote from a user message in the task. */
  evidence: string;
  expiresInDays?: number;
}

export interface MemoryWritePolicyInput {
  candidate: MemoryCandidate;
  /** `role=user` messages of the task the write belongs to. */
  userTexts: readonly string[];
  existing: MemoryRecord | undefined;
  count: number;
  now: Date;
  /** 0 for a user task; delegated sessions cannot write. */
  depth?: number;
}

export interface UserMemoryEdit {
  title: string;
  body: string;
  kind: MemoryKind;
  expiresAt: string | null;
}

export interface MemoryPolicyAccept {
  ok: true;
  slug: string;
  expiresAt: string | null;
}

export interface MemoryPolicyReject {
  ok: false;
  reason: string;
  message: string;
}

export type MemoryPolicyResult = MemoryPolicyAccept | MemoryPolicyReject;

export interface MemoryWriteResult {
  ok: boolean;
  memory?: MemoryRecord;
  reason?: string;
  message?: string;
}

export interface MemoryUserChange {
  action: 'update' | 'delete';
  slug: string;
  title: string;
  body: string | null;
}
