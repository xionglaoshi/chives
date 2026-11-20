/** Pure draft state machine fed by side-channel streaming frames. */

export type StreamFrameType = 'start' | 'end' | 'text-delta' | 'reasoning-delta';

export interface StreamFrame {
  session: string;
  t: StreamFrameType;
  attemptId?: string;
  outcome?: unknown;
  i?: number;
  text?: string;
}

export type DraftEvent =
  | { type: 'draft_reset'; sessionId: string; attemptId?: string }
  | { type: 'draft_delta'; sessionId: string; attemptId?: string; kind: 'text' | 'reasoning'; text: string }
  | { type: 'draft_commit'; sessionId: string; text: string };

export interface DraftSnapshot {
  attemptId: string | undefined;
  text: string;
  reasoning: string;
  ended: boolean;
}

interface DraftState {
  attemptId: string | undefined;
  text: string;
  reasoning: string;
  ended: boolean;
}

/**
 * Keeps one live draft per session. A new `start` discards the previous
 * uncommitted draft; `handleCommitted` always wins over accumulated deltas.
 */
export class DraftTracker {
  private readonly drafts = new Map<string, DraftState>();

  constructor(private readonly emit: (event: DraftEvent) => void) {}

  handleFrame(frame: StreamFrame): void {
    switch (frame.t) {
      case 'start': {
        this.emit({
          type: 'draft_reset',
          sessionId: frame.session,
          ...(frame.attemptId === undefined ? {} : { attemptId: frame.attemptId }),
        });
        this.drafts.set(frame.session, {
          attemptId: frame.attemptId,
          text: '',
          reasoning: '',
          ended: false,
        });
        return;
      }
      case 'text-delta':
      case 'reasoning-delta': {
        const state = this.drafts.get(frame.session) ?? {
          attemptId: frame.attemptId,
          text: '',
          reasoning: '',
          ended: false,
        };
        this.drafts.set(frame.session, state);
        if (
          frame.attemptId !== undefined
          && state.attemptId !== undefined
          && frame.attemptId !== state.attemptId
        ) {
          return;
        }
        const text = frame.text ?? '';
        if (frame.t === 'text-delta') state.text += text;
        else state.reasoning += text;
        this.emit({
          type: 'draft_delta',
          sessionId: frame.session,
          kind: frame.t === 'text-delta' ? 'text' : 'reasoning',
          text,
          ...(frame.attemptId === undefined ? {} : { attemptId: frame.attemptId }),
        });
        return;
      }
      case 'end': {
        const state = this.drafts.get(frame.session);
        if (state !== undefined) state.ended = true;
        return;
      }
      default:
        return;
    }
  }

  /** Replace the draft with the committed ACP message and clear it. */
  handleCommitted(sessionId: string, text: string): void {
    this.emit({ type: 'draft_commit', sessionId, text });
    this.drafts.delete(sessionId);
  }

  snapshot(sessionId: string): DraftSnapshot | undefined {
    const state = this.drafts.get(sessionId);
    if (state === undefined) return undefined;
    return {
      attemptId: state.attemptId,
      text: state.text,
      reasoning: state.reasoning,
      ended: state.ended,
    };
  }

  clear(sessionId: string): void {
    this.drafts.delete(sessionId);
  }
}
