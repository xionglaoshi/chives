import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ServiceBanner } from '../src/components/ServiceBanner';

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('ServiceBanner', () => {
  it('explains an unreachable server and counts down to the automatic retry', () => {
    vi.useFakeTimers();
    const onRetry = vi.fn();
    render(
      <ServiceBanner
        serverError="fetch failed"
        eventStatus="open"
        onRetry={onRetry}
        retrySeconds={3}
      />
    );

    expect(screen.getByText(/连不上 Chives 服务，3 秒后自动重试/)).toBeTruthy();
    expect(screen.getByText(/已加载的时间线仍可阅读/)).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByText(/2 秒后自动重试/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '立即重试' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('does not show the server banner once the list loads', () => {
    render(<ServiceBanner serverError={null} eventStatus="open" onRetry={() => {}} />);
    expect(screen.queryByText(/连不上 Chives 服务/)).toBeNull();
  });
});
