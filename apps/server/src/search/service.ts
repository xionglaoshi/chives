/** Bot-timeline search: query terms, task grouping, snippets, and tool payloads. */

import type { BotRegistry } from '../bots/index.js';
import type {
  SearchRange,
  SearchResponse,
  SearchSnippet,
  SearchTaskGroup,
} from '../api/protocol.js';
import { toDeliverableDto, toTaskSummaryDto } from '../api/dto.js';
import type { SessionIdentity } from '../delegations/tokens.js';
import { AppError } from '../errors.js';
import type {
  DeliverableRecord,
  SearchDocumentRecord,
  Store,
  TaskRecord,
  TaskSummaryRecord,
} from '../store/index.js';
import { resolveRootTask } from '../store/index.js';

export const SNIPPET_CONTEXT_CHARS = 40;
export const MAX_SNIPPETS_PER_GROUP = 5;
export const DEFAULT_GROUP_LIMIT = 20;
export const MAX_GROUP_LIMIT = 50;
export const DEFAULT_TOOL_LIMIT = 5;
export const MAX_TOOL_LIMIT = 10;
export const MAX_TOOL_RESULT_CHARS = 8_000;
export const MAX_TASK_RESULT_CHARS = 12_000;

export function tokenizeQuery(query: string): string[] {
  const seen = new Set<string>();
  const tokens: string[] = [];
  for (const raw of query.split(/\s+/u)) {
    const token = raw.trim();
    if (token === '' || seen.has(token)) continue;
    seen.add(token);
    tokens.push(token);
  }
  return tokens;
}

interface Occurrence {
  start: number;
  end: number;
}

/** All case-insensitive occurrences of every term, sorted by start offset. */
export function findOccurrences(body: string, terms: readonly string[]): Occurrence[] {
  const haystack = body.toLowerCase();
  const found: Occurrence[] = [];
  for (const term of terms) {
    const needle = term.toLowerCase();
    if (needle === '') continue;
    let from = 0;
    while (from <= haystack.length) {
      const at = haystack.indexOf(needle, from);
      if (at < 0) break;
      found.push({ start: at, end: at + needle.length });
      from = at + Math.max(1, needle.length);
    }
  }
  found.sort((left, right) => left.start - right.start || left.end - right.end);
  return found;
}

function mergeRanges(ranges: readonly SearchRange[]): SearchRange[] {
  const sorted = [...ranges].sort((left, right) => left.start - right.start || left.end - right.end);
  const merged: SearchRange[] = [];
  for (const range of sorted) {
    const last = merged[merged.length - 1];
    if (last !== undefined && range.start <= last.end) {
      last.end = Math.max(last.end, range.end);
    } else {
      merged.push({ ...range });
    }
  }
  return merged;
}

function snippetFor(body: string, occurrence: Occurrence, all: readonly Occurrence[]): SearchSnippetBase {
  const start = Math.max(0, occurrence.start - SNIPPET_CONTEXT_CHARS);
  const end = Math.min(body.length, occurrence.end + SNIPPET_CONTEXT_CHARS);
  const text = body.slice(start, end);
  const ranges = mergeRanges(
    all
      .filter((entry) => entry.start < end && entry.end > start)
      .map((entry) => ({
        start: Math.max(entry.start, start) - start,
        end: Math.min(entry.end, end) - start,
      })),
  );
  return { text, ranges };
}

interface SearchSnippetBase {
  text: string;
  ranges: SearchRange[];
}

export interface SearchServiceOptions {
  store: Store;
  registry: BotRegistry;
}

interface GroupState {
  task: TaskRecord;
  taskIds: string[];
  documents: SearchDocumentRecord[];
  hitCount: number;
}

export class SearchService {
  private readonly store: Store;
  private readonly registry: BotRegistry;

  constructor(options: SearchServiceOptions) {
    this.store = options.store;
    this.registry = options.registry;
  }

