import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import GlobalSearch from '../src/components/GlobalSearch';
import { searchEntries } from '../src/utils/globalSearch';
import { jsonResponse, makeBot } from './testUtils';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function open() {
  const locate = vi.fn();
  render(<GlobalSearch bots={[makeBot({id:'research',name:'研究员'})]} currentBot={null}
    onLocate={locate} onClose={() => undefined} onTimeline={() => undefined}/>);
  return {locate,input:screen.getByRole('searchbox')};
}
describe('global search', () => {
  it('ranks the model setting and finds actual help sections, terminal and workspace entries', () => {
    expect(searchEntries('思考强度',[])[0]?.destination).toEqual({hash:'#/settings?tab=models'});
    expect(searchEntries('卸载',[])).toContainEqual(expect.objectContaining({title:'卸载',destination:expect.objectContaining({source:'INSTALL.md',body:expect.stringContaining('yes')})}));
    expect(searchEntries('/MODEL',[])[0]?.title).toBe('/model');
    expect(searchEntries('热门榜单',[])[0]?.destination).toEqual({hash:'#/workspace/trends'});
  });
  it('opens the selected command by keyboard and keeps the query on return', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({hits:[],more:false})));
    const {input} = open();
    fireEvent.click(screen.getByRole('button',{name:'命令',exact:true}));
    fireEvent.change(input,{target:{value:'/model'}});
    fireEvent.keyDown(input,{key:'Enter'});
    expect(screen.getByRole('heading',{name:'/model'})).toBeTruthy();
    expect(screen.getByRole('link',{name:'打开模型设置'}).getAttribute('href')).toBe('#/settings?tab=models');
    fireEvent.keyDown(screen.getByRole('button',{name:'‹ 返回搜索结果'}),{key:'Escape'});
    expect((screen.getByRole('searchbox') as HTMLInputElement).value).toBe('/model');
    expect(fetch).not.toHaveBeenCalled();
  });
  it('locates another bot’s message via the unscoped conversation endpoint',async () => {
    const hit = {botId:'research',messageId:'m42',snippet:'同步分析',createdAt:'2026-11-22T09:00:00Z'};
    const request = vi.fn(async (_url: RequestInfo | URL) => jsonResponse({hits:[hit],more:false}));
    vi.stubGlobal('fetch',request);
    const {input,locate} = open();
    fireEvent.change(input,{target:{value:'同步分析'}});
    const result = await screen.findByRole('button',{name:/研究员/});
    fireEvent.click(result);
    expect(request.mock.calls[0]?.[0]).toBe('/api/conversations/search?q=%E5%90%8C%E6%AD%A5%E5%88%86%E6%9E%90&offset=0');
    expect(locate).toHaveBeenCalledWith(hit);
  });
  it('keeps help usable if history is unavailable',async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw Error('offline'); }));
    const {input}=open();
    fireEvent.change(input,{target:{value:'卸载'}});
    await screen.findByText('暂时无法读取历史会话。');
    const help = screen.getByRole('region',{name:'帮助文档搜索结果'});
    fireEvent.click(within(help).getByRole('button',{name:/^卸载\s*INSTALL\.md$/}));
    expect(screen.getByRole('heading',{name:'卸载'})).toBeTruthy();
    expect(screen.getByText('yes')).toBeTruthy();
  });
});
