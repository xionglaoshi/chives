import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { DeliverableDto, MessageDto, TaskDto, ToolEventDto } from '@chives/server/protocol';
import { Timeline } from '../src/components/Timeline';
import { initialTimelineState, timelineReducer } from '../src/hooks/useTimeline';

function isoToday(hour: number, minute: number): string {
  const date = new Date();
  date.setHours(hour, minute, 0, 0);
  return date.toISOString();
}

function isoYesterday(hour: number, minute: number): string {
  const date = new Date();
  date.setDate(date.getDate() - 1);
  date.setHours(hour, minute, 0, 0);
  return date.toISOString();
}

const task: TaskDto = {
  id: 't1',
  botId: 'expert',
  title: '贵州茅台三季报点评',
  status: 'done',
  harnessSessionId: null,
  startedAt: isoToday(9, 58),
  endedAt: isoToday(10, 0),
  parentTaskId: null
};

const userMessage: MessageDto = {
  id: 'm1',
  botId: 'expert',
  taskId: 't1',
  role: 'user',
  kind: 'text',
  content: '看下贵州茅台三季报',
  meta: null,
  createdAt: isoToday(9, 58),
  seq: 1
};

const botMessage: MessageDto = {
  id: 'm2',
  botId: 'expert',
  taskId: 't1',
  role: 'bot',
  kind: 'text',
  content: '结论如下：\n\n| 指标 | 数值 |\n| --- | ---: |\n| 每股收益 | 51.53 元 |\n| 市盈率 | 21.84 倍 |\n',
  meta: null,
  createdAt: isoToday(10, 0),
  seq: 2
};

const oldMessage: MessageDto = {
  id: 'm0',
  botId: 'expert',
  taskId: null,
  role: 'system',
  kind: 'notice',
  content: '昨天的一条系统消息',
  meta: null,
  createdAt: isoYesterday(18, 0),
  seq: 0
};

const output = `${'x'.repeat(2000)}TAIL`;

const tools: ToolEventDto[] = [
  {
    id: 'tool-1',
    taskId: 't1',
    messageId: null,
    toolCallId: 'call-1',
    title: 'cn_get_quote_snapshot',
    kind: 'read',
    rawInput: { symbol: '600519.SH' },
    status: 'completed',
    output,
    startedAt: isoToday(9, 58),
    endedAt: isoToday(9, 59)
  }
];

const baseProps = {
  botId: 'expert',
  messages: [oldMessage, userMessage, botMessage],
  tasks: { t1: task },
  toolEvents: { t1: tools },
  draft: null,
  pending: [],
  hasMore: false,
  loadingOlder: false,
  onLoadOlder: () => {},
  onRetryPending: () => {}
};

