import type { ReactElement } from 'react';

export interface ExpertSidebarSparklineProps {
  values: number[];
  label: string;
}

/** A tiny intraday line; renders nothing when there is no usable series. */
export function ExpertSidebarSparkline({
  values,
  label
}: ExpertSidebarSparklineProps): ReactElement | null {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min === 0 ? 1 : max - min;
  const points = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * 100;
      const y = 30 - ((value - min) / span) * 26;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(' ');
  const up = values[values.length - 1]! >= values[0]!;

  return (
    <svg
      className={`expert-sidebar__spark expert-sidebar__spark--${up ? 'up' : 'down'}`}
      viewBox="0 0 100 32"
      preserveAspectRatio="none"
      role="img"
      aria-label={`${label} 当日分时`}
    >
      <polyline points={points} fill="none" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
