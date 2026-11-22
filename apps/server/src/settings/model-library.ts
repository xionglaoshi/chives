import {randomUUID} from 'node:crypto';
import {mkdirSync,existsSync,readFileSync,writeFileSync,renameSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import type {Store} from '../store/index.js';
import {AppError} from '../errors.js';
import {ModelProviderStore, parseModelProvider, type ModelProviderConfig} from './model-provider.js';

interface Entry extends ModelProviderConfig {id:string}
const catalogKey='provider.library.v1', selectedKey='provider.selected.v1';
export class ModelLibrary {
  constructor(private store:Store,private data:string,private provider:ModelProviderStore){}
  private records():Entry[]{
    const saved=this.store.settings.get<Entry[]>(catalogKey);
    if(saved)return saved;
    const current=this.provider.read();
    return current?[{...current,id:'original'}]:[];
  }
  private active(){return this.store.settings.get<string>(selectedKey)??'original';}
  private file(id:string){return join(this.data,'secrets','providers',id);}
  private key(id:string){
    if(existsSync(this.file(id)))return readFileSync(this.file(id),'utf8');
    if(id==='original'&&this.active()===id)return this.provider.currentKey();
    return '';
  }
  private putKey(id:string,key:string){
    const file=this.file(id),temp=file+'.'+randomUUID();
    mkdirSync(join(this.data,'secrets','providers'),{recursive:true,mode:0o700});
    writeFileSync(temp,key,{mode:0o600});renameSync(temp,file);
  }
  synchronizeLegacy(){
    const saved=this.store.settings.get<Entry[]>(catalogKey);
    if(!saved)return;
    const id=this.active()||'original',config=this.provider.read(),key=this.provider.currentKey();
    const records=saved.filter(r=>r.id!==id);
    if(config){records.push({...config,id});if(key)this.putKey(id,key);else rmSync(this.file(id),{force:true});}
    else rmSync(this.file(id),{force:true});
    this.store.settings.set(catalogKey,records);
    this.store.settings.set(selectedKey,config?id:'');
  }
  entry(id: string){return this.records().find(row=>row.id===id);}
  runtime(id:string,botId:string){
    const cfg=this.entry(id), key=cfg && this.key(id);
    if(!cfg || (!key && cfg.api!=='openai-codex-subscription'))throw new AppError(409,'missing_connection','请在 Bot 档案中重新选择有效模型连接');
    return this.provider.runtimeFor(cfg,key||'',botId);
  }
  list(){return this.records().map(r=>({...r,active:r.id===this.active(),keyConfigured:!!this.key(r.id)}));}
  async perform(action:unknown,body:Record<string,unknown>){
    if(action==='subscription-status')return this.provider.subscription.status();
    if(action==='subscription-cancel'){this.provider.subscription.cancel();return {};}
    if(action==='subscription-login')return this.provider.subscription.login(body.device===true);
    const records=this.records(),id=String(body.id??''),old=records.find(x=>x.id===id);
    if(action==='activate'||action==='delete'){
      if(!old)throw new AppError(404,'missing','找不到这个模型');
      if(this.active()==='original'&&this.key('original'))this.putKey('original',this.key('original'));
      if(action==='activate'){
        const {id:_,...cfg}=old;
        this.provider.write(cfg,this.key(id)||null);this.store.settings.set(selectedKey,id);
      }else{
        this.store.settings.set(catalogKey,records.filter(r=>r.id!==id));
        if(id===this.active()){this.provider.clear();this.store.settings.set(selectedKey,'');}
        rmSync(this.file(id),{force:true});
      }
      return this.list();
    }
    const tuning=action==='tune';
    let input=body.config;
    if(tuning || action==='capabilities'){
      if(!old)throw new AppError(404,'missing','找不到这个模型');
      if(action==='capabilities')return this.provider.capabilities(old);
      const {id:entryId,...saved}=old;
      input={...saved,reasoningEffort:body.reasoningEffort,fastMode:body.fastMode};
    }
    const cfg=parseModelProvider(action==='discover'&&input&&typeof input==='object'&&!('model' in input && input.model)?{...input,model:'discovery'}:input);
    if(cfg.api==='openai-codex-subscription'){
      const status=await this.provider.subscription.status();
      if(!status.authorized||!status.models.includes(cfg.model))throw new AppError(409,'codex_auth','请先完成 OpenAI 订阅授权并选择可用模型。');
      await this.provider.validateTuning(cfg,status.capabilities[cfg.model]);
      if(action==='probe'){
        const {sent,served}=await this.provider.subscription.complete(cfg.model,'请简短回答。','请回复 OK',cfg);
        if(sent.model!==cfg.model || (cfg.reasoningEffort && sent.effort!==cfg.reasoningEffort) || (cfg.fastMode && sent.tier!=='priority'))
          throw new AppError(502,'tuning_mismatch','请求参数与所选设置不符');
        const tier=(value:string|null|undefined)=>value==='default'?'标准':value==='priority'||value==='fast'?'快速':value??'未报告';
        return {message:'已请求 '+sent.model+' · 思考 '+(sent.effort??'跟随模型')+' · '+(sent.tier?'快速':'标准')+
          '。服务端回报 '+(served?.model??'未报告模型')+' · 思考 '+(served?.effort??'未报告')+' · '+tier(served?.tier)+'。'};
      }
      if(action!=='save'&&!tuning)throw new AppError(400,'action','无效的订阅操作');
      const current=this.records();
      const target=old?.id??current.find(r=>r.api===cfg.api&&r.model===cfg.model)?.id??randomUUID();
      this.store.settings.set(catalogKey,[...current.filter(r=>r.id!==target),{...cfg,id:target}]);
      if(target===this.active()||!this.provider.read()){this.provider.write(cfg,null);this.store.settings.set(selectedKey,target);}
      return this.list();
    }
    await this.provider.validateTuning(cfg);
    const key=typeof body.key==='string'&&body.key.trim()?body.key.trim():old&&old.baseURL===cfg.baseURL?this.key(id):'';
    if(!key||/[\r\n]/.test(key))throw new AppError(400,'missing_key','请为这个服务地址填写 API Key');
    if(action==='save'||tuning){
      const target=old?.id??randomUUID();
      this.putKey(target,key);
      this.store.settings.set(catalogKey,[...this.records().filter(x=>x.id!==target),{...cfg,id:target}]);
      if(target===this.active()||!this.provider.read()){
        this.provider.write(cfg,key);this.store.settings.set(selectedKey,target);
      }
      return this.list();
    }
    if(action!=='discover'&&action!=='probe')throw new AppError(400,'invalid','不支持的操作');
    const anth=cfg.api==='anthropic-messages';
    const headers:Record<string,string>={'Content-Type':'application/json',...(anth?{'x-api-key':key,'anthropic-version':'2023-06-01'}:{Authorization:'Bearer '+key})};
    const base=cfg.baseURL.replace(/\/$/,'');
    const endpoint=anth&&!base.endsWith('/v1')?base+'/v1':base;
    const path=action==='discover'?'/models':anth?'/messages':cfg.api==='openai-responses'?'/responses':'/chat/completions';
    const payload=action==='discover'?undefined:cfg.api==='openai-responses'?{model:cfg.model,input:'Reply OK',max_output_tokens:32}:{model:cfg.model,messages:[{role:'user',content:'Reply OK'}],max_tokens:cfg.reasoningEffort?512:32,...(cfg.reasoningEffort?{thinking:{type:'enabled'},reasoning_effort:cfg.reasoningEffort}:{})};
    const resp=await fetch(endpoint+path,{method:payload?'POST':'GET',headers,...(payload?{body:JSON.stringify(payload)}:{}),redirect:'error',signal:AbortSignal.timeout(25000)});
    if(!resp.ok)throw new AppError(400,'provider_error','供应商返回 HTTP '+resp.status+'，请检查地址、权限和模型 ID');
    const result=await resp.json() as {data?:{id:string}[];choices?:unknown[];output?:unknown[];content?:unknown[]};
    if(action==='discover'){
      if(!Array.isArray(result.data))throw new AppError(400,'provider_error','服务没有返回模型清单');
      return {models:result.data.map(m=>m.id).filter(id=>typeof id==='string')};
    }
    if(!(result.choices?.length||result.output?.length||result.content?.length))throw new AppError(400,'provider_error','推理端点未返回有效结果');
    return {message:'模型已响应测试请求'};
  }
}
