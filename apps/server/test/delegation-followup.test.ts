import { afterEach, describe, expect, it } from 'vitest';

import { waitFor } from './support.js';
import {
  closeFollowupHarnesses,
  followupMessages,
  startFollowupApp,
} from './followup-support.js';

afterEach(async () => {
  await closeFollowupHarnesses();
});

function identity(taskId: string): { botId: string; taskId: string; depth: number } {
  return { botId: 'expert', taskId, depth: 0 };
}

describe('report-back delegation follow-up', () => {
  it('ends the initiator turn, then wakes the same task with result, deliverables and a separator', async () => {
    const harness = await startFollowupApp({
      withWorkspace: true,
      scripts: {
        expert: [{ type: 'delay', ms: 100 }, { type: 'message', text: 'expert first answer' }],
        research: [
          { type: 'write', path: 'reports/600519.md', content: '# 600519 数据\n' },
          { type: 'delay', ms: 200 },
          { type: 'message', text: 'dataset ready' },
        ],
      },
    });
    const accepted = await harness.app.orchestrator.submitMessage('expert', '分析茅台 600519.SH');
    const parentTaskId = accepted.taskId;

    const started = await harness.app.delegations.delegate(identity(parentTaskId), {
      bot: 'research',
      brief: '取三表并落盘',
      reportBack: true,
    });
    expect(started).toMatchObject({ bot: 'research', status: 'running', report_back: true });

    await waitFor(() => followupMessages(harness, parentTaskId).length === 1, 5000);
    const followup = harness.driver.prompts.find(
      (prompt) => prompt.botId === 'expert' && prompt.text.includes('委派结果已返回'),
    );
    expect(followup?.botId).toBe('expert');
    expect(followup?.text).toContain('委派结果已返回');
    expect(followup?.text).toContain('dataset ready');
    expect(followup?.text).toContain('reports/600519.md');
    expect(followup?.text).toContain('研究员');
    expect(followup?.text).toContain('不要为同一件事再次委派');

    await waitFor(() => harness.app.store.tasks.get(parentTaskId)?.status === 'done', 5000);
    const rows = followupMessages(harness, parentTaskId);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toContain('委派结果已返回');
    expect(rows[0]).toContain('研究员');

    // The follow-up is a turn inside the same task, never a second task.
    const expertTasks = harness.app.store.tasks
      .listAll()
      .filter((task) => task.botId === 'expert' && !task.delegated);
    expect(expertTasks.map((task) => task.id)).toEqual([parentTaskId]);
  });

  it('waits for all three parallel children and follows up exactly once with the failure reason', async () => {
    const harness = await startFollowupApp({
      scripts: {
        expert: [{ type: 'delay', ms: 300 }, { type: 'message', text: 'expert answer' }],
        research: [{ type: 'delay', ms: 30 }, { type: 'message', text: 'research done' }],
        'equity-analyst': [{ type: 'delay', ms: 60 }, { type: 'message', text: 'equity done' }],
        'report-builder': [{ type: 'delay', ms: 90 }, { type: 'fail', message: 'upstream 500' }],
      },
    });
    const accepted = await harness.app.orchestrator.submitMessage('expert', '并行三件事');
    const parentTaskId = accepted.taskId;

    for (const bot of ['research', 'equity-analyst', 'report-builder']) {
      const result = await harness.app.delegations.delegate(identity(parentTaskId), {
        bot,
        brief: `任务 ${bot}`,
        reportBack: true,
      });
      expect(result).toMatchObject({ status: 'running' });
    }
    await waitFor(() =>
      harness.app.store.tasks
        .listByParent(parentTaskId)
        .every((task) => task.status !== 'running'),
    );
    // Two children finished while the initiator was still answering: no follow-up yet.
    expect(followupMessages(harness, parentTaskId)).toHaveLength(0);

    await waitFor(() => followupMessages(harness, parentTaskId).length === 1, 5000);
    expect(followupMessages(harness, parentTaskId)).toHaveLength(1);
    const prompt =
      harness.driver.prompts.find(
        (entry) => entry.botId === 'expert' && entry.text.includes('委派结果已返回'),
      )?.text ?? '';
    expect(prompt).toContain('research done');
    expect(prompt).toContain('equity done');
    expect(prompt).toContain('失败原因');
    expect(prompt).toContain('upstream 500');
    expect(prompt).toContain('个股分析师');
    expect(prompt).toContain('报告员');
  });

  it('follows up again when the follow-up turn starts a new report-back delegation', async () => {
    const harness = await startFollowupApp({
      scripts: {
        expert: [{ type: 'delay', ms: 250 }, { type: 'message', text: 'expert answer' }],
        research: [{ type: 'delay', ms: 150 }, { type: 'message', text: 'dataset ready' }],
      },
    });
    const accepted = await harness.app.orchestrator.submitMessage('expert', '第一轮');
    const parentTaskId = accepted.taskId;
    await harness.app.delegations.delegate(identity(parentTaskId), {
      bot: 'research',
      brief: '第一次委派',
      reportBack: true,
    });

    await waitFor(
      () => harness.driver.prompts.some((entry) => entry.text.includes('委派结果已返回')),
      5000,
    );
    const second = await harness.app.delegations.delegate(identity(parentTaskId), {
      bot: 'research',
      brief: '跟进轮里的第二次委派',
      reportBack: true,
    });
    expect(second).toMatchObject({ status: 'running' });

    await waitFor(() => followupMessages(harness, parentTaskId).length === 2, 5000);
    const secondFollowup = harness.driver.prompts.find(
      (entry) => entry.botId === 'expert' && entry.text.includes('跟进轮里的第二次委派'),
    );
    expect(secondFollowup?.text).toContain('委派结果已返回');
    expect(followupMessages(harness, parentTaskId)).toHaveLength(2);
  });

  it('queues the follow-up while the initiator is busy and runs it when the turn ends', async () => {
    const harness = await startFollowupApp({
      scripts: {
        expert: [{ type: 'delay', ms: 400 }, { type: 'message', text: 'expert answer' }],
        research: [{ type: 'delay', ms: 50 }, { type: 'message', text: 'dataset ready' }],
      },
    });
    const accepted = await harness.app.orchestrator.submitMessage('expert', '父任务');
    const parentTaskId = accepted.taskId;
    await harness.app.delegations.delegate(identity(parentTaskId), {
      bot: 'research',
      brief: '快任务',
      reportBack: true,
    });

    await waitFor(() =>
      harness.app.delegations.pendingFollowupTaskIds().includes(parentTaskId),
    );
    expect(harness.app.store.tasks.get(parentTaskId)?.status).toBe('running');

    await waitFor(() => followupMessages(harness, parentTaskId).length === 1, 5000);
    expect(harness.app.delegations.pendingFollowupTaskIds()).toHaveLength(0);
  });

  it('exposes the waiting delegation count on the initiator bot summary', async () => {
    const harness = await startFollowupApp({
      scripts: {
        expert: [{ type: 'delay', ms: 50 }, { type: 'message', text: 'expert answer' }],
        research: [{ type: 'delay', ms: 500 }, { type: 'message', text: 'dataset ready' }],
      },
    });
    const accepted = await harness.app.orchestrator.submitMessage('expert', '父任务');
    await harness.app.delegations.delegate(identity(accepted.taskId), {
      bot: 'research',
      brief: '慢任务',
      reportBack: true,
    });
    await waitFor(() => harness.app.store.tasks.get(accepted.taskId)?.status === 'done', 5000);

    const response = await fetch(`${harness.baseUrl}/api/bots`);
    const bots = (await response.json()) as Array<{
      id: string;
      status: string;
      waitingDelegations?: number;
    }>;
    const expert = bots.find((bot) => bot.id === 'expert');
    expect(expert?.status).toBe('idle');
    expect(expert?.waitingDelegations).toBe(1);
  });
});
