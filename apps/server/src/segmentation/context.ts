/** Fixed-shape context block prepended to the first prompt of a new task. */

export interface ContextRecentMessage {
  role: 'user' | 'bot';
  content: string;
  createdAt: string;
  taskTitle: string | null;
}

export interface ContextTaskLine {
  taskId: string;
  /** `YYYY-MM-DD` of the close time. */
  date: string;
  title: string;
  conclusion: string;
}

export interface ContextInjectionInput {
  userText: string;
  recentMessages: readonly ContextRecentMessage[];
  tasks: readonly ContextTaskLine[];
  /** T134 fills this; an empty value omits the whole section. */
  memory?: string;
  /** Audit cursor captured with the injection, stored on the task. */
  memoryAuditCursor?: number;
  maxChars?: number;
}

export interface ContextInjectionMeta {
  injectedChars: number;
  recentMessages: number;
  directoryEntries: number;
  memoryIncluded: boolean;
  memoryAuditCursor?: number;
}

export interface ContextInjection {
  text: string;
  meta: ContextInjectionMeta;
}

export const MAX_INJECTION_CHARS = 8000;
export const MAX_RECENT_MESSAGES = 6;
export const MAX_TASK_LINES = 20;
export const MAX_RECENT_MESSAGE_CHARS = 1200;
export const MAX_CONCLUSION_CHARS = 60;

const HEADER =
  '[Chives 上下文：以下是你之前和用户的工作记录，供参考；与当前问题无关的忽略即可]';
const FOOTER = '需要某个旧任务的细节时，调用 timeline_search。';

function oneLine(text: string): string {
  return text.replace(/\s+/g, ' ').trim();
}

function truncate(text: string, limit: number): string {
  if (text.length <= limit) return text;
  return `${text.slice(0, Math.max(0, limit - 1))}…`;
}

function timeLabel(iso: string): string {
  const parsed = Date.parse(iso);
  if (!Number.isFinite(parsed)) return iso;
  return iso.slice(0, 16).replace('T', ' ');
}

function render(
  input: ContextInjectionInput,
  recentMessages: readonly ContextRecentMessage[],
  tasks: readonly ContextTaskLine[],
  userText: string,
): string {
  const lines: string[] = [HEADER];

  const memory = input.memory?.trim() ?? '';
  if (memory !== '') {
    lines.push('## 你记得的', memory);
  }

  lines.push('## 最近的对话原文');
  if (recentMessages.length === 0) {
    lines.push('（无）');
  } else {
    for (const message of recentMessages) {
      const title = message.taskTitle ?? '未命名任务';
      const content = truncate(oneLine(message.content), MAX_RECENT_MESSAGE_CHARS);
      const role = message.role === 'user' ? '用户' : '助手';
      lines.push(`- ${timeLabel(message.createdAt)} · 任务「${title}」· ${role}：${content}`);
    }
  }

  lines.push('## 之前的任务目录');
  if (tasks.length === 0) {
    lines.push('（无）');
  } else {
    for (const task of tasks) {
      lines.push(
        `${task.date} · ${task.title} · ${truncate(oneLine(task.conclusion), MAX_CONCLUSION_CHARS)} · task:${task.taskId}`,
      );
    }
  }

  lines.push(FOOTER, '[用户的新消息]', userText);
  return lines.join('\n');
}

/**
 * Builds the injection block. The 8000-character cap first drops directory
 * lines from the tail, then shortens the user's original text.
 */
export function buildContextInjection(input: ContextInjectionInput): ContextInjection {
  const maxChars = input.maxChars ?? MAX_INJECTION_CHARS;
  const recentMessages = input.recentMessages.slice(-MAX_RECENT_MESSAGES);
  let tasks = input.tasks.slice(0, MAX_TASK_LINES);
  let userText = input.userText;

  let text = render(input, recentMessages, tasks, userText);
  while (text.length > maxChars && tasks.length > 0) {
    tasks = tasks.slice(0, -1);
    text = render(input, recentMessages, tasks, userText);
  }

  if (text.length > maxChars) {
    const fixed = render(input, recentMessages, tasks, '').length;
    const budget = maxChars - fixed;
    if (budget <= 0) {
      text = text.slice(0, maxChars);
    } else if (userText.length > budget) {
      userText = `${userText.slice(0, Math.max(0, budget - 1))}…`;
      text = render(input, recentMessages, tasks, userText);
    }
  }

  return {
    text,
    meta: {
      injectedChars: text.length,
      recentMessages: recentMessages.length,
      directoryEntries: tasks.length,
      memoryIncluded: (input.memory?.trim() ?? '') !== '',
      ...(input.memoryAuditCursor === undefined
        ? {}
        : { memoryAuditCursor: input.memoryAuditCursor }),
    },
  };
}

export const buildInjectionBlock = buildContextInjection;
