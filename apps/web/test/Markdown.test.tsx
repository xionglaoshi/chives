import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { DeliverableDto } from '@chives/server/protocol';
import { Markdown, isSignedPercent, matchDeliverable } from '../src/components/Markdown';

const deliverable: DeliverableDto = {
  id: 'd1',
  taskId: 't1',
  botId: 'expert',
  path: 'reports/宁德时代-三季报.md',
  kind: 'markdown',
  size: 1024,
  createdAt: '2026-11-16T10:00:00.000Z'
};

describe('Markdown links', () => {
  it('opens a matching relative deliverable instead of navigating', () => {
    const onOpen = vi.fn();
    render(
      <Markdown deliverables={[deliverable]} onOpenDeliverable={onOpen}>
        {'[三季报](reports/宁德时代-三季报.md)'}
      </Markdown>
    );
    const link = screen.getByRole('button', { name: '三季报' });
    fireEvent.click(link);
    expect(onOpen).toHaveBeenCalledWith(deliverable, link);
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('matches ./ prefixes, percent-encoding, and a unique basename', () => {
    expect(matchDeliverable('./reports/宁德时代-三季报.md', [deliverable])).toBe(deliverable);
    expect(
      matchDeliverable('reports/%E5%AE%81%E5%BE%B7%E6%97%B6%E4%BB%A3-%E4%B8%89%E5%AD%A3%E6%8A%A5.md', [
        deliverable
      ])
    ).toBe(deliverable);
    expect(matchDeliverable('宁德时代-三季报.md', [deliverable])).toBe(deliverable);
  });

  it('renders an unmatched relative link as non-clickable code', () => {
    render(<Markdown deliverables={[deliverable]}>{'[别的文件](notes/missing.md)'}</Markdown>);
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.queryByRole('button', { name: '别的文件' })).toBeNull();
    const literal = screen.getByText('别的文件');
    expect(literal.tagName).toBe('CODE');
    expect(literal.className).toContain('md-link-literal');
  });

  it('renders app-internal paths as code and never as a link', () => {
    const { container } = render(
      <Markdown deliverables={[deliverable]}>
        {'[首页](#/bots) [外部](/api/bots) [邮件](mailto:a@b.com)'}
      </Markdown>
    );
    expect(container.querySelectorAll('a')).toHaveLength(0);
    expect(container.querySelectorAll('.md-link-literal')).toHaveLength(3);
  });

  it('opens absolute http(s) links in a new window with safe rel', () => {
    render(<Markdown>{'[公告](https://example.com/a)'}</Markdown>);
    const link = screen.getByRole('link', { name: '公告' });
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toBe('noopener noreferrer');
  });

  it('turns relative links into code when there is no deliverable context', () => {
    render(<Markdown>{'[报告](reports/a.md)'}</Markdown>);
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.getByText('报告').tagName).toBe('CODE');
  });
});

const imageDeliverable: DeliverableDto = {
  id: 'd2',
  taskId: 't1',
  botId: 'research',
  path: 'lg_strategy_20261117/chart_liugong_20261117.png',
  kind: 'image',
  size: 2048,
  createdAt: '2026-11-17T10:00:00.000Z'
};

describe('CJK emphasis', () => {
  it.each([
    ['**结论：柳工处于"低估值"状态。**大盘缩量…', '结论：柳工处于"低估值"状态。'],
    ['**−9.1%**，扣非', '−9.1%'],
    ['（**8.05 元**）', '8.05 元'],
    ['**柳工下破7.76（减半线）**：', '柳工下破7.76（减半线）']
  ])('renders %s as bold without asterisks', (source, expected) => {
    const { container } = render(<Markdown>{source}</Markdown>);
    const strong = container.querySelector('strong');
    expect(strong).not.toBeNull();
    expect(strong?.textContent).toBe(expected);
    expect(container.textContent).not.toContain('**');
  });
});

describe('pseudo headings', () => {
  it('marks a bold-only paragraph as a section heading', () => {
    const { container } = render(<Markdown>{'**五、反证与不确定性**'}</Markdown>);
    const paragraph = container.querySelector('p');
    expect(paragraph?.className).toContain('md-pseudo-heading');
    expect(paragraph?.querySelector('strong')?.textContent).toBe('五、反证与不确定性');
  });

  it('keeps a bold-prefixed paragraph in flow with a lead class', () => {
    const { container } = render(<Markdown>{'**结论：**柳工处于防御区间。'}</Markdown>);
    const paragraph = container.querySelector('p');
    expect(paragraph?.className).toContain('md-pseudo-lead');
    expect(paragraph?.className).not.toContain('md-pseudo-heading');
    expect(paragraph?.querySelector('strong')?.textContent).toBe('结论：');
  });
});

