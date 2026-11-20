import { describe, expect, it } from 'vitest';

import { EventNormalizer } from '../src/index.js';

describe('EventNormalizer', () => {
  it('normalizes messages, thoughts, usage, config, and unknown updates', () => {
    const normalizer = new EventNormalizer();
    expect(normalizer.normalize('s1', {
      sessionUpdate: 'agent_message_chunk',
      messageId: 'm1',
      content: { type: 'text', text: 'hello' },
    })).toEqual({ type: 'message', sessionId: 's1', text: 'hello', messageId: 'm1' });

    expect(normalizer.normalize('s1', {
      sessionUpdate: 'agent_thought_chunk',
      content: { type: 'text', text: 'thinking' },
    })).toEqual({ type: 'thought', sessionId: 's1', text: 'thinking' });

    expect(normalizer.normalize('s1', { sessionUpdate: 'usage_update', used: 10, size: 100 }))
      .toEqual({ type: 'usage', sessionId: 's1', used: 10, size: 100 });

    expect(normalizer.normalize('s1', {
      sessionUpdate: 'config_option_update',
      configOptions: [{ id: 'model', currentValue: 'x' }],
    })).toMatchObject({ type: 'config', sessionId: 's1' });

    const unknown = normalizer.normalize('s1', { sessionUpdate: 'future_kind', payload: 1 });
    expect(unknown).toEqual({
      type: 'unknown',
      sessionId: 's1',
      update: { sessionUpdate: 'future_kind', payload: 1 },
    });
  });

  it('merges tool updates into one start and one terminal end', () => {
    const normalizer = new EventNormalizer();
    const start = normalizer.normalize('s1', {
      sessionUpdate: 'tool_call',
      toolCallId: 't1',
      title: 'Bash',
      kind: 'other',
      status: 'in_progress',
      rawInput: { command: 'echo hi' },
    });
    expect(start).toMatchObject({
      type: 'tool_start',
      toolCallId: 't1',
      title: 'Bash',
      rawInput: { command: 'echo hi' },
    });
    expect(normalizer.toolCall('t1')).toMatchObject({ title: 'Bash', rawInput: { command: 'echo hi' } });

    expect(normalizer.normalize('s1', {
      sessionUpdate: 'tool_call_update',
      toolCallId: 't1',
      status: 'in_progress',
    })).toBeUndefined();

    const end = normalizer.normalize('s1', {
      sessionUpdate: 'tool_call_update',
      toolCallId: 't1',
      status: 'completed',
      content: [{ type: 'content', content: { type: 'text', text: 'hi\n' } }],
    });
    expect(end).toMatchObject({ type: 'tool_end', status: 'completed', output: 'hi\n' });

    expect(normalizer.normalize('s1', {
      sessionUpdate: 'tool_call_update',
      toolCallId: 't1',
      status: 'failed',
    })).toBeUndefined();
  });

  it('reports failed tools and terminal updates that arrive without a start', () => {
    const normalizer = new EventNormalizer();
    const end = normalizer.normalize('s1', {
      sessionUpdate: 'tool_call_update',
      toolCallId: 't2',
      status: 'failed',
      content: [{ type: 'content', content: { type: 'text', text: 'boom' } }],
    });
    expect(end).toMatchObject({ type: 'tool_end', status: 'failed', output: 'boom' });
  });

  it('keeps malformed typed updates as unknown instead of dropping them', () => {
    const normalizer = new EventNormalizer();
    expect(normalizer.normalize('s1', { sessionUpdate: 'agent_message_chunk' }))
      .toMatchObject({ type: 'unknown' });
    expect(normalizer.normalize('s1', { sessionUpdate: 'tool_call' }))
      .toMatchObject({ type: 'unknown' });
    expect(normalizer.normalize('s1', { sessionUpdate: 'usage_update', used: 'x' }))
      .toMatchObject({ type: 'unknown' });
  });
});
