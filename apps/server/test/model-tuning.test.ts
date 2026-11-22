import {mkdtempSync,rmSync,readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {parse} from 'yaml';
import {Store} from '../src/store/index.js';
import {ModelLibrary} from '../src/settings/model-library.js';
import {ModelProviderStore} from '../src/settings/model-provider.js';
import {codexBase} from '../src/settings/codex-subscription.js';

let dir:string,store:Store,provider:ModelProviderStore,library:ModelLibrary;
const cfg={api:'openai-codex-subscription',baseURL:codexBase,model:'fixture',deepseekThinking:false};
beforeEach(()=>{
  dir=mkdtempSync(join(tmpdir(),'chives-tuning-'));
  store=Store.open(dir);provider=new ModelProviderStore(store,dir);library=new ModelLibrary(store,dir,provider);
  vi.spyOn(provider.subscription,'status').mockResolvedValue({authorized:true,models:['fixture'],failed:false,
    capabilities:{fixture:{efforts:['low','high'],fast:true}}});
});
afterEach(()=>{store.close();rmSync(dir,{recursive:true,force:true});});

it('shares the saved connection with new Bot processes, including terminal changes and clearing both overrides',async()=>{
  await library.perform('save',{config:{...cfg,reasoningEffort:'high',fastMode:true}});
  const id=library.list()[0]!.id;
  const patch=()=>parse(readFileSync(library.runtime(id,'operator').patchPath,'utf8'));
  expect(patch()[0].config.providers['openai-codex'].reasoning).toBe('high');
  expect(patch()[1].insert[0].config.fastMode).toBe(true);
  expect(provider.runtime('another-model','other')?.reasoningEffort).toBeUndefined();
  expect(parse(readFileSync(provider.runtime('another-model','other')!.patchPath,'utf8'))[1].insert[0].config.fastMode).toBe(false);
  await library.perform('tune',{id,reasoningEffort:'low'});
  expect(provider.read()?.reasoningEffort).toBe('low');
  await library.perform('tune',{id});
  expect(patch()[0].config.providers['openai-codex'].reasoning).toBeUndefined();
  expect(patch()[1].insert[0].config.fastMode).toBe(false);
});

it('rejects an unsupported setting before overwriting a saved connection',async()=>{
  await library.perform('save',{config:cfg});
  const id=library.list()[0]!.id;
  await expect(library.perform('tune',{id,reasoningEffort:'max'})).rejects.toThrow('不支持');
  expect(provider.read()?.reasoningEffort).toBeUndefined();
  await expect(library.perform('save',{config:{...cfg,api:'anthropic-messages',fastMode:true}})).rejects.toThrow('快速模式');
});

it('binds a subscription variant and its tuning to one bot without editing the connection',async()=>{
  vi.mocked(provider.subscription.status).mockResolvedValue({authorized:true,failed:false,
    models:['fixture','second'],capabilities:{fixture:{efforts:['high'],fast:false},second:{efforts:['low'],fast:true}}});
  await library.perform('save',{config:{...cfg,reasoningEffort:'high'}});
  const id=library.list()[0]!.id;
  const {pick}=await library.composerPreference({connection:id,model:'second',tuning:{reasoningEffort:'low',fastMode:true}});
  const runtime=library.runtime(id,'operator',pick);
  expect(runtime.route.model).toBe('second');
  expect(runtime.reasoningEffort).toBe('low');
  expect(parse(readFileSync(runtime.patchPath,'utf8'))[1].insert[0].config.fastMode).toBe(true);
  expect(library.runtime(id,'other').route.model).toBe('fixture');
  expect(provider.read()?.reasoningEffort).toBe('high');
  await expect(library.composerPreference({connection:id,model:'fixture',tuning:{fastMode:true}})).rejects.toThrow('速度');
  await expect(library.composerPreference({connection:id,model:'second',tuning:{reasoningEffort:'high'}})).rejects.toThrow('强度');
  await expect(library.composerPreference({connection:id,model:'removed'})).rejects.toThrow('不可用');
  expect(await library.composerPreference({followGlobal:true})).toEqual({kernel:'dsh',model:'',connection:''});
});

it('keeps manual connections usable when the subscription is unavailable',async()=>{
  await library.perform('save',{config:cfg});
  await library.perform('save',{key:'test',config:{model:'manual',api:'openai-completions',baseURL:'http://localhost/v1',deepseekThinking:true}});
  vi.mocked(provider.subscription.status).mockRejectedValue(new Error('offline'));
  const catalog=await library.composerChoices();
  expect(catalog.subscriptionUnavailable).toBe(true);
  expect(catalog.choices).toEqual([expect.objectContaining({model:'manual',subscription:false,efforts:['high','max'],fast:false})]);
});
