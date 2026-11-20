/** Normalizes ACP `session/update` payloads into a discriminated event union. */

import type { SessionUpdate, SessionConfigOption } from './types.js';

export interface AcpMessageEvent {
  type: 'message';
  sessionId: string;
  text: string;
  messageId?: string;
}

export interface AcpThoughtEvent {
  type: 'thought';
  sessionId: string;
  text: string;
  messageId?: string;
}

export interface AcpToolStartEvent {
  type: 'tool_start';
  sessionId: string;
  toolCallId: string;
  title: string | undefined;
  kind: string | undefined;
  rawInput: unknown;
}

export interface AcpToolEndEvent {
  type: 'tool_end';
  sessionId: string;
  toolCallId: string;
  status: 'completed' | 'failed';
  output: string;
  title: string | undefined;
  kind: string | undefined;
}

export interface AcpUsageEvent {
  type: 'usage';
  sessionId: string;
  used: number;
  size: number;
}

export interface AcpConfigEvent {
  type: 'config';
  sessionId: string;
  configOptions: readonly SessionConfigOption[];
}

export interface AcpUnknownEvent {
  type: 'unknown';
  sessionId: string;
  update: SessionUpdate;
}

export type AcpEvent =
  | AcpMessageEvent
  | AcpThoughtEvent
  | AcpToolStartEvent
  | AcpToolEndEvent
  | AcpUsageEvent
  | AcpConfigEvent
  | AcpUnknownEvent;

export interface ToolCallSnapshot {
  toolCallId: string;
  title: string | undefined;
  kind: string | undefined;
  rawInput: unknown;
}

interface ToolState extends ToolCallSnapshot {
  ended: boolean;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function optionalString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

function textOfContent(content: unknown): string | undefined {
  if (isRecord(content) && content.type === 'text' && typeof content.text === 'string') {
    return content.text;
  }
  if (Array.isArray(content)) {
    const parts: string[] = [];
    for (const block of content) {
      const text = textOfContent(block);
      if (text !== undefined) parts.push(text);
    }
    return parts.length === 0 ? undefined : parts.join('');
  }
  return undefined;
}

function toolOutput(content: unknown): string {
  if (!Array.isArray(content)) return '';
  const parts: string[] = [];
  for (const block of content) {
    if (!isRecord(block)) continue;
    const value = block.type === 'content' ? textOfContent(block.content) : textOfContent(block);
    if (value !== undefined) parts.push(value);
  }
  return parts.join('');
}

/**
 * Stateful normalizer for one connection. Tool call updates are merged by
 * `toolCallId`; only the first terminal update produces `tool_end`.
 */
export class EventNormalizer {
  private readonly tools = new Map<string, ToolState>();

  toolCall(toolCallId: string): ToolCallSnapshot | undefined {
    const state = this.tools.get(toolCallId);
    if (state === undefined) return undefined;
    return {
      toolCallId: state.toolCallId,
      title: state.title,
      kind: state.kind,
      rawInput: state.rawInput,
    };
  }

  normalize(sessionId: string, update: SessionUpdate): AcpEvent | undefined {
    switch (update.sessionUpdate) {
      case 'agent_message_chunk': {
        const text = textOfContent(update.content);
        if (text === undefined) return this.unknown(sessionId, update);
        return {
          type: 'message',
          sessionId,
          text,
          ...(typeof update.messageId === 'string' ? { messageId: update.messageId } : {}),
        };
      }
      case 'agent_thought_chunk': {
        const text = textOfContent(update.content);
        if (text === undefined) return this.unknown(sessionId, update);
        return {
          type: 'thought',
          sessionId,
          text,
          ...(typeof update.messageId === 'string' ? { messageId: update.messageId } : {}),
        };
      }
      case 'tool_call': {
        const toolCallId = optionalString(update.toolCallId);
        if (toolCallId === undefined) return this.unknown(sessionId, update);
        const state: ToolState = {
          toolCallId,
          title: optionalString(update.title),
          kind: optionalString(update.kind),
          rawInput: update.rawInput,
          ended: false,
        };
        this.tools.set(toolCallId, state);
        return {
          type: 'tool_start',
          sessionId,
          toolCallId,
          title: state.title,
          kind: state.kind,
          rawInput: state.rawInput,
        };
      }
      case 'tool_call_update': {
        const toolCallId = optionalString(update.toolCallId);
        if (toolCallId === undefined) return this.unknown(sessionId, update);
        const existing = this.tools.get(toolCallId);
        const state: ToolState = existing ?? {
          toolCallId,
          title: undefined,
          kind: undefined,
          rawInput: undefined,
          ended: false,
        };
        if (!existing) this.tools.set(toolCallId, state);
        if (optionalString(update.title) !== undefined) state.title = optionalString(update.title);
        if (optionalString(update.kind) !== undefined) state.kind = optionalString(update.kind);
        if (update.rawInput !== undefined) state.rawInput = update.rawInput;
        const status = update.status;
        if (status !== 'completed' && status !== 'failed') return undefined;
        if (state.ended) return undefined;
        state.ended = true;
        return {
          type: 'tool_end',
          sessionId,
          toolCallId,
          status,
          output: toolOutput(update.content),
          title: state.title,
          kind: state.kind,
        };
      }
      case 'usage_update': {
        if (typeof update.used !== 'number' || typeof update.size !== 'number') {
          return this.unknown(sessionId, update);
        }
        return { type: 'usage', sessionId, used: update.used, size: update.size };
      }
      case 'config_option_update': {
        if (!Array.isArray(update.configOptions)) return this.unknown(sessionId, update);
        return {
          type: 'config',
          sessionId,
          configOptions: update.configOptions as SessionConfigOption[],
        };
      }
      default:
        return this.unknown(sessionId, update);
    }
  }

  private unknown(sessionId: string, update: SessionUpdate): AcpUnknownEvent {
    return { type: 'unknown', sessionId, update };
  }
}