describe('Timeline', () => {
  it('hides execution stamps in history and live updates while keeping replies and operational notices', () => {
    const stamp: MessageDto = { ...oldMessage, content: 'dsh · deepseek-flash',
      meta: { kernel: 'dsh', model: 'deepseek-flash' } };
    const reply = { ...botMessage, content: stamp.content };
    const warning = { ...stamp, id: 'warning', content: '模型连接中断，请重试。' };
    const { container, rerender } = render(<Timeline {...baseProps} messages={[stamp,reply,warning]} />);
    expect(container.querySelector('[data-message-id="m0"]')).toBeNull();
    expect(screen.getByText(reply.content)).toBeTruthy();
    expect(screen.getByText(warning.content)).toBeTruthy();
    rerender(<Timeline {...baseProps} messages={[reply,{ ...stamp,id:'new-stamp',content:'codex · example',meta:{kernel:'codex',model:'example'} }]} />);
    expect(screen.queryByText('codex · example')).toBeNull();
  });

  it('renders date separators and a GFM table with right-aligned numbers', () => {
    const { container } = render(<Timeline {...baseProps} />);
    expect(screen.getByText('昨天')).toBeTruthy();
    expect(screen.getByText('今天')).toBeTruthy();
    expect(screen.getByText('贵州茅台三季报点评')).toBeTruthy();

    const numeric = screen.getByText('51.53 元');
    expect(numeric.tagName).toBe('TD');
    expect(numeric.className).toContain('md-num');
    expect(container.querySelector('table')).not.toBeNull();
  });

  it('offers a per-code retry action on a failure notice', () => {
    const onRetryTask = vi.fn();
    const notice: MessageDto = {
      id: 'm-notice',
      botId: 'expert',
      taskId: 't1',
      role: 'system',
      kind: 'notice',
      content: '这一轮中断了，已保留之前的内容。',
      meta: { code: 'harness_crashed' },
      createdAt: isoToday(10, 1),
      seq: 3
    };
    render(
      <Timeline
        {...baseProps}
        messages={[userMessage, notice]}
        onRetryTask={onRetryTask}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: '重试这一轮' }));
    expect(onRetryTask).toHaveBeenCalledWith('t1');
  });

  it('expands a task row to tool steps and truncates output at 2000 characters', () => {
    const { container } = render(<Timeline {...baseProps} />);
    const workToggle = screen.getByRole('button', { name: /工作了/ });
    expect(workToggle.getAttribute('aria-expanded')).toBe('false');

    fireEvent.click(workToggle);
    expect(workToggle.getAttribute('aria-expanded')).toBe('true');
    const toolToggle = screen.getByRole('button', { name: /cn_get_quote_snapshot/ });
    fireEvent.click(toolToggle);

    const pres = container.querySelectorAll('.task-step__pre');
    expect(pres).toHaveLength(2);
    expect(pres[1]?.textContent).not.toContain('TAIL');
    expect(pres[1]?.textContent).toContain('…（输出已截断）');
    expect(screen.getByText(/共 2004 字，仅显示前 2000 字/)).toBeTruthy();
    expect(container.querySelector('.task-step__detail')?.textContent).toContain('600519.SH');
  });


  it('puts a running task\'s progress row right after the latest follow-up', () => {
    const running: TaskDto = { ...task, status: 'running', endedAt: null };
    const followUp: MessageDto = {
      ...userMessage,
      id: 'm3',
      content: '再看下估值',
      createdAt: isoToday(10, 5),
      seq: 3
    };
    const { container } = render(
      <Timeline {...baseProps} tasks={{ t1: running }} messages={[userMessage, botMessage, followUp]} />
    );
    const order = [...container.querySelectorAll('.timeline__task, [data-message-id]')].map(
      (node) => node.getAttribute('data-message-id') ?? 'progress'
    );
    expect(order).toEqual(['m1', 'm2', 'm3', 'progress']);
    expect(screen.getByRole('button', { name: /工作中/ })).toBeTruthy();
  });

  it('keeps a finished task\'s progress row after its first message', () => {
    const followUp: MessageDto = { ...userMessage, id: 'm3', createdAt: isoToday(10, 5), seq: 3 };
    const { container } = render(
      <Timeline {...baseProps} messages={[userMessage, botMessage, followUp]} />
    );
    const order = [...container.querySelectorAll('.timeline__task, [data-message-id]')].map(
      (node) => node.getAttribute('data-message-id') ?? 'progress'
    );
    expect(order).toEqual(['m1', 'progress', 'm2', 'm3']);
  });

  it('marks a searched message for scrolling and highlight', () => {
    const { container } = render(<Timeline {...baseProps} highlightMessageId="m2" />);
    const anchor = container.querySelector('[data-message-id="m2"]');
    expect(anchor?.className).toContain('timeline__anchor--highlight');
    expect(container.querySelector('#timeline-message-m2')).toBe(anchor);
  });

  it('renders a streaming draft with a cursor and a committed draft without one', () => {
    const { container, rerender } = render(
      <Timeline {...baseProps} draft={{ taskId: 't1', text: '三季报的核心数字很平', committed: false }} />
    );
    expect(screen.getByText('正在撰写…')).toBeTruthy();
    expect(container.querySelector('.timeline__cursor')).not.toBeNull();

    rerender(
      <Timeline {...baseProps} draft={{ taskId: 't1', text: '三季报的核心数字很平', committed: true }} />
    );
    expect(screen.getByText('正在提交…')).toBeTruthy();
    expect(container.querySelector('.timeline__cursor')).toBeNull();
  });


  it('marks each task boundary and exposes a closed task conclusion on hover', () => {
    const secondTask: TaskDto = {
      ...task,
      id: 't2',
      title: '宁德时代三季报',
      closedAt: isoToday(11, 0),
      summaryTitle: '宁德时代小结',
      summaryConclusion: '增速放缓，毛利率承压'
    };
    const secondUser: MessageDto = {
      ...userMessage,
      id: 'm3',
      taskId: 't2',
      content: '看下宁德时代',
      createdAt: isoToday(10, 30),
      seq: 3
    };
    const secondBot: MessageDto = {
      ...botMessage,
      id: 'm4',
      taskId: 't2',
      content: '增速放缓。',
      createdAt: isoToday(11, 0),
      seq: 4
    };
    render(
      <Timeline
        {...baseProps}
        messages={[userMessage, botMessage, secondUser, secondBot]}
        tasks={{ t1: task, t2: secondTask }}
      />
    );
    expect(screen.getByText('新任务 · 贵州茅台三季报点评')).toBeTruthy();
    const divider = screen.getByText('新任务 · 宁德时代小结').closest('.timeline__task-divider');
    expect(divider?.getAttribute('title')).toBe('增速放缓，毛利率承压');
    expect(divider?.getAttribute('role')).toBe('separator');
  });

  it('asks for an older page when scrolled to the top', () => {
    const onLoadOlder = vi.fn();
    render(<Timeline {...baseProps} hasMore onLoadOlder={onLoadOlder} />);
    fireEvent.scroll(screen.getByRole('log', { name: '时间线' }));
    expect(onLoadOlder).toHaveBeenCalledTimes(1);
  });

  it('shows a retry action beside a failed pending message', () => {
    const onRetryPending = vi.fn();
    render(
      <Timeline
        {...baseProps}
        pending={[{ id: 'p1', text: '补充一条', status: 'failed' }]}
        onRetryPending={onRetryPending}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(onRetryPending).toHaveBeenCalledWith({ id: 'p1', text: '补充一条', status: 'failed' });
  });
});

