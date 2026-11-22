// Use the same provider catalog and locked credential store as the selected dsh kernel.
import {createRequire} from 'node:module';
import {join,dirname} from 'node:path';
import {homedir} from 'node:os';
import {pathToFileURL} from 'node:url';
import {existsSync,readdirSync,readFileSync} from 'node:fs';
const [home,version,action,model]=process.argv.slice(2);
const id='openai-codex';
const cache=join(process.env.npm_config_cache||join(homedir(),'.agents/state/chives-npm'),'_npx');
const emit=value=>console.log(JSON.stringify(value));
// The CLI account catalog can advertise new chat models before the kernel ships them.
function subscriptionCatalog(models, getSupportedThinkingLevels) {
 const builtIn = models.getModels(id);
 const catalog = new Map();
 const capabilities = {};
 const dshLevels = ['minimal','low','medium','high','xhigh','max'];
 function nativeEfforts(model) {
  return getSupportedThinkingLevels(model).filter(level => dshLevels.includes(level) &&
    (!model.thinkingLevelMap?.[level] || model.thinkingLevelMap[level] === level));
 }
 const codexHome = process.env.CODEX_HOME || join(homedir(), '.codex');
 try {
  const cached = JSON.parse(readFileSync(join(codexHome, 'models_cache.json'), 'utf8'));
  for (const entry of cached.models) {
   if (entry.visibility !== 'list' || typeof entry.slug !== 'string' || !/^gpt-[a-z0-9.-]+$/.test(entry.slug)) continue;
   const native = models.getModel(id, entry.slug);
   const advertised = entry.supported_reasoning_levels?.map(level => level.effort);
   const efforts = Array.isArray(advertised) ? dshLevels.filter(level => advertised.includes(level)) : native ? nativeEfforts(native) : [];
   capabilities[entry.slug] = {efforts, fast: entry.service_tiers?.some(tier => tier.id === 'priority') === true ||
     entry.additional_speed_tiers?.includes('fast') === true};
   if (native) { catalog.set(entry.slug, native); continue; }
   const transport = builtIn[0];
   if (!transport || !Number.isSafeInteger(entry.context_window) || entry.context_window <= 0) continue;
   catalog.set(entry.slug, {
    id: entry.slug, name: entry.display_name || entry.slug, api: transport.api, provider: id,
    baseUrl: transport.baseUrl, cost: transport.cost, contextWindow: entry.context_window,
    maxTokens: Math.min(8192, entry.context_window),
    input: entry.input_modalities?.includes('image') ? ['text','image'] : ['text'],
    thinkingLevelMap: { off: null, ...Object.fromEntries(efforts.map(level => [level,level])) },
    reasoning: Array.isArray(entry.supported_reasoning_levels) && entry.supported_reasoning_levels.length > 0
   });
  }
 } catch { /* Standalone installations use the kernel catalog. */ }
 for (const native of builtIn) if (!catalog.has(native.id)) catalog.set(native.id, native);
 for (const native of builtIn) capabilities[native.id] ??= {efforts:nativeEfforts(native),fast:false};
 return {catalog, capabilities};
}

async function main(){
 const installed=process.env.CHIVES_DSH_JS;
 const candidates=installed?[join(dirname(installed),'..','package.json')]:[];
 if(existsSync(cache))candidates.push(...readdirSync(cache).map(dir=>join(cache,dir,'node_modules/@deepseek-ai/dsh/package.json')));
 const manifest=candidates.find(file=>{
  try{const pkg=JSON.parse(readFileSync(file));return pkg.name==='@deepseek-ai/dsh' && pkg.version===version;}catch{return false;}
 });
 if(!manifest)throw Error('kernel');
 const req=createRequire(manifest);
 const load=name=>import(pathToFileURL(name.startsWith('@earendil-works/pi-ai/')
  ?join(dirname(manifest),'../../',name.replace('pi-ai/','pi-ai/dist/')+'.js')
  :req.resolve(name)).href);
 const [{Context,Service},{LocalCredentialProvider},{credentialKey},{createModels,getSupportedThinkingLevels},{openaiCodexProvider}]=await Promise.all([
  '@deepseek-ai/cordis','@deepseek-ai/dsh-credentials-local','@deepseek-ai/dsh-credentials','@earendil-works/pi-ai/models','@earendil-works/pi-ai/providers/openai-codex'
 ].map(load));
 const storage=new LocalCredentialProvider(new Context(),{dshHome:home,watch:false});
 const init=storage[Service.init]();const {value:dispose}=await init.next();await init.next();
 const address=credentialKey('llm-pi-ai',id);
 const credentials={
  read:async()=> (await storage.readRecord(address))?.payload,
  modify:async(_,mutate)=>(await storage.modifyRecord(address,async old=>{
   const next=await mutate(old?.payload);return next?{kind:'grant',payload:JSON.parse(JSON.stringify(next))}:undefined;
  }))?.payload,
  list:async()=> (await storage.readRecord(address))?[{providerId:id,type:'oauth'}]:[],
  delete:()=>storage.deleteRecord(address)
 };
 try{
  const models=createModels({credentials});models.setProvider(openaiCodexProvider());
  if(action==='login'){
   await models.login(id,'oauth',{signal:AbortSignal.timeout(10*60_000),
    prompt:async p=>{if(p.type==='select')return model==='device'?'device_code':'browser';
     if(p.type==='manual_code')return new Promise((_,reject)=>p.signal.addEventListener('abort',()=>reject(Error('closed')),{once:true}));
     throw Error('unsupported prompt');},
    notify:n=>{if(n.type==='auth_url')emit({url:n.url,code:''});
     if(n.type==='device_code')emit({url:n.verificationUri,code:n.userCode});}
   });
  }else if(action==='status'){
   const {catalog,capabilities}=subscriptionCatalog(models,getSupportedThinkingLevels);
   emit({capabilities,authorized:(await storage.readRecord(address))?.kind==='grant',models:[...catalog.keys()]});
  }else if(action==='complete'){
   if(!(await credentials.read()))throw Error('missing authorization');
   const m=subscriptionCatalog(models,getSupportedThinkingLevels).catalog.get(model);if(!m)throw Error('model');
   const {instructions,text,reasoningEffort,fastMode}=JSON.parse(readFileSync(0,'utf8'));
   let sent=null,served=null;
   const answer=await models.complete(m,{systemPrompt:instructions,messages:[{role:'user',content:text,timestamp:Date.now()}]},{
    signal:AbortSignal.timeout(105000), ...(reasoningEffort?{reasoningEffort}:{}), ...(fastMode?{serviceTier:'priority'}:{}),
    onPayload(body){sent={model:body.model,effort:body.reasoning?.effort??null,tier:body.service_tier??null};},
    onProviderStreamEvent(event){const response=event?.response;if(event.type==='response.completed'&&response)served={model:response.model??null,effort:response.reasoning?.effort??null,tier:response.service_tier??null};}
   });
   if(answer.stopReason==='error'||answer.stopReason==='aborted')throw Error('upstream');
   const output=answer.content.filter(x=>x.type==='text').map(x=>x.text).join('').trim();
   if(!output)throw Error('empty');
   emit({text:output,sent,served});
  }else throw Error('unknown action');
 }finally{await dispose();}
}
main().catch(e=>{process.exitCode=1;});