  /** Search only messages a user can actually open on a registered bot's timeline. */
  conversationMessages(raw: string, offset: number) {
    const query = raw.trim();
    if (!query || query.length > 120 || !Number.isSafeInteger(offset) || offset < 0)
      throw new AppError(400, 'invalid_search', '请输入 1 至 120 个字符的关键词');
    const indexed = [...query].length >= 3;
    const match = indexed ? `AND (m.task_id IS NULL OR m.id IN
      (SELECT d.ref_id FROM search_fts JOIN search_documents d ON d.id=search_fts.rowid
       WHERE search_fts MATCH ? AND d.doc_type='message'))` : '';
    const ids = this.registry.list().map(bot => bot.id);
    const rows = this.store.db.prepare(`
      WITH hits AS (
        SELECT m.id AS messageId,m.bot_id AS botId,m.created_at AS createdAt,m.content AS body,
               instr(lower(m.content),lower(?)) AS pos
        FROM messages m LEFT JOIN tasks t ON t.id=m.task_id
        WHERE m.role IN ('user','bot') AND m.kind IN ('text','proactive')
          AND (m.task_id IS NULL OR t.delegated=0) AND m.bot_id IN (SELECT value FROM json_each(?)) ${match}
      )
      SELECT messageId,botId,createdAt,substr(body,max(1,pos-24),24+length(?)+52) AS snippet
      FROM hits WHERE pos>0 ORDER BY createdAt DESC,messageId DESC LIMIT 26 OFFSET ?
    `).all(query,JSON.stringify(ids),...(indexed ? ['"'+query.replaceAll('"','""')+'"'] : []),query,offset);
    return {hits: rows.slice(0,25), more: rows.length > 25};
  }

  /** Used by `GET /api/bots/:id/search`. */
  search(botId: string, query: string, limit = DEFAULT_GROUP_LIMIT): SearchResponse {
    const tokens = tokenizeQuery(query);
    if (tokens.length === 0) {
      return { query, groups: [], totalGroups: 0, totalHits: 0 };
    }
    const clamped = Math.max(1, Math.min(Math.floor(limit), MAX_GROUP_LIMIT));
    const documents = this.matchingDocuments(botId, tokens);
    const groups = this.groupDocuments(documents, tokens);
    const totalHits = groups.reduce((sum, group) => sum + group.hitCount, 0);
    return {
      query,
      groups: groups.slice(0, clamped),
      totalGroups: groups.length,
      totalHits,
    };
  }

  /** Used by the internal `timeline_search` tool; always scoped to the caller's root bot. */
  searchForTool(
    identity: SessionIdentity,
    input: { query: string; limit?: number; taskId?: string },
  ): unknown {
    const root = this.rootOfIdentity(identity);
    if (root === undefined) {
      throw new AppError(404, 'task_not_found', '当前会话绑定的任务不存在');
    }
    const query = input.query.trim();
    if (query === '') {
      throw new AppError(400, 'validation_error', 'query must be a non-empty string');
    }
    if (input.taskId !== undefined) {
      return this.taskDetailForTool(root, input.taskId);
    }
    const limit = Math.max(
      1,
      Math.min(Math.floor(input.limit ?? DEFAULT_TOOL_LIMIT), MAX_TOOL_LIMIT),
    );
    const result = this.search(root.botId, query, limit);
    const payload: {
      groups: Array<{
        task_id: string;
        date: string;
        title: string;
        conclusion: string;
        key_numbers: Array<{ label: string; value: string; source: string; as_of: string }>;
        open_questions: string[];
        snippets: string[];
        hit_count: number;
      }>;
      truncated: boolean;
    } = {
      groups: result.groups.map((group) => ({
        task_id: group.taskId,
        date: group.lastActivityAt.slice(0, 10),
        title: group.title,
        conclusion: group.summary?.conclusion ?? '',
        key_numbers: (group.summary?.keyNumbers ?? []).map((entry) => ({
          label: entry.label,
          value: entry.value,
          source: entry.source,
          as_of: entry.asOf,
        })),
        open_questions: [...(group.summary?.openQuestions ?? [])],
        snippets: group.snippets.map((snippet) => snippet.text),
        hit_count: group.hitCount,
      })),
      truncated: false,
    };
    return this.fitPayload(payload, MAX_TOOL_RESULT_CHARS);
  }