describe('Timeline markdown links', () => {
  it('opens a matching deliverable and blocks unmatched relative links', () => {
    const deliverable: DeliverableDto = {
      id: 'd1',
      taskId: 't1',
      botId: 'expert',
      path: 'reports/a.md',
      kind: 'markdown',
      size: 10,
      createdAt: isoToday(10, 0)
    };
    const linked: MessageDto = {
      ...botMessage,
      id: 'm3',
      content: '看[报告](reports/a.md)，另见[不存在](reports/missing.md)。',
      seq: 3
    };
    const deliverableMessage: MessageDto = {
      ...botMessage,
      id: 'm4',
      kind: 'deliverable',
      content: '已生成',
      meta: { deliverables: [deliverable] },
      seq: 4
    };
    const onOpenDeliverable = vi.fn();
    render(
      <Timeline
        {...baseProps}
        messages={[userMessage, linked, deliverableMessage]}
        onOpenDeliverable={onOpenDeliverable}
      />
    );

    const linkedButton = screen.getByRole('button', { name: '报告' });
    fireEvent.click(linkedButton);
    expect(onOpenDeliverable).toHaveBeenCalledWith(deliverable, linkedButton);
    expect(screen.queryByRole('link', { name: '不存在' })).toBeNull();
    expect(screen.getByText('不存在').tagName).toBe('CODE');
  });
});

describe('proactive timeline pieces', () => {
  it('renders the proactive separator line with its title', () => {
    const proactive: MessageDto = {
      ...oldMessage,
      id: 'p1',
      taskId: 't1',
      role: 'system',
      kind: 'proactive',
      content: '主动消息 · 08:30 · 盘前简报',
      createdAt: isoToday(8, 30),
      seq: 5
    };
    const { container } = render(
      <Timeline {...baseProps} messages={[proactive, userMessage, botMessage]} />
    );
    expect(screen.getByText('主动消息 · 08:30 · 盘前简报')).toBeTruthy();
    const divider = container.querySelector('.timeline__proactive-divider');
    expect(divider).not.toBeNull();
    expect(divider?.getAttribute('aria-label')).toBe('主动消息 · 08:30 · 盘前简报');
  });

  it('renders the routine confirmation card and enables it', () => {
    const card: MessageDto = {
      ...oldMessage,
      id: 'r1',
      taskId: 't1',
      role: 'system',
      kind: 'approval',
      content: '新的主动任务：盘前简报 · 工作日 08:30（北京时间）',
      meta: {
        approvalKind: 'routine',
        routineId: 'user:1',
        title: '盘前简报',
        scheduleText: '工作日 08:30（北京时间）',
        promptSummary: '按 morning-note 技能出盘前简报',
        decision: null
      },
      createdAt: isoToday(8, 0),
      seq: 6
    };
    const onEnableRoutine = vi.fn(async () => undefined);
    const onDismissRoutine = vi.fn(async () => undefined);
    render(
      <Timeline
        {...baseProps}
        messages={[card, userMessage, botMessage]}
        onEnableRoutine={onEnableRoutine}
        onDismissRoutine={onDismissRoutine}
      />
    );
    expect(screen.getByText('要创建主动任务：盘前简报')).toBeTruthy();
    expect(screen.getByText('工作日 08:30（北京时间）')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '启用' }));
    expect(onEnableRoutine).toHaveBeenCalledWith('user:1');
    expect(onDismissRoutine).not.toHaveBeenCalled();
  });
});

