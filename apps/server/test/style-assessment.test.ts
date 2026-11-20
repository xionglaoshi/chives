import {expect,it,vi} from 'vitest';
import {StyleAssessment,assessmentKey} from '../src/settings/style-assessment.js';
import type {ModelProviderStore} from '../src/settings/model-provider.js';
import type {Store} from '../src/store/index.js';

it('keeps capacity distinct from trades and retains the previous assessment on failure',async()=>{
  const store={settings:new Map<string,unknown>()} as unknown as Store;
  const provider={read:()=>({api:'openai-completions',baseURL:'http://example.invalid'}),currentKey:()=>'fixture'} as ModelProviderStore;
  const service=new StyleAssessment(store,provider,()=>'test');
  const summary={philosophy:'价值',style:'长期',industries:'待确认',analogy:'证据不足',riskBehavior:'仅作参考',evidence:'问卷'};
  const fetcher=vi.fn(async()=>Response.json({choices:[{message:{content:JSON.stringify(summary)}}]}));
  vi.stubGlobal('fetch',fetcher);
  try{
    await expect(service.evaluate({mode:'supplement',revision:null})).rejects.toThrow('先完成');
    const answers={liquidity:4,reserve:4,loss:0,experience:4,knowledge:4,reaction:4,philosophy:'现金流',industries:''};
    const first=await service.evaluate({mode:'questionnaire',revision:null,answers});
    expect(first.result?.grade).toBe(1);
    const body={mode:'supplement',revision:first.result!.updated,materials:[{name:'trades.csv',text:'短线试仓'}]};
    const second=await service.evaluate(body);
    expect(second.result?.grade).toBe(1);
    expect(JSON.stringify(fetcher.mock.calls.at(-1))).toContain('短线试仓');
    expect(JSON.stringify(fetcher.mock.calls.at(-1))).toContain('现金流');
    expect(JSON.stringify(service.botContext())).not.toContain('trades.csv');
    const before=store.settings.get(assessmentKey);
    fetcher.mockResolvedValueOnce(Response.json({choices:[]}));
    await expect(service.evaluate({...body,revision:second.result!.updated})).rejects.toThrow('上次画像已保留');
    expect(store.settings.get(assessmentKey)).toEqual(before);
    await expect(service.evaluate({...body,revision:'outdated'})).rejects.toThrow('刷新');
  }finally{vi.unstubAllGlobals();}
});
