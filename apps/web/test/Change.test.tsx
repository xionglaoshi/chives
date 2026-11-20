import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Change, changeDirection, formatChange } from '../src/components/Change';

describe('Change', () => {
  it('renders an up arrow in red for gains', () => {
    render(<Change value={1.3} />);
    const node = screen.getByText('▲ 1.30%');
    expect(node.className).toContain('change--up');
    expect(node.getAttribute('data-direction')).toBe('up');
  });

  it('renders a down arrow in green for losses', () => {
    render(<Change value={-0.91} />);
    const node = screen.getByText('▼ 0.91%');
    expect(node.className).toContain('change--down');
    expect(node.getAttribute('data-direction')).toBe('down');
  });

  it('renders a dash without an arrow for zero', () => {
    render(<Change value={0} />);
    const node = screen.getByText('—');
    expect(node.className).toContain('change--flat');
    expect(node.textContent).not.toContain('▲');
    expect(node.textContent).not.toContain('▼');
  });

  it('exposes direction and formatting helpers', () => {
    expect(changeDirection(2)).toBe('up');
    expect(changeDirection(-2)).toBe('down');
    expect(changeDirection(0)).toBe('flat');
    expect(formatChange(-1.5)).toBe('▼ 1.50%');
    expect(formatChange(0)).toBe('—');
  });
});
