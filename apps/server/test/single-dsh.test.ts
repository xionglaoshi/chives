import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {expect,it,vi} from 'vitest';
import {KernelManager,selectedVersion} from '../src/harness/kernel-manager.js';

it('upgrades only the checked version after verification and retains it on restart',async()=>{
  const dir=mkdtempSync(join(tmpdir(),'dsh-test-'));
  try{
    const reload=vi.fn(async()=>{});
    const verify=vi.fn(async()=>{});
    const manager=new KernelManager(dir,reload,async()=>'1.0.0',verify);
    const start=selectedVersion(dir);
    await expect(manager.upgrade('1.0.0')).rejects.toThrow();
    await manager.check();
    expect(selectedVersion(dir)).toBe(start);
    await expect(manager.upgrade('9.9.9')).rejects.toThrow();
    verify.mockRejectedValueOnce(new Error('failed smoke test'));
    await expect(manager.upgrade('1.0.0')).rejects.toThrow();
    expect(selectedVersion(dir)).toBe(start);
    await manager.upgrade('1.0.0');
    expect(reload).toHaveBeenCalledTimes(1);
    expect(new KernelManager(dir,reload).snapshot().current).toBe('1.0.0');
    await expect(manager.upgrade('1.0.0')).rejects.toThrow();
  }finally{rmSync(dir,{recursive:true,force:true});}
});

it('runs two saved model connections independently of the global provider',async()=>{
  const {Store}=await import('../src/store/index.js');
  const {ModelProviderStore}=await import('../src/settings/model-provider.js');
  const {ModelLibrary}=await import('../src/settings/model-library.js');
  const dir=mkdtempSync(join(tmpdir(),'dsh-models-'));
  const store=Store.open(dir);
  try{
    const provider=new ModelProviderStore(store,dir);
    const library=new ModelLibrary(store,dir,provider);
    const config={baseURL:'https://first.example/v1',api:'openai-completions',model:'first',deepseekThinking:false};
    await library.perform('save',{config,key:'fixture-first'});
    await library.perform('save',{config:{...config,baseURL:'https://second.example/v1',model:'second'},key:'fixture-second'});
    const alternate=library.list().find(row=>row.model==='second')!;
    const applied=library.runtime(alternate.id,'research');
    expect(applied.route.model).toBe('second');
    expect(applied.env.CHIVES_MODEL_API_KEY).toBe('fixture-second');
    expect(provider.runtime()?.route.model).toBe('first');
    expect(provider.currentKey()).toBe('fixture-first');
  }finally{store.close();rmSync(dir,{recursive:true,force:true});}
});
