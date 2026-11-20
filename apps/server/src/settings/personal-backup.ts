import {holdingsPath} from './user-document.js';
import {profilePath,validProfileFile} from './interview-profile.js';
import {assessmentKey,validAssessment} from './style-assessment.js';
import { existsSync, mkdirSync, readFileSync, readdirSync, renameSync, writeFileSync, lstatSync, rmSync, realpathSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
import type {Store} from '../store/index.js';
import {AppError} from '../errors.js';
import {parsePreferences,defaults,preferenceKey} from './workbench.js';

const keys=[preferenceKey,assessmentKey,'appearance','proactive','sidebar.botOrder','workbench.investor-context'];
const kernelKey=(name:string)=>/^kernel\/[a-z0-9_-]+$/.test(name);
function validSetting(key:string,value:Record<string,unknown>){
  if(key==='sidebar.botOrder')return Array.isArray(value)&&value.every(id=>typeof id==='string');
  if(key==='workbench.investor-context')return typeof value==='object';
  if(key===assessmentKey)return validAssessment(value);
  if(key===preferenceKey){parsePreferences(value,defaults);return true;}
  if(kernelKey(key))return Object.keys(value).every(k=>['kernel','model','connection'].includes(k))&&['dsh','claude','codex','hermes','builtin'].includes(String(value.kernel))&&(value.connection===undefined || (typeof value.connection==='string' && /^[a-zA-Z0-9-]{0,80}$/.test(value.connection)))&&typeof value.model==='string'&&value.model.length<=160;
  if(key==='appearance')return Object.entries(value).every(([k,v])=>k==='theme'?['system','light','dark'].includes(String(v)):k==='changeColor'&&['red-up','green-up'].includes(String(v)));
  if(key==='proactive')return Object.entries(value).every(([k,v])=>k==='dailyLimit'?Number.isInteger(v)&&Number(v)>=0&&Number(v)<=200:['enabled','autoAnalysis','observeOnly','browserNotify','systemNotify','importantOnly'].includes(k)&&typeof v==='boolean');
  return false;
}
function allowed(path:string){
  return path===profilePath || path===holdingsPath || path==='profile/finance-profile.json' || path==='profile/finance-profile.md' || /^dsh\/finance-(profile|portfolio)\.json$/.test(path) ||
    /^bots\/[a-z0-9_-]+\/(memory\/[\w-]+\.md|profile\/(AGENTS\.md|resources\.json))$/.test(path);
}
function files(data:string){
  const paths=[profilePath,'profile/finance-profile.json','profile/finance-profile.md',holdingsPath];
  for(const bot of existsSync(join(data,'bots'))?readdirSync(join(data,'bots'),{withFileTypes:true}):[]){
    if(!bot.isDirectory()||!/^[a-z0-9_-]+$/.test(bot.name))continue;
    const base='bots/'+bot.name+'/';
    paths.push(base+'profile/AGENTS.md',base+'profile/resources.json');
    const dir=join(data,base,'memory');
    if(existsSync(dir)&&!lstatSync(dir).isSymbolicLink())for(const name of readdirSync(dir))paths.push(base+'memory/'+name);
  }
  return paths.filter(path=>allowed(path)&&existsSync(join(data,path))&&realpathSync(join(data,path))===join(realpathSync(data),path));
}
export function backupPersonal(data:string,store:Store){
  const entries=Object.fromEntries(files(data).map(p=>[p,readFileSync(join(data,p),'utf8')]));
  const kernels=store.db.prepare("SELECT key FROM settings WHERE key LIKE 'kernel/%'").all().map(r=>String(r.key)).filter(kernelKey);
  return {format:'chives-personal-v1',createdAt:new Date().toISOString(),preferences:Object.fromEntries([...keys,...kernels].map(k=>[k,store.settings.get(k)??null])),files:entries};
}
export function restorePersonal(data:string,store:Store,input:Record<string,unknown>){
  const bad=()=>new AppError(400,'invalid_backup','请选择 Chives 个性化备份文件');
  if(Array.isArray(input.preferences)||Array.isArray(input.files)||input.format!=='chives-personal-v1'||!input.preferences||typeof input.preferences!=='object'||!input.files||typeof input.files!=='object')throw bad();
  const prefs=Object.entries(input.preferences),entries=Object.entries(input.files).map(([p,v])=>[p==='dsh/finance-portfolio.json'?holdingsPath:p==='dsh/finance-profile.json'?'profile/finance-profile.json':p,v] as const);
  if(new Set(entries.map(([p])=>p)).size!==entries.length)throw bad();
  for(const [k,v] of prefs){
    if((!keys.includes(k)&&!kernelKey(k))||(v!==null&&(typeof v!=='object'||(Array.isArray(v)&&k!=='sidebar.botOrder')||!validSetting(k,v))))throw bad();
  }
  for(const [p,v] of entries){
    if(!allowed(p)||typeof v!=='string')throw bad();
    if(p===profilePath&&!validProfileFile(v))throw bad();
    if(p.endsWith('.json'))try { if(!JSON.parse(v)||typeof JSON.parse(v)!=='object')throw bad(); } catch {throw bad();}
    let dst=join(data,p);while(!existsSync(dst)&&dst!==data)dst=dirname(dst);
    if(realpathSync(dst)!==resolve(realpathSync(data),dst.slice(data.length+1)))throw bad();
  }
  const backup=backupPersonal(data,store);
  const dir=join(data,'personal-backups');mkdirSync(dir,{recursive:true,mode:0o700});
  writeFileSync(join(dir,randomUUID()+'.json'),JSON.stringify(backup),{mode:0o600});
  const atomic=(p:string,v:string)=>{const dest=join(data,p);mkdirSync(dirname(dest),{recursive:true,mode:0o700});const temp=dest+'.'+randomUUID();writeFileSync(temp,v,{mode:0o600});renameSync(temp,dest);};
  const changed:string[]=[];
  store.db.exec('BEGIN IMMEDIATE');
  try{
    for(const [p,v] of entries){atomic(p,v);changed.push(p);}
    for(const [k,v] of prefs){if(v===null)store.settings.delete(k);else store.settings.set(k,kernelKey(k)?{...v,kernel:'dsh'}:v);}
    store.db.exec('COMMIT');
  }catch(error){
    store.db.exec('ROLLBACK');
    for(const [k] of prefs){const previous=backup.preferences[k];if(previous===null)store.settings.delete(k);else store.settings.set(k,previous);}
    for(const p of changed.reverse()){const old=backup.files[p];if(old===undefined)rmSync(join(data,p),{force:true});else atomic(p,old);}
    throw error;
  }
  return {files:entries.length,settings:prefs.length};
}
