import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { avatarTones } from '../src/theme/tokens';
import { BotAvatar, EMBLEMS, EMBLEM_LABELS } from '../src/brand/BotAvatar';

describe('BotAvatar', () => {
  it('renders every emblem on every tone', () => {
    const tones = Object.keys(avatarTones);
    expect(EMBLEMS).toEqual(expect.arrayContaining(['stone', 'shield', 'orb', 'peak', 'page']));
    expect(tones).toHaveLength(5);

    for (const emblem of EMBLEMS) {
      for (const tone of tones) {
        const { container, unmount } = render(
          <BotAvatar emblem={emblem} tone={tone} name="测试" />
        );
        const svg = container.querySelector('svg');
        expect(svg).not.toBeNull();
        expect(svg?.getAttribute('aria-label')).toContain(EMBLEM_LABELS[emblem]);
        const ring = container.querySelector('.bot-avatar');
        expect(ring?.getAttribute('style')).toContain('width: 18px');
        unmount();
      }
    }
  });

  it('falls back to the monochrome crown for unknown values', () => {
    const { container } = render(<BotAvatar emblem="unknown" tone="unknown" />);
    expect(container.querySelector('svg')?.getAttribute('aria-label')).toContain('王冠');
    expect(container.querySelector('.bot-avatar')?.getAttribute('style')).not.toContain('background');
  });

  it('reserves imageUrl for uploaded avatars', () => {
    const { getByAltText } = render(
      <BotAvatar emblem="crown" tone="gold" name="投资专家" imageUrl="/avatar.png" />
    );
    expect(getByAltText('投资专家 头像').getAttribute('src')).toBe('/avatar.png');
  });
});
