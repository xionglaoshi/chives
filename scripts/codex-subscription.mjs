// Use the same provider catalog and locked credential store as the selected dsh kernel.
import {createRequire} from 'node:module';
import {join,dirname} from 'node:path';
import {homedir} from 'node:os';
import {readdirSync,readFileSync} from 'node:fs';
const [home,version,action,model]=process.argv.slice(2);
const id='openai-codex';
const cache=join(process.env.npm_config_cache||join(homedir(),'.agents/state/chives-npm'),'_npx');
const emit=value=>console.log(JSON.stringify(value));
// The CLI account catalog can advertise new chat models before the kernel ships them.
function subscriptionCatalog(models) {
 const builtIn = models.getModels(id);
 const catalog = new Map();
 const codexHome = process.env.CODEX_HOME || join(homedir(), '.codex');
 try {
  const cached = JSON.parse(readFileSync(join(codexHome, 'models_cache.json'), 'utf8'));
  for (const entry of cached.models) {
   if (entry.visibility !== 'list' || typeof entry.slug !== 'string' || !/^gpt-[a-z0-9.-]+$/.test(entry.slug)) continue;
   const native = models.getModel(id, entry.slug);
   if (native) { catalog.set(entry.slug, native); continue; }
   const transport = builtIn[0];
   if (!transport || !Number.isSafeInteger(entry.context_window) || entry.context_window <= 0) continue;
   catalog.set(entry.slug, {
    id: entry.slug, name: entry.display_name || entry.slug, api: transport.api, provider: id,
    baseUrl: transport.baseUrl, cost: transport.cost, contextWindow: entry.context_window,
    maxTokens: Math.min(8192, entry.context_window),
    input: entry.input_modalities?.includes('image') ? ['text','image'] : ['text'],
    thinkingLevelMap: { off: null },
    reasoning: Array.isArray(entry.supported_reasoning_levels) && entry.supported_reasoning_levels.length > 0
   });
  }
 } catch { /* Standalone installations use the kernel catalog. */ }
 for (const native of builtIn) if (!catalog.has(native.id)) catalog.set(native.id, native);
 return catalog;
}

async function main(){
 const manifest=readdirSync(cache).map(dir=>join(cache,dir,'node_modules/@deepseek-ai/dsh/package.json')).find(file=>{
  try{return JSON.parse(readFileSync(file)).version===version;}catch{return false;}
 });
 if(!manifest)throw Error('kernel');
 const req=createRequire(manifest),load=name=>import(name.startsWith("@earendil-works/pi-ai/")?join(dirname(manifest),"../../",name.replace("pi-ai/","pi-ai/dist/")+".js"):req.resolve(name));
 const [{Context,Service},{LocalCredentialProvider},{credentialKey},{createModels},{openaiCodexProvider}]=await Promise.all([
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
   emit({authorized:(await storage.readRecord(address))?.kind==='grant',models:[...subscriptionCatalog(models).keys()]});
  }else if(action==='complete'){
   if(!(await credentials.read()))throw Error('missing authorization');
   const m=subscriptionCatalog(models).get(model);if(!m)throw Error('model');
   const {instructions,text}=JSON.parse(readFileSync(0,'utf8'));
   const answer=await models.complete(m,{systemPrompt:instructions,messages:[{role:'user',content:text,timestamp:Date.now()}]},{signal:AbortSignal.timeout(105000)});
   if(answer.stopReason==='error'||answer.stopReason==='aborted')throw Error('upstream');
   const output=answer.content.filter(x=>x.type==='text').map(x=>x.text).join('').trim();
   if(!output)throw Error('empty');
   emit({text:output});
  }else throw Error('unknown action');
 }finally{await dispose();}
}
main().catch(e=>{process.exitCode=1;});
