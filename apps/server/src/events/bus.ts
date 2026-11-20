/** In-process fan-out for SSE clients with a bounded replay buffer. */

import type { ServerEvent } from '../api/protocol.js';

export const DEFAULT_BUFFER_SIZE = 2000;

type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;

/** An event before the bus assigns its global id and timestamp. */
export type EventInput = DistributiveOmit<ServerEvent, 'id' | 'at'> & { at?: string };

export type EventListener = (event: ServerEvent) => void;

export class EventBus {
  private readonly capacity: number;
  private readonly buffer: ServerEvent[] = [];
  private readonly listeners = new Set<EventListener>();
  private nextId = 1;
  private now: () => Date;

  constructor(options: { capacity?: number; now?: () => Date } = {}) {
    this.capacity = options.capacity ?? DEFAULT_BUFFER_SIZE;
    if (!Number.isInteger(this.capacity) || this.capacity < 1) {
      throw new Error('EventBus capacity must be a positive integer');
    }
    this.now = options.now ?? (() => new Date());
  }

  get lastId(): number {
    return this.nextId - 1;
  }

  get oldestBufferedId(): number | undefined {
    return this.buffer[0]?.id;
  }

  publish(input: EventInput): ServerEvent {
    const event = {
      ...input,
      id: this.nextId,
      at: input.at ?? this.now().toISOString(),
    } as ServerEvent;
    this.nextId += 1;
    this.buffer.push(event);
    while (this.buffer.length > this.capacity) this.buffer.shift();
    for (const listener of [...this.listeners]) {
      try {
        listener(event);
      } catch {
        // A broken SSE client must not affect other subscribers or the caller.
      }
    }
    return event;
  }

  subscribe(listener: EventListener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  /** Events with `id > sinceId`, oldest first, limited to the ring buffer. */
  replay(sinceId: number): ServerEvent[] {
    return this.buffer.filter((event) => event.id > sinceId);
  }
}
