import { pixelIcons, pixelIconIds, type PixelIcon } from '../../../server/src/bots/pixel-icons';
import type { CSSProperties, ReactElement } from 'react';

import { avatarTones, type ToneName } from '../theme/tokens';
import './BotAvatar.css';

export const EMBLEMS = [
  'crown',
  'scale',
  'lens',
  'bars',
  'scroll',
  'compass',
  'coin',
  'quill',
  'key',
  'hourglass',
  'lamp',
  'shield',
  'stone',
  'orb',
  'peak',
  'page',
  ...pixelIconIds
] as const;

export type Emblem = (typeof EMBLEMS)[number];

export const EMBLEM_LABELS: Record<Emblem, string> = {
  ...Object.fromEntries(pixelIconIds.map(id => [id, pixelIcons[id].label])) as Record<PixelIcon,string>,
  stone: '六棱石',
  orb: '圆',
  peak: '升三角',
  page: '文稿',
  crown: '王冠',
  scale: '天平',
  lens: '放大镜',
  bars: '算筹',
  scroll: '卷轴',
  compass: '罗盘',
  coin: '金币',
  quill: '羽笔',
  key: '钥匙',
  hourglass: '沙漏',
  lamp: '明灯',
  shield: '盾徽'
};

/** Stepped monochrome outlines on an 18-pixel grid, shared by the picker and all Bot views. */
export const EMBLEM_PATHS: Record<Emblem, string> = {
  ...Object.fromEntries(pixelIconIds.map(id => [id, pixelIcons[id].path])) as Record<PixelIcon,string>,
  stone: 'M6 2h6v2h3v10h-3v2H6v-2H3V4h3z M6 4v2h6V4 M9 6v8',
  orb: 'M6 2h6v2h2v2h2v6h-2v2h-2v2H6v-2H4v-2H2V6h2V4h2z M6 7V6h2',
  peak: 'M2 15v-3h2V9h2V6h2V3h2v3h2v3h2v3h2v3z M6 9h2v2h2V9h2',
  page: 'M4 2h7v2h2v2h2v10H4z M11 2v5h4 M6 10h6 M6 13h4',
  crown: 'M2 5h2v2h2v2h1V6h1V3h2v3h1v3h1V7h2V5h2v8H2z M3 16h12',
  scale: 'M9 2v13 M5 16h8 M2 5h14 M4 6v2H3v2H2v1h4v-1H5V8H4 M14 6v2h-1v2h-1v1h4v-1h-1V8h-1',
  lens: 'M5 2h5v2h2v2h1v4h-2v2H5v-1H3V9H2V5h1V3h2z M11 12h2v2h2v2h1',
  bars: 'M2 16h14 M3 13V9h2v4 M8 13V5h2v8 M13 13V2h2v11',
  scroll: 'M3 3h10v1h2v3h-3V4 M3 3v9H2v2h2v1h7v-1h1V7 M5 7h4 M5 10h4',
  compass: 'M5 2h8v2h2v2h1v6h-1v2h-2v2H5v-2H3v-2H2V6h1V4h2z M6 12V9h2V7h3V6h1v3h-2v2H7v1z',
  coin: 'M5 3h8v2h2v8h-2v2H5v-2H3V5h2z M6 6v1h1v1h4V7h1V6 M6 10h6 M9 8v5',
  quill: 'M3 16v-3h2v-3h1V7h2V5h2V3h5v5h-2v2h-2v2H7v1H5 M7 10h2V8h2',
  key: 'M4 3h5v2h2v4H9v2H4V9H2V5h2z M5 6h2 M10 9h2v2h2v2h2v3h-3v-2h-2',
  hourglass: 'M3 2h12 M4 3v3h2v2h2v2H6v2H4v3 M14 3v3h-2v2h-2v2h2v2h2v3 M3 16h12 M6 13h6',
  lamp: 'M6 2h6v2h2v5h-2v2h-1v2H7v-2H6V9H4V4h2z M7 16h4',
  shield: 'M8 2h2v1h3v1h3v6h-1v2h-2v2h-2v1H9v1H8v-1H6v-2H4v-2H3V4h3V3h2z'
};

export function isEmblem(value: string): value is Emblem {
  return (EMBLEMS as readonly string[]).includes(value);
}

export function isTone(value: string): value is ToneName {
  return Object.prototype.hasOwnProperty.call(avatarTones, value);
}

export interface BotAvatarProps {
  emblem: string;
  tone: string;
  size?: number;
  imageUrl?: string | undefined;
  name?: string | undefined;
  className?: string | undefined;
}

export function BotAvatar({
  emblem,
  size = 18,
  imageUrl,
  name,
  className
}: BotAvatarProps): ReactElement {
  const safeEmblem: Emblem = isEmblem(emblem) ? emblem : 'crown';
  const label = name === undefined ? 'Bot 头像' : `${name} 头像`;
  const style: CSSProperties = {
    width: `${size}px`,
    height: `${size}px`
  };


  return (
    <span className={className === undefined ? 'bot-avatar' : `bot-avatar ${className}`} style={style}>
      {imageUrl === undefined || imageUrl === '' ? (
        <svg
          width={size}
          height={size}
          viewBox={safeEmblem.startsWith('px-') ? '0 0 24 24' : '0 0 18 18'}
          role="img"
          aria-label={`${label} · ${EMBLEM_LABELS[safeEmblem]}`}
          fill={safeEmblem.startsWith('px-') ? 'currentColor' : 'none'}
          stroke={safeEmblem.startsWith('px-') ? 'none' : 'currentColor'}
          strokeWidth="1.2"
          strokeLinecap="square"
          strokeLinejoin="miter"
          focusable="false"
        >
          <path d={EMBLEM_PATHS[safeEmblem]} />
        </svg>
      ) : (
        <img src={imageUrl} alt={label} width={size} height={size} className="bot-avatar__image" />
      )}
    </span>
  );
}
