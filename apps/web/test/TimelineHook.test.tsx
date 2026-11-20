import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { MessageDto, TimelinePage } from '@chives/server/protocol';
import { useTimeline } from '../src/hooks/useTimeline';
import { jsonResponse } from './testUtils';

function message(id: string, seq: number, content: string): MessageDto {
  return {
    id,
    botId: 'expert',
    taskId: null,
    role: 'bot',
    kind: 'text',
    content,
    meta: null,
    createdAt: '2026-11-16T10:00:00.000Z',
    seq
  };
}

const initial: TimelinePage = {
  messages: [message('m6', 6, '最新一页')],
  tasks: [],
  toolEvents: [],
  hasMore: true,
  nextBeforeSeq: 6
};

const older: TimelinePage = {
  messages: [message('m5', 5, '更早一页')],
  tasks: [],
  toolEvents: [],
  hasMore: false,
  nextBeforeSeq: null
};

function Probe() {
  const { state, loadOlder } = useTimeline('expert');
  return (
    <div>
      <span data-testid="status">{state.status}</span>
      <span data-testid="messages">{state.messages.map((item) => item.content).join('|')}</span>
      <button type="button" onClick={loadOlder}>
        加载更早
      </button>
    </div>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('useTimeline pagination', () => {
  it('requests the page before nextBeforeSeq and prepends it', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('beforeSeq=6')) return jsonResponse(older);
      return jsonResponse(initial);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<Probe />);

    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('ready'));
    expect(screen.getByTestId('messages').textContent).toBe('最新一页');

    fireEvent.click(screen.getByRole('button', { name: '加载更早' }));
    await waitFor(() =>
      expect(screen.getByTestId('messages').textContent).toBe('更早一页|最新一页')
    );
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/bots/expert/timeline?limit=50&beforeSeq=6',
      expect.any(Object)
    );
  });
});