describe('timelineReducer drafts', () => {
  it('resets, appends deltas, commits, then replaces the draft with the created message', () => {
    let state = timelineReducer(initialTimelineState, { type: 'reset', botId: 'expert' });
    state = timelineReducer(state, {
      type: 'event',
      event: {
        type: 'draft.reset',
        id: 1,
        at: isoToday(10, 0),
        botId: 'expert',
        taskId: 't1',
        sessionId: 's1'
      }
    });
    expect(state.draft).toEqual({ taskId: 't1', text: '', committed: false });

    state = timelineReducer(state, {
      type: 'event',
      event: {
        type: 'draft.delta',
        id: 2,
        at: isoToday(10, 0),
        botId: 'expert',
        taskId: 't1',
        sessionId: 's1',
        kind: 'text',
        text: '你好'
      }
    });
    state = timelineReducer(state, {
      type: 'event',
      event: {
        type: 'draft.delta',
        id: 3,
        at: isoToday(10, 0),
        botId: 'expert',
        taskId: 't1',
        sessionId: 's1',
        kind: 'text',
        text: '，世界'
      }
    });
    expect(state.draft?.text).toBe('你好，世界');

    state = timelineReducer(state, {
      type: 'event',
      event: {
        type: 'draft.commit',
        id: 4,
        at: isoToday(10, 0),
        botId: 'expert',
        taskId: 't1',
        sessionId: 's1',
        text: '你好，世界'
      }
    });
    expect(state.draft).toEqual({ taskId: 't1', text: '你好，世界', committed: true });

    state = timelineReducer(state, {
      type: 'event',
      event: {
        type: 'message.created',
        id: 5,
        at: isoToday(10, 0),
        botId: 'expert',
        taskId: 't1',
        message: { ...botMessage, content: '你好，世界' }
      }
    });
    expect(state.draft).toBeNull();
    expect(state.messages.some((message) => message.content === '你好，世界')).toBe(true);
  });

  it('ignores drafts from a delegated child task (they are published under the root bot)', () => {
    let state = timelineReducer(initialTimelineState, { type: 'reset', botId: 'expert' });
    state = {
      ...state,
      messages: [
        {
          ...botMessage,
          id: 'd1',
          kind: 'delegation',
          content: '',
          meta: { delegationId: 'd1', childTaskId: 'child-1', targetBotId: 'data-prep' }
        }
      ]
    };
    state = timelineReducer(state, {
      type: 'event',
      event: {
        type: 'draft.delta',
        id: 9,
        at: isoToday(10, 0),
        botId: 'expert',
        taskId: 'child-1',
        sessionId: 's2',
        kind: 'text',
        text: '我现在开始取数'
      }
    });
    expect(state.draft).toBeNull();
  });

  it('renders a follow-up separator that expands the matching delegation rows', () => {
    const delegation: MessageDto = {
      id: 'm-delegation',
      botId: 'expert',
      taskId: 't1',
      role: 'bot',
      kind: 'delegation',
      content: '委派给 个股分析师：做估值',
      meta: {
        delegationId: 'd1',
        parentTaskId: 't1',
        targetBotId: 'equity-analyst',
        targetBotName: '个股分析师',
        childTaskId: 'child-1',
        brief: '做完整估值',
        reportBack: true,
        status: 'done',
        startedAt: isoToday(9, 59),
        endedAt: isoToday(10, 2),
        error: null
      },
      createdAt: isoToday(9, 59),
      seq: 3
    };
    const followup: MessageDto = {
      id: 'm-followup',
      botId: 'expert',
      taskId: 't1',
      role: 'system',
      kind: 'proactive',
      content: '委派结果已返回 · 个股分析师',
      meta: { followup: true, childTaskIds: ['child-1'] },
      createdAt: isoToday(10, 2),
      seq: 4
    };
    render(
      <Timeline
        {...baseProps}
        messages={[userMessage, botMessage, delegation, followup]}
      />
    );
    const toggle = screen.getByRole('button', { name: /委派结果已返回/ });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getAllByText(/做完整估值/).length).toBeGreaterThanOrEqual(2);
  });
});
