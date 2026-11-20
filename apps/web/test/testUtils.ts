import type { BotSummary, TimelinePage } from '@chives/server/protocol';

export function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body
  } as Response;
}

export function makeBot(overrides: Partial<BotSummary> = {}): BotSummary {
  return {
    id: 'expert',
    name: '投资专家',
    role: '默认入口 · 会把任务分给合适的同事',
    avatar: { emblem: 'crown', tone: 'gold' },
    skills: [],
    mcp: [],
    model: 'default',
    canDelegateTo: [],
    background: false,
    status: 'idle',
    runningTaskId: null,
    pendingApprovals: 0,
    panels: [],
    ...overrides
  };
}

export function emptyTimeline(): TimelinePage {
  return { messages: [], tasks: [], toolEvents: [], hasMore: false, nextBeforeSeq: null };
}

type Listener = (event: MessageEvent<string>) => void;

export class MockEventSource {
  static instances: MockEventSource[] = [];

  readonly url: string;
  readonly listeners = new Map<string, Listener[]>();
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: Listener): void {
    const list = this.listeners.get(type) ?? [];
    list.push(listener);
    this.listeners.set(type, list);
  }

  close(): void {
    this.closed = true;
  }

  open(): void {
    this.onopen?.(new Event('open'));
  }

  emit(type: string, payload: unknown): void {
    const data = JSON.stringify(payload);
    const event = { data, lastEventId: String((payload as { id?: number }).id ?? '') } as MessageEvent<string>;
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }

  fail(): void {
    this.onerror?.(new Event('error'));
  }
}

export function resetEventSources(): void {
  MockEventSource.instances = [];
}
