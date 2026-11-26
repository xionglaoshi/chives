import {createHash} from 'node:crypto';
import {expect, it, vi} from 'vitest';
import {Channels} from './channels.js';

const {invoke} = vi.hoisted(() => ({
  invoke: vi.fn<(operation: string, body: Record<string, unknown>) => object>(),
}));

vi.mock('node:child_process', () => ({
  execFile: (
    _file: string,
    args: string[],
    _options: unknown,
    callback: (error: Error | null, stdout: string) => void,
  ) => ({
    stdin: {
      on() {},
      end(input: string) {
        callback(null, JSON.stringify(invoke(args[2]!, JSON.parse(input))));
      },
    },
  }),
}));

it('routes Weixin replies by channel and acknowledges only after text and files', async () => {
  const message = {id: 'incoming', context: 'context', text: '你好', media: []};
  const binding = 'binding';
  const cursor = 'next-cursor';
  const deliveryId = createHash('sha256').update(binding + ':' + message.id).digest('hex');
  invoke.mockImplementation((operation, body) => {
    if (operation !== 'poll') return {ok: true};
    if (body.id === 'weixin') return {binding, cursor, messages: [message]};
    return {enabled: false};
  });

  const channels = new Channels('/chives', '/data', () => '总经理');
  try {
    channels.startInboxes(async () => ({
      text: '你好',
      files: [{path: '/data/report.pdf', botId: 'ceo'}],
    }));
    await vi.waitFor(() => {
      expect(invoke.mock.calls.filter(([operation]) => operation !== 'poll')).toEqual([
        ['reply', {id: 'weixin', binding, context: message.context, deliveryId, message: '【总经理：】你好'}],
        ['reply', {id: 'weixin', binding, context: message.context,
          deliveryId: deliveryId + '-file-0-label', message: '【总经理：】report.pdf'}],
        ['media_reply', {id: 'weixin', binding, context: message.context,
          deliveryId: deliveryId + '-file-0', path: '/data/report.pdf'}],
        ['ack', {id: 'weixin', binding, cursor}],
      ]);
    });
  } finally {
    channels.stopInboxes();
  }
});
