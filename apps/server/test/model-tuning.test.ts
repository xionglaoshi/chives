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