  private taskDetailForTool(root: TaskRecord, taskId: string): unknown {
    const task = this.store.tasks.get(taskId);
    if (task === undefined) {
      throw new AppError(404, 'task_not_found', `unknown task "${taskId}"`);
    }
    if (resolveRootTask(this.store.db, taskId)?.id !== root.id) {
      throw new AppError(403, 'forbidden', 'this task is not in the caller timeline');
    }
    const summary = this.store.summaries.get(taskId);
    // A root task's timeline includes its delegated children's final answers;
    // asking for a child task directly stays scoped to that child.
    const detailTaskIds = task.delegated ? [task.id] : this.taskTree(task.id);
    const messages = detailTaskIds
      .flatMap((id) => this.store.messages.listByTask(id))
      .filter(
        (message) =>
          (message.role === 'user' || message.role === 'bot') &&
          (message.kind === 'text' || message.kind === 'proactive'),
      )
      .sort((left, right) => left.createdAt.localeCompare(right.createdAt) || left.seq - right.seq)
      .map((message) => ({
        at: message.createdAt,
        role: message.role,
        text: message.content,
      }));
    const payload = {
      task: {
        task_id: task.id,
        date: (summary?.createdAt ?? task.endedAt ?? task.startedAt).slice(0, 10),
        title: summary?.title ?? task.title ?? '未命名任务',
        conclusion: summary?.conclusion ?? '',
        key_numbers: (summary?.keyNumbers ?? []).map((entry) => ({
          label: entry.label,
          value: entry.value,
          source: entry.source,
          as_of: entry.asOf,
        })),
        open_questions: [...(summary?.openQuestions ?? [])],
      },
      messages,
      truncated: false,
    };
    return this.fitPayload(payload, MAX_TASK_RESULT_CHARS);
  }

  private rootOfIdentity(identity: SessionIdentity): TaskRecord | undefined {
    const root = resolveRootTask(this.store.db, identity.taskId);
    return root === undefined ? undefined : this.store.tasks.get(root.id);
  }

  private matchingDocuments(botId: string, terms: readonly string[]): SearchDocumentRecord[] {
    let matched: Set<number> | null = null;
    for (const term of terms) {
      const ids = new Set(this.store.search.matchIds(botId, term));
      if (matched === null) {
        matched = ids;
      } else {
        for (const id of [...matched]) {
          if (!ids.has(id)) matched.delete(id);
        }
      }
      if (matched.size === 0) return [];
    }
    if (matched === null) return [];
    return this.store.search.byIds([...matched]);
  }

  private groupDocuments(
    documents: readonly SearchDocumentRecord[],
    terms: readonly string[],
  ): SearchTaskGroup[] {
    const states = new Map<string, GroupState>();
    for (const document of documents) {
      const task = this.store.tasks.get(document.taskId);
      if (task === undefined) continue;
      const existing = states.get(task.id);
      if (existing !== undefined) {
        existing.documents.push(document);
      } else {
        states.set(task.id, {
          task,
          taskIds: this.taskTree(task.id),
          documents: [document],
          hitCount: 0,
        });
      }
    }

    const groups: SearchTaskGroup[] = [];
    for (const state of states.values()) {
      const summary = this.groupSummary(state.task.id, state.taskIds);
      const documents = [...state.documents].sort((left, right) =>
        left.createdAt.localeCompare(right.createdAt),
      );
      let hitCount = 0;
      const snippets: SearchSnippet[] = [];
      for (const document of documents) {
        const occurrences = findOccurrences(document.body, terms);
        hitCount += occurrences.length;
        for (const occurrence of occurrences) {
          if (snippets.length >= MAX_SNIPPETS_PER_GROUP) continue;
          const base = snippetFor(document.body, occurrence, occurrences);
          snippets.push({
            docType: document.docType,
            sourceId: document.refId,
            messageId: document.docType === 'message' ? document.refId : null,
            deliverableId: document.docType === 'deliverable' ? document.refId : null,
            text: base.text,
            ranges: base.ranges,
            createdAt: document.createdAt,
          });
        }
      }
      const deliverables = this.groupDeliverables(state.taskIds);
      const lastActivityAt = [
        state.task.endedAt ?? state.task.startedAt,
        summary?.createdAt ?? '',
        ...documents.map((document) => document.createdAt),
        ...deliverables.map((deliverable) => deliverable.createdAt),
      ].reduce((latest, value) => (value > latest ? value : latest), state.task.startedAt);
      groups.push({
        taskId: state.task.id,
        botId: state.task.botId,
        botName: this.registry.get(state.task.botId)?.name ?? state.task.botId,
        title: summary?.title ?? state.task.title ?? '未命名任务',
        lastActivityAt,
        startedAt: state.task.startedAt,
        endedAt: state.task.endedAt,
        steps: state.taskIds.reduce(
          (sum, taskId) => sum + this.store.toolEvents.listByTask(taskId).length,
          0,
        ),
        summary: summary === undefined ? null : toTaskSummaryDto(summary),
        snippets,
        hitCount,
        deliverables: deliverables.map(toDeliverableDto),
        taskIds: state.taskIds,
        locateMessageId: this.firstMessageId(state.taskIds),
      });
    }
    groups.sort((left, right) => right.lastActivityAt.localeCompare(left.lastActivityAt));
    return groups;
  }

