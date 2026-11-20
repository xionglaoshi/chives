/** Model-backed segmentation classifier, plus a fake used by tests. */

import type { BotManifest } from '../bots/index.js';
import type { TaskSummaryRecord } from '../store/index.js';
import type { HarnessDriver, TemporaryPromptDriver } from '../harness/types.js';

export interface ClassifierMessage {
  role: 'user' | 'bot';
  content: string;
}

export interface TaskClassifier {
  classify(
    bot: BotManifest,
    previousSummary: TaskSummaryRecord | null,
    recentMessages: readonly ClassifierMessage[],
    newText: string,
  ): Promise<'continue' | 'new'>;
}

export const CLASSIFIER_TIMEOUT_MS = 15_000;

export function isTemporaryPromptDriver(driver: HarnessDriver): driver is HarnessDriver & TemporaryPromptDriver {
  return typeof (driver as Partial<TemporaryPromptDriver>).temporaryPrompt === 'function';
}

export function buildClassifierPrompt(
  previousSummary: TaskSummaryRecord | null,
  recentMessages: readonly ClassifierMessage[],
  newText: string,
): string {
  const title = previousSummary?.title ?? '（未知）';
  const conclusion = previousSummary?.conclusion ?? '（无小结）';
  const recent = recentMessages
    .slice(-2)
    .map((message) => `${message.role === 'user' ? '用户' : '助手'}：${message.content.slice(0, 500)}`)
    .join('\n');
  return [
    '你是任务分段判断器。判断用户的新消息是延续上一个任务，还是开始一个新任务。',
    `上一任务标题：${title}`,
    `上一任务结论：${conclusion}`,
    '最近消息：',
    recent === '' ? '（无）' : recent,
    `用户的新消息：${newText}`,
    '',
    '只回答一个词：continue 或 new。',
  ].join('\n');
}

/**
 * Creates a temporary session in the bot's own harness process, asks one
 * question, and closes it. Events go to a private sink and never reach the
 * timeline or the SSE stream.
 */
export class DshTaskClassifier implements TaskClassifier {
  constructor(
    private readonly host: HarnessDriver & TemporaryPromptDriver,
    private readonly timeoutMs: number = CLASSIFIER_TIMEOUT_MS,
  ) {}

  async classify(
    bot: BotManifest,
    previousSummary: TaskSummaryRecord | null,
    recentMessages: readonly ClassifierMessage[],
    newText: string,
  ): Promise<'continue' | 'new'> {
    const reply = await this.host.temporaryPrompt(
      bot,
      buildClassifierPrompt(previousSummary, recentMessages, newText),
      { timeoutMs: this.timeoutMs, config: { reasoning_effort: 'low' } },
    );
    if (reply === null) throw new Error('classifier_timeout');
    const match = /\b(continue|new)\b/i.exec(reply);
    if (match === null || match[1] === undefined) throw new Error('classifier_parse_failed');
    return match[1].toLowerCase() === 'new' ? 'new' : 'continue';
  }
}

export class FakeTaskClassifier implements TaskClassifier {
  private index = 0;

  constructor(
    private readonly answers: readonly ('continue' | 'new')[] = ['continue'],
    private readonly fail = false,
  ) {}

  classify(): Promise<'continue' | 'new'> {
    if (this.fail) return Promise.reject(new Error('fake classifier failure'));
    const answer = this.answers[this.index] ?? this.answers[this.answers.length - 1] ?? 'continue';
    this.index += 1;
    return Promise.resolve(answer);
  }
}
