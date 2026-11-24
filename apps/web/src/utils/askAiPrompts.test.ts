import { describe, expect, it } from 'vitest';
import { askAiPrompts, fillAskPrompt } from './askAiPrompts';

const headings = ['这是什么', '入榜意味着什么', '要读哪些文件', '重点回答哪些问题', '不要做什么'];
const closing = '直接回答本按钮列出的问题。不要质疑或审计数据版本、采集过程、时滞或来源质量，不要自行扩大范围。依据不足时略过对应判断，继续回答其余问题。只在对话中简洁回答。';

function templates(value: object, path = ''): Array<[string, string]> {
  return Object.entries(value).flatMap(([key, child]) => {
    const name = path ? path + '/' + key : key;
    if (key === '名称') return [];
    return typeof child === 'string' ? [[name, child]] : templates(child, name);
  });
}

describe('问AI预设提示词规范', () => {
  it.each(templates(askAiPrompts))('%s has exactly five named sections and a scope limit', (_name, prompt) => {
    const sections = prompt.split('\n\n');
    expect(sections).toHaveLength(headings.length);
    expect(sections.map(section => section.split('：', 1)[0])).toEqual(headings);
    sections.forEach((section, index) => expect(section.slice(headings[index]!.length + 1).trim()).not.toBe(''));
    expect(sections.at(-1)).toMatch(/不要自行扩大范围/);
    expect(prompt.endsWith(closing)).toBe(true);
  });

  it('fills rankings and market-specific variables in the draft text', () => {
    const board = askAiPrompts['行情看板'];
    expect(fillAskPrompt(board['个股跌停榜'], {股票数: 17, 排序: '跌幅'})).toContain('共 17 只，本次按跌幅排列');
    for (const market of ['港股', '美股']) {
      expect(fillAskPrompt(board['港美股行业热图'], {市场: market})).toContain(market + '行业热图');
    }
  });

  it.each(Object.entries(askAiPrompts['风格评估']))('%s keeps the sample report isolated', (_section, variants) => {
    expect(variants['示例报告']).toContain('要读哪些文件：只读本次示例报告附件');
    expect(variants['示例报告']).not.toContain('portfolio/holdings.json');
    expect(variants['个人报告']).toContain('profile/investor.json');
  });
});