  private groupSummary(taskId: string, taskIds: readonly string[]): TaskSummaryRecord | undefined {
    const own = this.store.summaries.get(taskId);
    if (own !== undefined) return own;
    let latest: TaskSummaryRecord | undefined;
    for (const id of taskIds) {
      if (id === taskId) continue;
      const summary = this.store.summaries.get(id);
      if (summary === undefined) continue;
      if (latest === undefined || summary.createdAt > latest.createdAt) latest = summary;
    }
    return latest;
  }

  private groupDeliverables(taskIds: readonly string[]): DeliverableRecord[] {
    const byId = new Map<string, DeliverableRecord>();
    for (const taskId of taskIds) {
      for (const record of this.store.deliverables.listByTask(taskId)) byId.set(record.id, record);
    }
    return [...byId.values()].sort((left, right) =>
      right.createdAt.localeCompare(left.createdAt),
    );
  }

  private taskTree(rootId: string): string[] {
    const ids: string[] = [];
    const queue = [rootId];
    const seen = new Set<string>();
    while (queue.length > 0) {
      const id = queue.shift();
      if (id === undefined || seen.has(id)) continue;
      seen.add(id);
      ids.push(id);
      for (const child of this.store.tasks.listByParent(id)) queue.push(child.id);
    }
    return ids;
  }

  private firstMessageId(taskIds: readonly string[]): string | null {
    for (const taskId of taskIds) {
      const messages = this.store.messages.listByTask(taskId);
      const first = messages.find(
        (message) =>
          (message.role === 'user' || message.role === 'bot') &&
          (message.kind === 'text' || message.kind === 'proactive'),
      );
      if (first !== undefined) return first.id;
    }
    return null;
  }

  /** Keeps the JSON serialization of `payload` at or below `limit` characters. */
  private fitPayload<T>(payload: T, limit: number): T {
    interface MutableGroup {
      title?: string;
      snippets: string[];
      conclusion?: string;
      key_numbers?: unknown[];
      open_questions?: string[];
    }
    interface MutableTask {
      title?: string;
      conclusion?: string;
      key_numbers?: unknown[];
      open_questions?: string[];
    }
    const mutable = payload as unknown as {
      groups?: MutableGroup[];
      task?: MutableTask;
      messages?: Array<{ text: string }>;
      truncated?: boolean;
    };
    const size = (): number => JSON.stringify(mutable).length;
    if (size() <= limit) return payload;
    mutable.truncated = true;
    let iterations = 0;
    while (size() > limit) {
      iterations += 1;
      if (iterations > 10_000) throw new Error('fitPayload did not converge');
      const groups = mutable.groups;
      const lastGroup = groups?.[groups.length - 1];
      if (lastGroup !== undefined) {
        if (lastGroup.snippets.length > 0) {
          lastGroup.snippets.pop();
          continue;
        }
        if (lastGroup.key_numbers !== undefined && lastGroup.key_numbers.length > 0) {
          lastGroup.key_numbers.pop();
          continue;
        }
        if (lastGroup.open_questions !== undefined && lastGroup.open_questions.length > 0) {
          lastGroup.open_questions.pop();
          continue;
        }
        if (lastGroup.conclusion !== undefined && lastGroup.conclusion.length > 21) {
          lastGroup.conclusion = `${lastGroup.conclusion.slice(0, 20)}…`;
          continue;
        }
        if (lastGroup.title !== undefined && lastGroup.title.length > 21) {
          lastGroup.title = `${lastGroup.title.slice(0, 20)}…`;
          continue;
        }
        groups?.pop();
        continue;
      }
      const task = mutable.task;
      if (task !== undefined) {
        if (task.key_numbers !== undefined && task.key_numbers.length > 0) {
          task.key_numbers.pop();
          continue;
        }
        if (task.open_questions !== undefined && task.open_questions.length > 0) {
          task.open_questions.pop();
          continue;
        }
        if (task.conclusion !== undefined && task.conclusion.length > 21) {
          task.conclusion = `${task.conclusion.slice(0, 20)}…`;
          continue;
        }
        if (task.title !== undefined && task.title.length > 21) {
          task.title = `${task.title.slice(0, 20)}…`;
          continue;
        }
      }
      const messages = mutable.messages;
      const lastMessage = messages?.[messages.length - 1];
      if (lastMessage !== undefined && lastMessage.text.length > 21) {
        lastMessage.text = `${lastMessage.text.slice(0, 20)}…`;
        continue;
      }
      if (messages !== undefined && messages.length > 0) {
        messages.pop();
        continue;
      }
      break;
    }
    return payload;
  }
}
