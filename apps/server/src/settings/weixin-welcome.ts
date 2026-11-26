import {createHash} from 'node:crypto';

export const weixinWelcomeKey = 'onboarding.weixin.welcomed';
const greeting = '恭喜，你已将 Chives 接入微信。以后可以在这里和 Chives 交流，Chives 也会通过微信给你推送重要信息。';

export interface WeixinWelcomeState {
  hasWelcomed(binding: string): boolean;
  markWelcomed(binding: string): void;
}

/** Called only for a verified inbox message belonging to the active binding. */
export async function welcomeWeixin(
  state: WeixinWelcomeState,
  binding: string,
  reply: (text: string, deliveryId: string) => Promise<unknown>,
): Promise<void> {
  if (state.hasWelcomed(binding)) return;
  const deliveryId = createHash('sha256').update(`chives:weixin:welcome:${binding}`).digest('hex');
  await reply(greeting, deliveryId);
  state.markWelcomed(binding);
}
