/** Pure write rules for bot-level memory: user evidence, red lines, length, expiry. */

import { createHash } from 'node:crypto';

import {
  DEFAULT_EXPIRY_DAYS,
  MEMORY_KINDS,
  MEMORY_MAX_BODY_CHARS,
  MEMORY_MAX_DESCRIPTION_CHARS,
  MEMORY_MAX_PER_BOT,
  MEMORY_MAX_TITLE_CHARS,
  type MemoryKind,
  type MemoryPolicyResult,
  type MemoryWritePolicyInput,
  type UserMemoryEdit,
} from './types.js';

export const MAX_EVIDENCE_CHARS = 1000;

const REASON_TEXT: Readonly<Record<string, string>> = {
  forbidden_delegated: '被委派的会话只能读记忆，不能写入',
  invalid_title: `标题必须是 1-${MEMORY_MAX_TITLE_CHARS} 字`,
  invalid_description: `描述最多 ${MEMORY_MAX_DESCRIPTION_CHARS} 字`,
  invalid_kind: `kind 必须是 ${MEMORY_KINDS.join(' / ')}`,
  invalid_body: '正文不能为空',
  body_too_long: `正文最多 ${MEMORY_MAX_BODY_CHARS} 字`,
  missing_evidence: '必须带一段用户原话作为依据',
  evidence_too_long: `依据最多 ${MAX_EVIDENCE_CHARS} 字`,
  evidence_not_from_user: '依据不是本任务里用户本人说过的话，不能写入',
  sensitive_account: '候选包含账号或卡号，不能写入记忆',
  sensitive_credential: '候选包含密码、口令、验证码、token 或密钥，不能写入记忆',
  sensitive_phone: '候选包含手机号，不能写入记忆',
  sensitive_id: '候选包含身份证号，不能写入记忆',
  sensitive_capital: '候选包含精确资金，不能写入记忆',
  sensitive_position: '候选包含精确持仓，不能写入记忆',
  limit_reached: `这个 bot 的记忆已达上限 ${MEMORY_MAX_PER_BOT} 条，请先清理`,
  invalid_expiry: '到期日必须是合法的日期时间',
  not_found: '记忆不存在',
};

export function policyMessage(reason: string): string {
  return REASON_TEXT[reason] ?? '记忆写入被拒绝';
}

export function normalizeWhitespace(text: string): string {
  return text.replace(/\s+/g, ' ').trim();
}

export function isMemoryKind(value: unknown): value is MemoryKind {
  return typeof value === 'string' && (MEMORY_KINDS as readonly string[]).includes(value);
}

/** Detects the first red-line category; returns null when the text is clean. */
export function findSensitiveCategory(text: string): string | null {
  if (/(?<!\d)\d{17}[\dXx](?![\dXx])/.test(text)) return 'sensitive_id';
  if (/(?<!\d)1[3-9]\d{9}(?!\d)/.test(text)) return 'sensitive_phone';
  if (/密码|口令|验证码|token|api[\s_-]?key|secret|密钥/i.test(text)) return 'sensitive_credential';
  if (/\d{8,}/.test(text)) return 'sensitive_account';
  const capital = /资金|本金|存款|余额|现金/.test(text);
  const money = /\d[\d,]*(?:\.\d+)?\s*(?:万元|万|亿元|亿|元)/.test(text);
  if (capital && money) return 'sensitive_capital';
  const holding = /持有|持仓/.test(text);
  const shares = /\d[\d,]*(?:\.\d+)?\s*(?:股|手)/.test(text);
  if (holding && shares) return 'sensitive_position';
  return null;
}

/** Evidence must be a whitespace-normalized substring of one user message. */
export function hasUserEvidence(evidence: string, userTexts: readonly string[]): boolean {
  const needle = normalizeWhitespace(evidence);
  if (needle === '') return false;
  return userTexts.some((text) => normalizeWhitespace(text).includes(needle));
}

/** Stable ASCII slug; CJK-only titles fall back to a short content hash. */
export function memorySlug(title: string): string {
  const normalized = normalizeWhitespace(title).normalize('NFKC').toLowerCase();
  const ascii = normalized
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48);
  if (ascii.length >= 2) return ascii;
  const hash = createHash('sha256').update(normalized).digest('hex').slice(0, 12);
  return `m-${hash}`;
}

export function isValidSlug(slug: string): boolean {
  return /^[a-z0-9][a-z0-9-]{0,63}$/.test(slug);
}

export function addDays(now: Date, days: number): string {
  return new Date(now.getTime() + days * 24 * 60 * 60_000).toISOString();
}

/** `undefined` applies the kind default; an explicit value overrides it. */
export function computeExpiresAt(
  kind: MemoryKind,
  expiresInDays: number | undefined,
  now: Date,
): string | null {
  const days = expiresInDays === undefined ? DEFAULT_EXPIRY_DAYS[kind] : expiresInDays;
  return days === null ? null : addDays(now, days);
}

