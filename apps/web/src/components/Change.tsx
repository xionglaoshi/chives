import type { ReactElement } from 'react';

import './Change.css';

export type ChangeDirection = 'up' | 'down' | 'flat';

export interface ChangeProps {
  value: number;
  digits?: number;
  suffix?: string;
  className?: string | undefined;
}

export function changeDirection(value: number): ChangeDirection {
  if (!Number.isFinite(value) || value === 0) return 'flat';
  return value > 0 ? 'up' : 'down';
}

export function formatChange(value: number, digits = 2, suffix = '%'): string {
  if (!Number.isFinite(value) || value === 0) return '—';
  const arrow = value > 0 ? '▲' : '▼';
  return `${arrow} ${Math.abs(value).toFixed(digits)}${suffix}`;
}

/**
 * Price change. The up/down colours follow the saved `data-change-color`
 * setting (red-up by default), always with an arrow. Zero is a plain dash.
 */
export function Change({ value, digits = 2, suffix = '%', className }: ChangeProps): ReactElement {
  const direction = changeDirection(value);
  const classes = ['change', `change--${direction}`];
  if (className !== undefined) classes.push(className);
  const text = formatChange(value, digits, suffix);
  const label =
    direction === 'flat' ? '持平' : `${direction === 'up' ? '上涨' : '下跌'} ${Math.abs(value).toFixed(digits)}${suffix}`;

  return (
    <span className={classes.join(' ')} data-direction={direction} aria-label={label}>
      {text}
    </span>
  );
}
