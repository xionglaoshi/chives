import {BotModelSettings} from './KernelSettings';
import './KernelSettings.css';
import {effortNames} from "./modelTuning";
import {useState,useEffect} from 'react';
import {readModelFile,type ImportedModel} from './importModel';
import {desk} from './deskApi';
import {listBots} from '../api/client';
import type {BotSummary,ModelReceipt,ModelTuning,ModelCapabilities,ReasoningEffort} from '@chives/server/protocol';
import {Row} from './DeskPanels';
type Config=ModelTuning&{baseURL:string;model:string;displayName:string;api:string;deepseekThinking:boolean;contextWindow?:number;maxTokens?:number};
type Entry=Config&{id:string;active:boolean;keyConfigured:boolean};
const blank:Config={baseURL:'https://api.deepseek.com/v1',model:'deepseek-flash',displayName:'',api:'openai-completions',deepseekThinking:true};
function tuningOf(c:ModelTuning):ModelTuning {
 return {...(c.reasoningEffort?{reasoningEffort:c.reasoningEffort}:{}),...(c.fastMode?{fastMode:true}:{})};
}
export function ModelsDesk({initialize=false,onInitialized}:{initialize?:boolean;onInitialized?:(()=>void)|undefined}={}){
 const [entries,set]=useState<Entry[]>([]),[mode,show]=useState(''),[id,sel]=useState(''),[config,edit]=useState<Config>(blank),[key,setKey]=useState(''),[msg,note]=useState(''),[busy,wait]=useState(false),[models,list]=useState<string[]>([]);
 useEffect(()=>{if(initialize){edit(blank);sel('');setKey('');note('');show('initialize');}},[initialize]);
 const [capabilities,setCapabilities]=useState<Record<string,ModelCapabilities>>({});
 function changeModel(patch:Partial<Config>){
   edit(({reasoningEffort,fastMode,...rest})=>({...rest,...patch}));
 }
 const caps:ModelCapabilities = config.api==='openai-codex-subscription'
   ? capabilities[config.model]??{efforts:[],fast:false}
   : {efforts:config.deepseekThinking && config.api==='openai-completions'?['high','max']:[],fast:false};
 const controls=<div className="desk-fields model-tuning">
  {caps.efforts.length>0&&<label>思考强度<select aria-label="思考强度" value={config.reasoningEffort??''} onChange={e=>{
    const {reasoningEffort,...rest}=config;
    edit(e.target.value?{...rest,reasoningEffort:e.target.value as ReasoningEffort}:rest);
  }}><option value="">跟随模型</option>{caps.efforts.map(level=><option key={level} value={level}>{effortNames[level]}（{level}）</option>)}</select></label>}
  {caps.fast&&<label>处理速度<select aria-label="处理速度" aria-describedby="fast-mode-usage" value={config.fastMode?'fast':'standard'} onChange={e=>edit({...config,fastMode:e.target.value==='fast'})}>
   <option value="standard">标准</option><option value="fast">快速（优先处理）</option></select><small id="fast-mode-usage">快速模式可能消耗更多订阅额度。</small></label>}
 </div>;
 const [receipts,setReceipts]=useState<Record<string,ModelReceipt|null>>({});
 async function refreshReceipts(){setReceipts(await desk<Record<string,ModelReceipt|null>>('models','POST',{action:'receipts'}));}
 const tierName=(tier:string|null)=>tier==='default'?'标准':tier==='priority'||tier==='fast'?'快速':tier??'未报告';
 const [bots,setBots]=useState<BotSummary[]|null>(null);
 const load=async()=>{
   const [connections, roster]=await Promise.all([desk<Entry[]>('models'),listBots()]);
   set(connections);setBots(roster);await refreshReceipts();
 };useEffect(()=>{void load().catch(e=>note(e.message));},[]);
 async function act(action:string,target=id){wait(true);note('');try{const r=await desk<{models?:string[];message?:string}>('models','POST',{action,id:target,config,key,...(mode==='initialize-manual'?{manualModel:config.model}:{})});
 if(action==='discover'){list(r.models??[]);note('已拉取 '+(r.models?.length??0)+' 个模型');}
 else if(action==='probe')note(r.message||'连接成功');else{await load();show('');setKey('');if(action==='initialize-save')onInitialized?.();note(action==='delete'?'模型已删除':'模型配置已更新');}}catch(e){note(String(e));}finally{wait(false);}}
 function start(e?:Entry){sel(e?.id??'');edit(e?{...tuningOf(e),model:e.model,api:e.api,baseURL:e.baseURL,displayName:e.displayName??'',deepseekThinking:e.deepseekThinking,...(e.contextWindow?{contextWindow:e.contextWindow}:{}),...(e.maxTokens?{maxTokens:e.maxTokens}:{})}:blank);setKey('');list([]);note('');show(e?(e.api==='openai-codex-subscription'?'auth':'manual'):'choose');}
 const txt=(k:'model'|'baseURL'|'displayName',label:string)=><label>{label}<input value={config[k]} onChange={e=>k==='displayName'?edit({...config,[k]:e.target.value}):changeModel({[k]:e.target.value})}/></label>;
 const [imports,setImports]=useState<ImportedModel[]>([]);
 function useImport(item:ImportedModel){edit({...blank,baseURL:item.baseURL,model:item.model,api:item.api,displayName:item.displayName});setKey(item.apiKey);setImports([]);show('manual');note('请核对地址，拉取模型后验证并保存');}
 async function importJson(file?:File){if(!file)return;try{if(file.size>256000)throw Error();const values=readModelFile(await file.text());if(values.length===1)useImport(values[0]!);else setImports(values);}catch{note('文件中没有可识别的供应商 API Key 或模型配置');}}
 useEffect(()=>{if(!mode)return;function close(e:KeyboardEvent){if(e.key==='Escape'){show('');setKey('');setImports([]);}}window.addEventListener('keydown',close);return()=>window.removeEventListener('keydown',close);},[mode]);
 const [grant,setGrant]=useState<{url:string;code:string}|null>(null),[authorized,setAuthorized]=useState(false);
 useEffect(()=>{
  if(mode!=='auth'){setGrant(null);setAuthorized(false);return;}
  let live=true;
  async function status(){
   try{
    const r=await desk<{authorized:boolean;models:string[];capabilities:Record<string,ModelCapabilities>;failed:boolean}>('models','POST',{action:'subscription-status'});
    if(!live)return;setAuthorized(r.authorized);list(r.models);setCapabilities(r.capabilities);
    if(r.authorized){
     setGrant(null);edit(c=>({...blank,...(c.api==='openai-codex-subscription'&&r.models.includes(c.model)?tuningOf(c):{}),api:'openai-codex-subscription',baseURL:'https://chatgpt.com/backend-api',
      model:r.models.includes(c.model)?c.model:r.models[0]??'',displayName:'OpenAI · Codex 订阅',deepseekThinking:false}));
    }else if(r.failed){setGrant(null);note('授权已结束，可以重新登录。');}
   }catch{if(live)note('无法读取 Codex 授权状态，请检查本地内核。');}
  }
  void status();const timer=grant?window.setInterval(()=>void status(),2500):undefined;
  return ()=>{live=false;clearInterval(timer);};
 },[mode,grant]);
 async function login(device=false){
  wait(true);note('');try{
   if(grant)await desk('models','POST',{action:'subscription-cancel'});
   setGrant(await desk<{url:string;code:string}>('models','POST',{action:'subscription-login',device}));
  }catch(e){note(String(e));}finally{wait(false);}
 }
 return <><div className="desk-actions"><button className={initialize?'desk-primary dock-initialization':'desk-primary'} onClick={()=>{if(initialize)show('initialize');else start();}}>＋ 添加模型</button></div>
 <div className="desk-model-list">{entries.map(e=><Row key={e.id} title={e.displayName||e.model} hint={(e.active?'当前默认 · ':'')+e.model+' · '+e.baseURL}><div className="desk-end">{!e.active&&<button onClick={()=>void act('activate',e.id)}>设为默认</button>}<button onClick={()=>start(e)}>编辑</button><button onClick={()=>{sel(e.id);show('remove');note('');}}>删除</button></div></Row>)}</div>
 {mode&&<div className="desk-modal-layer"><section className="desk-modal" role="dialog" aria-modal="true" aria-label="模型连接"><button aria-label="关闭" className="desk-close" onClick={()=>{show('');setKey('');setImports([]);}}>×</button><h2>{mode==='remove'?'删除模型':id?'编辑模型':'添加模型'}</h2>
 {mode==='choose'&&<div className="desk-choice">{[['auth','OpenAI 订阅登录','使用 ChatGPT 账户授权 Codex 套餐。'],['import','导入本地配置','选择现有 Agent 或供应商的 API 配置文件。'],['manual','手动填写','指定推理接口、模型和密钥。']].map(([m,t,h])=><button key={m} onClick={()=>show(m!)}><strong>{t}</strong><p>{h}</p></button>)}</div>}
 {mode==='import'&&<><p>请选择自己的模型配置 JSON、.env 或 Claude 的 settings.json。支持 OpenAI、Anthropic、DeepSeek 的 API Key，以及含 baseURL、apiKey 的兼容配置。</p><input aria-label="模型配置文件" type="file" onChange={e=>void importJson(e.target.files?.[0])}/>{imports.map(i=><button key={i.displayName} onClick={()=>useImport(i)}>导入 {i.displayName}</button>)}</>}
 {mode==='auth'&&<><h3>OpenAI · Codex 订阅</h3>
 {authorized?<><p>已获得 ChatGPT 账户授权。</p><div className="model-picker"><label>GPT 模型<select aria-label="GPT 模型" value={config.model} onChange={e=>changeModel({model:e.target.value})}>{models.map(m=><option key={m}>{m}</option>)}</select></label></div>{controls}
 <div className="desk-end"><button disabled={busy} onClick={()=>void act('probe')}>验证订阅连接</button><button className="desk-primary" disabled={busy} onClick={()=>void act('save')}>保存模型</button></div></>:
 <><p>用购买套餐的 ChatGPT 账户登录，授权后即可为 Chives 选择 GPT 模型。</p>
 {grant?<p><a href={grant.url} target="_blank" rel="noreferrer">前往 OpenAI 完成授权 ↗</a>{grant.code&&<>　一次性设备码 <strong>{grant.code}</strong></>}</p>:<button className="desk-primary" disabled={busy} onClick={()=>void login()}>使用 ChatGPT 登录</button>}
 {grant&&!grant.code&&<button disabled={busy} onClick={()=>void login(true)}>改用设备码授权</button>}</>}
 <details><summary>其他供应商与 API Key</summary>{[['DeepSeek','https://platform.deepseek.com/api_keys'],['OpenAI','https://platform.openai.com/api-keys'],['Anthropic','https://console.anthropic.com/settings/keys']].map(([name,url])=><p key={name}><a href={url} target="_blank" rel="noreferrer">{name} 控制台 ↗</a></p>)}<button onClick={()=>{edit(blank);sel('');show('manual');}}>填写 API 连接</button></details></>}
 {mode==='remove'&&<><p>将移除这条连接和它在 Chives 中保存的密钥。</p><button disabled={busy} onClick={()=>void act('delete')}>确认删除</button></>}
 {(mode==='initialize'||mode==='initialize-manual')&&<form onSubmit={e=>{e.preventDefault();void act('initialize-save');}}>
 {txt('baseURL','API 地址')}
 <label>协议<select value={config.api} onChange={e=>changeModel({api:e.target.value})}>{['openai-completions','openai-responses','anthropic-messages'].map(a=><option key={a}>{a}</option>)}</select></label>
 <label>API Key<input required type="password" autoComplete="new-password" value={key} onChange={e=>setKey(e.target.value)}/></label>
 {mode==='initialize-manual'&&txt('model','模型 ID')}
 <div className="desk-end"><button type="button" disabled={busy} onClick={()=>{
   if(mode==='initialize-manual')show('initialize');
   else{changeModel({model:''});show('initialize-manual');}
 }}>{mode==='initialize-manual'?'自动选择模型':'手动指定模型'}</button><button className="desk-primary" disabled={busy||!config.baseURL.trim()||!key.trim()||(mode==='initialize-manual'&&!config.model.trim())}>验证并保存</button></div></form>}
 {mode==='manual'&&<form onSubmit={e=>{e.preventDefault();void act('save');}}>{txt('displayName','显示名称')}{txt('baseURL','API 地址')}<label>协议<select value={config.api} onChange={e=>changeModel({api:e.target.value})}>{['openai-completions','openai-responses','anthropic-messages'].map(a=><option key={a}>{a}</option>)}</select></label>
 <label>API Key<input type="password" autoComplete="new-password" value={key} placeholder={id?'同一地址可留空沿用密钥':''} onChange={e=>setKey(e.target.value)}/></label>{txt('model','模型 ID')}
 {!!models.length&&<label>可用模型<select value={config.model} onChange={e=>changeModel({model:e.target.value})}><option value="">请选择</option>{models.map(v=><option key={v}>{v}</option>)}</select></label>}

 <label><input type="checkbox" role="switch" checked={config.deepseekThinking} onChange={e=>changeModel({deepseekThinking:e.target.checked})}/> 启用 DeepSeek 思考参数</label>{controls}<div className="desk-end"><button type="button" disabled={busy} onClick={()=>void act('discover')}>拉取模型</button><button type="button" disabled={busy} onClick={()=>void act('probe')}>验证模型</button><button className="desk-primary" disabled={busy}>保存模型</button></div></form>}
 <p role="status">{msg}</p></section></div>}{!mode&&msg&&<p role="status">{msg}</p>}
 <section className="settings__section" aria-labelledby="bot-default-models">
   <h3 id="bot-default-models">各 Bot 的默认模型</h3><button onClick={()=>void refreshReceipts().catch(e=>note(e.message))}>刷新实际调用记录</button>
   {bots?.map(bot=>{const r=receipts[bot.id];return <div key={bot.id}><div className="settings__row"><span>{bot.name}</span><span>{bot.modelDisplayName}</span></div>
   <BotModelSettings id={bot.id} onSave={()=>void load().catch(e=>note(e.message))}/>
   {r&&<p>最近一次 Codex 调用 · {new Date(r.at).toLocaleString()}<br/>请求 {r.requestedModel} · 思考 {r.requestedEffort??'跟随模型'} · {tierName(r.requestedTier??'default')}<br/>
   服务端回报 {r.model??'未报告模型'} · 思考 {r.effort??'未报告'} · {tierName(r.tier)}</p>}</div>;})}
   {bots?.length===0&&<p>暂无可配置的 Bot</p>}
 </section></>;
}