export function parseExpiry(value: unknown): string | null | undefined {
  if (value === null) return null;
  if (typeof value !== 'string' || value.trim() === '') return undefined;
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return undefined;
  return new Date(parsed).toISOString();
}

function codePointLength(text: string): number {
  return [...text].length;
}

/** Validates a capture/tool candidate. User edits use {@link evaluateUserEdit}. */
export function evaluateMemoryWrite(input: MemoryWritePolicyInput): MemoryPolicyResult {
  const { candidate, existing, count, now } = input;
  if ((input.depth ?? 0) > 0) {
    return { ok: false, reason: 'forbidden_delegated', message: policyMessage('forbidden_delegated') };
  }
  const title = candidate.title.trim();
  const description = (candidate.description ?? '').trim();
  const body = candidate.body.trim();
  if (title === '' || codePointLength(title) > MEMORY_MAX_TITLE_CHARS) {
    return { ok: false, reason: 'invalid_title', message: policyMessage('invalid_title') };
  }
  if (codePointLength(description) > MEMORY_MAX_DESCRIPTION_CHARS) {
    return {
      ok: false,
      reason: 'invalid_description',
      message: policyMessage('invalid_description'),
    };
  }
  if (!isMemoryKind(candidate.kind)) {
    return { ok: false, reason: 'invalid_kind', message: policyMessage('invalid_kind') };
  }
  if (body === '') {
    return { ok: false, reason: 'invalid_body', message: policyMessage('invalid_body') };
  }
  if (codePointLength(body) > MEMORY_MAX_BODY_CHARS) {
    return { ok: false, reason: 'body_too_long', message: policyMessage('body_too_long') };
  }
  if (typeof candidate.evidence !== 'string' || candidate.evidence.trim() === '') {
    return { ok: false, reason: 'missing_evidence', message: policyMessage('missing_evidence') };
  }
  if (codePointLength(candidate.evidence) > MAX_EVIDENCE_CHARS) {
    return { ok: false, reason: 'evidence_too_long', message: policyMessage('evidence_too_long') };
  }
  if (!hasUserEvidence(candidate.evidence, input.userTexts)) {
    return {
      ok: false,
      reason: 'evidence_not_from_user',
      message: policyMessage('evidence_not_from_user'),
    };
  }
  const sensitive = findSensitiveCategory(
    [title, description, body, candidate.evidence].join('\n'),
  );
  if (sensitive !== null) {
    return { ok: false, reason: sensitive, message: policyMessage(sensitive) };
  }
  if (
    candidate.expiresInDays !== undefined &&
    (!Number.isInteger(candidate.expiresInDays) ||
      candidate.expiresInDays < 0 ||
      candidate.expiresInDays > 3650)
  ) {
    return { ok: false, reason: 'invalid_expiry', message: policyMessage('invalid_expiry') };
  }
  const slug = existing?.slug ?? memorySlug(title);
  if (existing === undefined && count >= MEMORY_MAX_PER_BOT) {
    return { ok: false, reason: 'limit_reached', message: policyMessage('limit_reached') };
  }
  return {
    ok: true,
    slug,
    expiresAt: computeExpiresAt(candidate.kind, candidate.expiresInDays, now),
  };
}

/** User edits skip the evidence rule but still enforce red lines, kind, and length. */
export function evaluateUserEdit(edit: UserMemoryEdit): MemoryPolicyResult {
  const title = edit.title.trim();
  const body = edit.body.trim();
  if (title === '' || codePointLength(title) > MEMORY_MAX_TITLE_CHARS) {
    return { ok: false, reason: 'invalid_title', message: policyMessage('invalid_title') };
  }
  if (!isMemoryKind(edit.kind)) {
    return { ok: false, reason: 'invalid_kind', message: policyMessage('invalid_kind') };
  }
  if (body === '') {
    return { ok: false, reason: 'invalid_body', message: policyMessage('invalid_body') };
  }
  if (codePointLength(body) > MEMORY_MAX_BODY_CHARS) {
    return { ok: false, reason: 'body_too_long', message: policyMessage('body_too_long') };
  }
  const sensitive = findSensitiveCategory(`${title}\n${body}`);
  if (sensitive !== null) {
    return { ok: false, reason: sensitive, message: policyMessage(sensitive) };
  }
  return { ok: true, slug: '', expiresAt: edit.expiresAt };
}

export function isExpired(expiresAt: string | null, now: Date): boolean {
  if (expiresAt === null) return false;
  const parsed = Date.parse(expiresAt);
  return Number.isFinite(parsed) && parsed <= now.getTime();
}

export function dateOnly(iso: string): string {
  return iso.slice(0, 10);
}
