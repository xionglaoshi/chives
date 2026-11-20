import { describe, expect, it } from 'vitest';

import { readRoute, routeHash, settingsHash } from '../src/utils/routes';

describe('routes', () => {
  it('opens the market board from the root or its workspace link', () => {
    for (const hash of ['', '#/', '#/workspace/market']) {
      expect(readRoute(hash)).toEqual({name:'workspace',tool:'market'});
    }
  });

  it('parses and renders the settings route', () => {
    expect(readRoute('#/settings')).toEqual({ name: 'settings' });
    expect(routeHash({ name: 'settings' })).toBe('#/settings');
    expect(settingsHash()).toBe('#/settings');
  });

  it('keeps bot routes unchanged', () => {
    expect(readRoute('#/bot/expert')).toEqual({ name: 'conversation', botId: 'expert' });
    expect(readRoute('#/bot/expert/profile')).toEqual({ name: 'profile', botId: 'expert' });
    expect(routeHash({ name: 'profile', botId: 'expert' })).toBe('#/bot/expert/profile');
  });
});
