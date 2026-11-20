import {existsSync,mkdirSync,readFileSync,readdirSync,renameSync,rmSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import type {DatabaseSync} from 'node:sqlite';

const names:Record<string,string>={
 'workbench.preferences.v1':'account-settings.json',appearance:'appearance.json',proactive:'notifications.json',
 'sidebar.botOrder':'sidebar-order.json','workbench.style-assessment.v1':'legacy-assessment.json',
 'workbench.investor-context':'legacy-context.json'
};
export class PersonalSettings {
 private dir:string;
 constructor(data:string,db:DatabaseSync){
  this.dir=join(data,'profile');mkdirSync(this.dir,{recursive:true,mode:0o700});
  const keys=Object.keys(names);
  const placeholders=keys.map(()=>'?').join(',');
  const previous=db.prepare(`SELECT key,value FROM settings WHERE key IN (${placeholders}) OR key LIKE 'profile-proposal/%'`).all(...keys);
  for(const row of previous){
   const key=String(row.key),path=this.path(key);
   if(!path)continue;
   if(!existsSync(path))this.set(path,JSON.parse(String(row.value)));
   if(JSON.stringify(this.get(path))!==JSON.stringify(JSON.parse(String(row.value))))throw Error('个人设置存在两个不同版本：'+key);
   db.prepare('DELETE FROM settings WHERE key=? AND value=?').run(key,row.value!);
  }
 }
 path(key:string){
  if(Object.hasOwn(names,key))return join(this.dir,names[key]!);
  const match=/^profile-proposal\/([a-z0-9_-]+)$/.exec(key);
  return match?join(this.dir,'pending-'+match[1]+'.json'):undefined;
 }
 get(path:string){return existsSync(path)?JSON.parse(readFileSync(path,'utf8')):undefined;}
 set(path:string,value:unknown){const tmp=path+'.'+randomUUID();try{writeFileSync(tmp,JSON.stringify(value,null,2)+'\n',{mode:0o600,flag:'wx'});renameSync(tmp,path);}finally{rmSync(tmp,{force:true});}}
 delete(path:string){rmSync(path,{force:true});}
 list(){
  const keys=[...Object.keys(names),...readdirSync(this.dir).flatMap(name=>{const m=/^pending-([a-z0-9_-]+)\.json$/.exec(name);return m?['profile-proposal/'+m[1]]:[];})];
  return Object.fromEntries(keys.filter(key=>existsSync(this.path(key)!)).map(key=>[key,this.get(this.path(key)!)]));
 }
}
