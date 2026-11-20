import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { Welcome } from '../src/components/Welcome';

const props = {
  value: '',
  onChange: () => {},
  onSend: () => {},
  onStop: () => {},
  running: false,
  sending: false,
  notice: null
};

describe('Welcome', () => {
  it('shows the greeting, four starters and three boundaries', () => {
    render(<Welcome {...props} />);
    expect(screen.getByRole('heading', { name: '今天想研究什么？' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /点评一份财报/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /今天盘面怎么样/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /帮我找几只候选/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /每天早上给我发晨报/ })).toBeTruthy();
    expect(screen.getByText('只做 A 股研究，外盘作为参考')).toBeTruthy();
    expect(screen.getByText('不连接真实券商，下单只在模拟盘')).toBeTruthy();
    expect(screen.getByText('所有数据带来源和时间')).toBeTruthy();
  });

  it('sends a starter prompt when clicked', () => {
    const onSend = vi.fn();
    render(<Welcome {...props} onSend={onSend} />);
    fireEvent.click(screen.getByRole('button', { name: /点评一份财报/ }));
    expect(onSend).toHaveBeenCalledWith('点评一份财报');
  });
});
