import type {ComposerModelChoice, ModelTuning} from '../api/protocol.js';
import {randomUUID} from 'node:crypto';
import {mkdirSync,existsSync,readFileSync,writeFileSync,renameSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import type {Store} from '../store/index.js';
import {AppError} from '../errors.js';
import {ModelProviderStore, parseModelProvider, type ModelProviderConfig} from './model-provider.js';

export interface BotModelPick {model:string; tuning?:ModelTuning}

export function tuningOf(config:ModelTuning):ModelTuning {
  return {...(config.reasoningEffort ? {reasoningEffort:config.reasoningEffort} : {}),
          ...(config.fastMode ? {fastMode:true} : {})};
}

function selectedConfig(entry:ModelProviderConfig, pick?:BotModelPick):ModelProviderConfig {
  if (!pick || (entry.api!=='openai-codex-subscription' && pick.model!==entry.model)) return entry;
  const {reasoningEffort, fastMode, ...base}=entry;
  const tuning=pick.tuning ?? (pick.model===entry.model ? tuningOf(entry) : {});
  if(entry.api!=='openai-codex-subscription' && !(entry.api==='openai-completions' && entry.deepseekThinking))
    return {...base, model:pick.model};
  return {...base,model:pick.model,...tuning};
}

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
  activeId(){return this.store.settings.get<string>(selectedKey)??'original';}
  private file(id:string){return join(this.data,'secrets','providers',id);}
  private key(id:string){
    if(existsSync(this.file(id)))return readFileSync(this.file(id),'utf8');
    if(id==='original'&&this.activeId()===id)return this.provider.currentKey();
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
    const id=this.activeId()||'original',config=this.provider.read(),key=this.provider.currentKey();
    const records=saved.filter(r=>r.id!==id);
    if(config){records.push({...config,id});if(key)this.putKey(id,key);else rmSync(this.file(id),{force:true});}
    else rmSync(this.file(id),{force:true});
    this.store.settings.set(catalogKey,records);
    this.store.settings.set(selectedKey,config?id:'');
  }
  entry(id: string){return this.records().find(row=>row.id===id);}
  configFor(id:string, pick?:BotModelPick) {
    const entry=this.entry(id);
    return entry && selectedConfig(entry,pick);
  }
  async composerChoices() {
    const needsSubscription=this.records().some(entry=>entry.api==='openai-codex-subscription');
    const status=needsSubscription ? await this.provider.subscription.status().catch(()=>null) : null;
    const choices:ComposerModelChoice[]=[];
    for (const entry of this.list()) {
      if (entry.api==='openai-codex-subscription') {
        if (!status?.authorized) continue;
        for (const model of status.models) choices.push({
          model, subscription:true, connection:entry.id, label:entry.displayName || 'Codex 订阅',
          defaults:model===entry.model ? tuningOf(entry) : {}, ...(status.capabilities[model] ?? {efforts:[],fast:false})
        });
      } else if (entry.keyConfigured) {
        choices.push({model:entry.model, subscription:false, connection:entry.id, label:entry.displayName || entry.model,
          defaults:tuningOf(entry), ...await this.provider.capabilities(entry)});
      }
    }
    return {choices, subscriptionUnavailable:needsSubscription && !status?.authorized};
  }
  async composerPreference(input:Record<string,unknown>) {
    let preference:{kernel:'dsh';connection:string;model:string;pick?:BotModelPick}={kernel:'dsh',connection:'',model:''};
    if (input.followGlobal===true) {
      if(Object.keys(input).length!==1) throw new AppError(400,'invalid_selection','跟随全局时无需另选参数');
    } else {
      if (Object.keys(input).some(k=>!['connection','model','tuning'].includes(k)))
        throw new AppError(400,'invalid_selection','无法识别模型选择参数');
      const {choices}=await this.composerChoices();
      const choice=choices.find(c=>c.connection===input.connection && c.model===input.model);
      if(!choice) throw new AppError(409,'unavailable_model','该模型当前不可用，请刷新模型列表');
      const pick:BotModelPick={model:choice.model};
      if(input.tuning!==undefined) {
        const t=input.tuning;
        if(!t || typeof t!=='object' || Array.isArray(t) || Object.keys(t).some(k=>k!=='fastMode' && k!=='reasoningEffort'))
          throw new AppError(400,'invalid_tuning','无法识别模型参数');
        const {reasoningEffort,fastMode}=t as Record<string,unknown>;
        const effort=choice.efforts.find(e=>e===reasoningEffort);
        if(reasoningEffort!==undefined && !effort) throw new AppError(400,'invalid_effort','此模型不支持所选思考强度');
        if(fastMode!==undefined && (typeof fastMode!=='boolean' || (fastMode && !choice.fast)))
          throw new AppError(400,'invalid_speed','此模型不支持所选速度');
        pick.tuning={...(effort ? {reasoningEffort:effort} : {}), ...(fastMode ? {fastMode:true} : {})};
      }
      preference={...preference,connection:choice.connection,pick};
    }
    return preference;
  }
  runtime(id:string,botId:string,pick?:BotModelPick){
    const cfg=this.configFor(id,pick), key=cfg && this.key(id);
    if(!cfg || (!key && cfg.api!=='openai-codex-subscription'))throw new AppError(409,'missing_connection','请在 Bot 档案中重新选择有效模型连接');
    return this.provider.runtimeFor(cfg,key||'',botId);
  }
  list(){return this.records().map(r=>({...r,active:r.id===this.activeId(),keyConfigured:!!this.key(r.id)}));}
  async perform(action:unknown,body:Record<string,unknown>):Promise<unknown>{
    if(action==='subscription-status')return this.provider.subscription.status();
    if(action==='subscription-cancel'){this.provider.subscription.cancel();return {};}
    if(action==='subscription-login')return this.provider.subscription.login(body.device===true);
    const records=this.records(),id=String(body.id??''),old=records.find(x=>x.id===id);
    if(action==='activate'||action==='delete'){
      if(!old)throw new AppError(404,'missing','找不到这个模型');
      if(this.activeId()==='original'&&this.key('original'))this.putKey('original',this.key('original'));
      if(action==='activate'){
        const {id:_,...cfg}=old;
        this.provider.write(cfg,this.key(id)||null);this.store.settings.set(selectedKey,id);
      }else{
        this.store.settings.set(catalogKey,records.filter(r=>r.id!==id));
        if(id===this.activeId()){this.provider.clear();this.store.settings.set(selectedKey,'');}
        rmSync(this.file(id),{force:true});
      }
      return this.list();
    }
    if(action==='initialize-save'){
      const input=body.config as Record<string,unknown>|undefined;
      if(!input||!['openai-completions','openai-responses','anthropic-messages'].includes(String(input.api)))
        throw new AppError(400,'model_protocol','请选择可用的 API 协议。');
      const config={baseURL:input.baseURL,api:input.api};
      const discovered=await this.perform('discover',{config,key:body.key}) as {models:string[]};
      const model=discovered.models[0];
      if(!model)throw new AppError(400,'model_unavailable','供应商未返回可用模型。');
      const selected={...config,model};
      await this.perform('probe',{config:selected,key:body.key});
      const entries=await this.perform('save',{config:selected,key:body.key}) as ReturnType<ModelLibrary['list']>;
      const entry=entries.at(-1);
      if(entry&&!entry.active)return this.perform('activate',{id:entry.id});
      return entries;
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
      if(target===this.activeId()||!this.provider.read()){this.provider.write(cfg,null);this.store.settings.set(selectedKey,target);}
      return this.list();
    }
    await this.provider.validateTuning(cfg);
    const key=typeof body.key==='string'&&body.key.trim()?body.key.trim():old&&old.baseURL===cfg.baseURL?this.key(id):'';
    if(!key||/[\r\n]/.test(key))throw new AppError(400,'missing_key','请为这个服务地址填写 API Key');
    if(action==='save'||tuning){
      const target=old?.id??randomUUID();
      this.putKey(target,key);
      this.store.settings.set(catalogKey,[...this.records().filter(x=>x.id!==target),{...cfg,id:target}]);
      if(target===this.activeId()||!this.provider.read()){
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
