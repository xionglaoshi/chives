import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { NotificationDto } from '@chives/server/protocol';
import { DashboardBotMessages } from './DashboardBotMessages';

describe('DashboardBotMessages', () => {
  it('shows the latest 20 by default and includes every older unread notification on expansion', () => {
    const notifications: NotificationDto[] = Array.from({length: 75}, (_, index) => ({
      id: String(index), botId: 'operator', taskId: String(index), title: '盯盘触发',
      body: '这里是通知正文', level: 'info', createdAt: '2026-11-24T05:00:00Z',
      readAt: index < 20 || index === 21 ? '2026-11-24T06:00:00Z' : null,
    }));
    const render = (expanded: boolean) => renderToStaticMarkup(
      <DashboardBotMessages notifications={notifications} bots={[{id: 'operator', name: '总调度'}]} expanded={expanded}
        loading={false} error={false} onLoadMore={() => {}} onOpen={() => {}} />
    );
    const latest = render(false);
    const expanded = render(true);
    expect(latest.match(/<li>/g)).toHaveLength(20);
    expect(latest).toContain('载入更多');
    expect(expanded.match(/<li>/g)).toHaveLength(74);
    expect(expanded.match(/mb-bot-message--unread/g)).toHaveLength(54);
    expect(expanded).toContain('载入更多');
    expect(expanded).toContain('总调度：盯盘触发');
    expect(expanded).not.toContain('【盯盘】');
    expect(expanded).not.toContain('这里是通知正文');
  });
});
