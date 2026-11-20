import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ServerEvent } from '@chives/server/protocol';
import { useEventStream } from '../src/hooks/useEventStream';
import { MockEventSource } from './testUtils';

const factory = (url: string): MockEventSource => new MockEventSource(url);

function Probe({ onEvent }: { onEvent: (event: ServerEvent) => void }) {
  const status = useEventStream(onEvent, { factory, retryBaseMs: 1000, retryMaxMs: 5000 });
  return <span data-testid="status">{status}</span>;
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('useEventStream', () => {
  it('opens one connection, dispatches events and reconnects with the last id', () => {
    vi.useFakeTimers();
    const onEvent = vi.fn();
    render(<Probe onEvent={onEvent} />);

    expect(MockEventSource.instances).toHaveLength(1);
    const first = MockEventSource.instances[0];
    expect(first?.url).toBe('/api/events');

    act(() => {
      first?.open();
    });
    expect(screen.getByTestId('status').textContent).toBe('open');

    act(() => {
      first?.emit('bot.status', {
        type: 'bot.status',
        id: 7,
        at: '2026-11-16T10:00:00.000Z',
        botId: 'expert',
        status: 'working',
        runningTaskId: 't1'
      });
    });
    expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({ id: 7, type: 'bot.status' }));

    act(() => {
      first?.fail();
    });
    expect(screen.getByTestId('status').textContent).toBe('reconnecting');

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(MockEventSource.instances).toHaveLength(2);
    expect(MockEventSource.instances[1]?.url).toBe('/api/events?since=7');
  });
});