describe('signed percentage colouring', () => {
  it('recognises only signed percentages', () => {
    expect(isSignedPercent('+3.34%')).toBe(true);
    expect(isSignedPercent('−9.05%')).toBe(true);
    expect(isSignedPercent('-0.12%')).toBe(true);
    expect(isSignedPercent('3%')).toBe(false);
    expect(isSignedPercent('+1.2 元')).toBe(false);
  });

  it('colours inline percentages and leaves unsigned numbers alone', () => {
    const { container } = render(
      <Markdown>{'今日 +3.34%，昨日 −9.05%，持平 -0.12%，量能 3%。'}</Markdown>
    );
    expect(container.querySelectorAll('.md-up')).toHaveLength(1);
    expect(container.querySelectorAll('.md-down')).toHaveLength(2);
    expect(container.querySelector('.md-up')?.textContent).toBe('+3.34%');
    expect(container.textContent).toContain('量能 3%。');
    expect(container.querySelector('p')?.textContent).not.toContain('md-up');
  });

  it('colours a signed percentage inside bold text', () => {
    const { container } = render(<Markdown>{'**−9.1%**，扣非增速回落。'}</Markdown>);
    const strong = container.querySelector('strong');
    expect(strong?.querySelector('.md-down')?.textContent).toBe('−9.1%');
  });

  it('colours percentages inside table cells', () => {
    const { container } = render(
      <Markdown>{'| 标的 | 涨跌 |\n| --- | --- |\n| 柳工 | +3.34% |\n| 三一 | −9.05% |'}</Markdown>
    );
    expect(container.querySelector('td .md-up')?.textContent).toBe('+3.34%');
    expect(container.querySelector('td .md-down')?.textContent).toBe('−9.05%');
  });
});

describe('markdown images', () => {
  it('resolves a relative image to its matching deliverable and opens the preview', () => {
    const onOpen = vi.fn();
    render(
      <Markdown
        botId="expert"
        deliverables={[imageDeliverable]}
        onOpenDeliverable={onOpen}
      >
        {'![柳工日线](lg_strategy_20261117/chart_liugong_20261117.png)'}
      </Markdown>
    );
    const image = screen.getByRole('img', { name: '柳工日线' });
    expect(image.getAttribute('src')).toBe('/api/deliverables/d2/content');
    expect(screen.getByText('柳工日线').tagName).toBe('FIGCAPTION');
    const zoom = screen.getByRole('button', { name: '查看大图：柳工日线' });
    fireEvent.click(zoom);
    expect(onOpen).toHaveBeenCalledWith(imageDeliverable, zoom);
  });

  it('falls back to a file name match for delegated child images', () => {
    const childImage: DeliverableDto = {
      ...imageDeliverable,
      path: 'research/output/chart_liugong_20261117.png'
    };
    render(
      <Markdown botId="expert" deliverables={[childImage]}>
        {'![日线](lg_strategy_20261117/chart_liugong_20261117.png)'}
      </Markdown>
    );
    expect(screen.getByRole('img').getAttribute('src')).toBe('/api/deliverables/d2/content');
  });

  it('ignores absolute image paths even when a file name matches', () => {
    render(
      <Markdown botId="expert" deliverables={[imageDeliverable]}>
        {'![图](/lg_strategy_20261117/chart_liugong_20261117.png)'}
      </Markdown>
    );
    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.getByText('图片未找到：chart_liugong_20261117.png')).toBeTruthy();
  });

  it('uses the bot file endpoint when no deliverable matches', () => {
    render(<Markdown botId="expert">{'![图](reports/chart.png)'}</Markdown>);
    expect(screen.getByRole('img').getAttribute('src')).toBe(
      '/api/bots/expert/files/content?path=reports%2Fchart.png'
    );
  });

  it('does not load http images but shows them as an external link', () => {
    const { container } = render(
      <Markdown>{'![远端图](https://example.com/chart.png)'}</Markdown>
    );
    expect(container.querySelector('img')).toBeNull();
    const link = screen.getByRole('link', { name: '外链图片：远端图' });
    expect(link.getAttribute('href')).toBe('https://example.com/chart.png');
    expect(link.getAttribute('rel')).toBe('noopener noreferrer');
  });

  it('shows a missing card instead of a broken image on load failure', () => {
    render(<Markdown botId="expert">{'![图](reports/missing.png)'}</Markdown>);
    fireEvent.error(screen.getByRole('img'));
    expect(screen.getByText('图片未找到：missing.png')).toBeTruthy();
    expect(screen.queryByRole('img')).toBeNull();
  });

  it('shows a missing card when no bot or deliverable can resolve the path', () => {
    render(<Markdown>{'![图](reports/chart.png)'}</Markdown>);
    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.getByText('图片未找到：chart.png')).toBeTruthy();
  });

  it('resolves images against the Markdown directory first and the root on failure', () => {
    render(
      <Markdown botId="expert" baseDir="reports/000528-柳工">
        {'![图](charts/pe.png)'}
      </Markdown>
    );
    const image = screen.getByRole('img');
    const resolved = new URL(image.getAttribute('src') ?? '', 'http://localhost');
    expect(resolved.searchParams.get('path')).toBe('reports/000528-柳工/charts/pe.png');
    fireEvent.error(image);
    const fallback = new URL(screen.getByRole('img').getAttribute('src') ?? '', 'http://localhost');
    expect(fallback.searchParams.get('path')).toBe('charts/pe.png');
  });

  it('normalizes ../ image paths from a nested report directory', () => {
    render(
      <Markdown botId="expert" baseDir="reports/000528-柳工">
        {'![图](../../charts/pe.png)'}
      </Markdown>
    );
    const resolved = new URL(screen.getByRole('img').getAttribute('src') ?? '', 'http://localhost');
    expect(resolved.searchParams.get('path')).toBe('charts/pe.png');
  });

  it('opens the image address when there is no deliverable to preview', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    render(<Markdown botId="expert">{'![图](reports/chart.png)'}</Markdown>);
    fireEvent.click(screen.getByRole('button', { name: '查看大图：图' }));
    expect(open).toHaveBeenCalledWith(
      '/api/bots/expert/files/content?path=reports%2Fchart.png',
      '_blank',
      'noopener,noreferrer'
    );
    open.mockRestore();
  });
});
