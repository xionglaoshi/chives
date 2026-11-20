import { afterEach, describe, expect, it } from 'vitest';

import { waitFor } from './support.js';
import {
  closeFollowupHarnesses,
  followupMessages,
  startFollowupApp,
  stopFollowupApp,
} from './followup-support.js';

afterEach(async () => {
  await closeFollowupHarnesses();
});

function identity(taskId: string): { botId: string; taskId: string; depth: number } {
  return { botId: 'expert', taskId, depth: 0 };
}

function delegationMeta(input: {
  parentTaskId: string;
  childTaskId: string;
  reportBack: boolean;
}): Record<string, unknown> {
  return {
    delegationId: 'delegation-restart',
    parentTaskId: input.parentTaskId,
    targetBotId: 'research',
    targetBotName: '研究员',
    childTaskId: input.childTaskId,
    brief: '重启时还没完成',
    reportBack: input.reportBack,
    round: 1,
    status: 'running',
    startedAt: new Date().toISOString(),
    endedAt: null,
    error: null,
  };
}

describe('report-back delegation edge cases', () => {
  it('gives up after the busy window: timeline notice plus an important notification', async () => {
    const harness = await startFollowupApp({
      followupMaxMs: 120,
      scripts: {
        expert: [{ type: 'delay', ms: 600 }, { type: 'message', text: 'expert answer' }],
        research: [{ type: 'delay', ms: 30 }, { type: 'message', text: 'dataset ready' }],
      },
    });
    const accepted = await harness.app.orchestrator.submitMessage('expert', '父任务');
    const parentTaskId = accepted.taskId;
    await harness.app.delegations.delegate(identity(parentTaskId), {
      bot: 'research',
      brief: '快任务',
      reportBack: true,
    });

    await waitFor(
      () =>
        harness.app.store.messages
          .listByTask(parentTaskId)
          .some((message) => message.content.includes('没有自动合成')),
      3000,
    );
    const notifications = harness.app.store.notifications.list({ botId: 'expert', limit: 10 });
    expect(notifications).toHaveLength(1);
    expect(notifications[0]).toMatchObject({ level: 'important', taskId: parentTaskId });
    expect(notifications[0]?.body).toContain('一直在忙，没有自动合成');

    await waitFor(() => harness.app.store.tasks.get(parentTaskId)?.status === 'done', 5000);
    expect(followupMessages(harness, parentTaskId)).toHaveLength(0);
    expect(harness.driver.prompts.filter((entry) => entry.botId === 'expert')).toHaveLength(1);
    expect(harness.app.delegations.pendingFollowupTaskIds()).toHaveLength(0);
  });

  it('cancelling the initiator cancels the child and never follows up', async () => {
    const harness = await startFollowupApp({
      scripts: {
        expert: [{ type: 'delay', ms: 600 }, { type: 'message', text: 'expert answer' }],
        research: [{ type: 'delay', ms: 300 }, { type: 'message', text: 'late result' }],
      },
    });
    const accepted = await harness.app.orchestrator.submitMessage('expert', '父任务');
    const parentTaskId = accepted.taskId;
    const child = await harness.app.delegations.delegate(identity(parentTaskId), {
      bot: 'research',
      brief: '慢任务',
      reportBack: true,
    });
    harness.app.orchestrator.cancel('expert');

    await waitFor(() => harness.app.store.tasks.get(parentTaskId)?.status === 'cancelled', 5000);
    await waitFor(() => harness.app.store.tasks.get(child.id)?.status === 'cancelled', 5000);
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(followupMessages(harness, parentTaskId)).toHaveLength(0);
    expect(harness.app.delegations.pendingFollowupTaskIds()).toHaveLength(0);
  });

  it('stops a child that runs past the delegation timeout and reports it in the follow-up', async () => {
    const harness = await startFollowupApp({
      childTimeoutMs: 200,
      scripts: {
        expert: [{ type: 'delay', ms: 20 }, { type: 'message', text: 'expert answer' }],
        research: [{ type: 'delay', ms: 1500 }, { type: 'message', text: 'too late' }],
      },
    });
    const accepted = await harness.app.orchestrator.submitMessage('expert', '父任务');
    const parentTaskId = accepted.taskId;
    const child = await harness.app.delegations.delegate(identity(parentTaskId), {
      bot: 'research',
      brief: '很慢的研究',
      reportBack: true,
    });
    await waitFor(() => harness.app.store.tasks.get(child.id)?.status === 'cancelled', 5000);
    await waitFor(() => followupMessages(harness, parentTaskId).length === 1, 5000);
    const prompt = harness.driver.prompts.filter((entry) => entry.botId === 'expert').at(-1)?.text ?? '';
    expect(prompt).toContain('分钟没有完成，已停止');
  }, 10_000);

  it('applies a per-delegation timeout_minutes and defaults to 20 minutes', async () => {
    const harness = await startFollowupApp({
      scripts: {
        expert: [{ type: 'delay', ms: 20 }, { type: 'message', text: 'expert answer' }],
        research: [{ type: 'delay', ms: 50 }, { type: 'message', text: 'done' }],
      },
    });
    const accepted = await harness.app.orchestrator.submitMessage('expert', '父任务');
    const custom = await harness.app.delegations.delegate(identity(accepted.taskId), {
      bot: 'research',
      brief: '完整版',
      reportBack: true,
      timeoutMinutes: 35,
    });
    expect(harness.app.delegations.timeoutMsFor(custom.id)).toBe(35 * 60_000);
    const plain = await harness.app.delegations.delegate(identity(accepted.taskId), {
      bot: 'research',
      brief: '默认',
      reportBack: true,
    });
    expect(harness.app.delegations.timeoutMsFor(plain.id)).toBe(20 * 60_000);
  });

  it('report_back=false never triggers a follow-up; delegate_wait returns the result', async () => {
    const harness = await startFollowupApp({
      scripts: {
        expert: [{ type: 'delay', ms: 200 }, { type: 'message', text: 'expert answer' }],
        research: [{ type: 'delay', ms: 30 }, { type: 'message', text: 'dataset ready' }],
      },
    });
    const accepted = await harness.app.orchestrator.submitMessage('expert', '父任务');
    const parentTaskId = accepted.taskId;
    const result = await harness.app.delegations.delegate(identity(parentTaskId), {
      bot: 'research',
      brief: '同步取结果',
      reportBack: false,
      waitSeconds: 5,
    });
    expect(result).toMatchObject({ status: 'done', result: 'dataset ready', report_back: false });

    await waitFor(() => harness.app.store.tasks.get(parentTaskId)?.status === 'done', 5000);
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(followupMessages(harness, parentTaskId)).toHaveLength(0);
    expect(harness.driver.prompts.filter((entry) => entry.botId === 'expert')).toHaveLength(1);
  });

  it('queued results are merged into the user turn on the same task instead of a follow-up', async () => {
    const harness = await startFollowupApp({
      scripts: {
        expert: [{ type: 'delay', ms: 350 }, { type: 'message', text: 'expert answer' }],
        research: [{ type: 'delay', ms: 150 }, { type: 'message', text: 'dataset ready' }],
      },
    });
    const accepted = await harness.app.orchestrator.submitMessage('expert', '父任务');
    const parentTaskId = accepted.taskId;
    const child = await harness.app.delegations.delegate(identity(parentTaskId), {
      bot: 'research',
      brief: '快任务',
      reportBack: true,
    });

    // A long-running task on the same bot keeps the follow-up queued.
    const startedAt = harness.app.store.tasks.get(parentTaskId)?.startedAt ?? new Date().toISOString();
    const blocking = harness.app.store.tasks.create({
      botId: 'expert',
      startedAt: new Date(Date.parse(startedAt) - 3_600_000).toISOString(),
    });
    await waitFor(() => harness.app.store.tasks.get(child.id)?.status === 'done', 5000);
    await waitFor(() =>
      harness.app.delegations.pendingFollowupTaskIds().includes(parentTaskId),
    );
    await waitFor(() => harness.app.store.tasks.get(parentTaskId)?.status === 'done', 5000);

    harness.app.store.tasks.finish(blocking.id, 'done', new Date().toISOString());
    const next = await harness.app.orchestrator.submitMessage('expert', '继续这个问题');
    expect(next.taskId).toBe(parentTaskId);

    await waitFor(
      () => harness.driver.prompts.some((entry) => entry.text.includes('并入本轮')),
      5000,
    );
    const prompt =
      harness.driver.prompts.find((entry) => entry.text.includes('并入本轮'))?.text ?? '';
    expect(prompt).toContain('dataset ready');
    expect(prompt).toContain('并入本轮');
    expect(followupMessages(harness, parentTaskId)).toHaveLength(0);
    expect(harness.app.delegations.pendingFollowupTaskIds()).toHaveLength(0);
  });

  it('after a restart an interrupted report-back child still produces one follow-up', async () => {
    const first = await startFollowupApp();
    const parent = first.app.store.tasks.create({
      botId: 'expert',
      startedAt: new Date(Date.now() - 60_000).toISOString(),
    });
    first.app.store.tasks.finish(parent.id, 'done', new Date().toISOString());
    const child = first.app.store.tasks.create({
      botId: 'research',
      startedAt: new Date().toISOString(),
      parentTaskId: parent.id,
      depth: 1,
      delegated: true,
      brief: '重启时还没完成',
    });
    first.app.store.messages.append({
      id: 'delegation-message',
      botId: 'expert',
      taskId: parent.id,
      role: 'bot',
      kind: 'delegation',
      content: '委派给 研究员：重启时还没完成',
      meta: delegationMeta({ parentTaskId: parent.id, childTaskId: child.id, reportBack: true }),
      createdAt: new Date().toISOString(),
    });
    await stopFollowupApp(first, false, false);

    const second = await startFollowupApp({ dataDir: first.dataDir });
    expect(second.app.store.tasks.get(child.id)?.status).toBe('interrupted');
    await waitFor(() => followupMessages(second, parent.id).length === 1, 5000);
    expect(second.driver.prompts[0]?.text).toContain('子任务因服务重启中断');
    expect(followupMessages(second, parent.id)[0]).toContain('研究员');
  });
});
