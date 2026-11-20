import {it,expect} from 'vitest';
import {mkdtempSync,mkdirSync,readFileSync,writeFileSync,existsSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {ensureHoldings,holdingsPath,refreshUserDocument} from '../src/settings/user-document.js';
import {backupPersonal,restorePersonal} from '../src/settings/personal-backup.js';
import {Store,openDatabase} from '../src/store/index.js';
it('moves the ledger intact and translates historical personal backup paths',()=>{
 const dir=mkdtempSync(join(tmpdir(),'user-map-'));const store=Store.open(dir);
 try{
  for(const sub of ['dsh','profile'])mkdirSync(join(dir,sub),{recursive:true});
  const old=join(dir,'dsh/finance-portfolio.json'),dest=join(dir,holdingsPath);
  const data=JSON.stringify({version:1,positions:[],cash:123,trades:[{id:'one'}]});
  writeFileSync(old,data);ensureHoldings(dir);expect(readFileSync(dest,'utf8')).toBe(data);
  expect(existsSync(old)).toBe(false);expect(backupPersonal(dir,store).files[holdingsPath]).toBe(data);
  const replacement=JSON.stringify({version:1,positions:[],cash:456});
  restorePersonal(dir,store,{format:'chives-personal-v1',preferences:{},files:{'dsh/finance-portfolio.json':replacement}});
  expect(readFileSync(dest,'utf8')).toBe(replacement);expect(existsSync(old)).toBe(false);
  writeFileSync(old,data);expect(()=>ensureHoldings(dir)).toThrow();expect(readFileSync(old,'utf8')).toBe(data);
  refreshUserDocument(dir,null);expect(readFileSync(join(dir,'profile/USER.md'),'utf8')).toContain('尚未评测');
 }finally{store.close();rmSync(dir,{recursive:true,force:true});}
});

it('routes existing SQLite account settings to their files across a restart',()=>{
 const dir=mkdtempSync(join(tmpdir(),'chives-settings-move-'));
 try{
  const db=openDatabase(dir);
  db.prepare('insert into settings(key,value) values (?,?)').run('workbench.preferences.v1','{"name":"测试"}');
  db.close();
  const store=Store.open(dir);
  try{
   expect(store.settings.get('workbench.preferences.v1')).toEqual({name:'测试'});
   expect(store.db.prepare('select key from settings where key=?').get('workbench.preferences.v1')).toBeUndefined();
   store.settings.set('sidebar.botOrder',['research']);
   const backup=backupPersonal(dir,store);
   writeFileSync(join(dir,'profile/account-settings.json'),'{"name":"改后"}');
   expect(store.settings.get('workbench.preferences.v1')).toEqual({name:'改后'});
   restorePersonal(dir,store,backup);
   expect(store.settings.get('workbench.preferences.v1')).toEqual({name:'测试'});
   expect(store.settings.get('sidebar.botOrder')).toEqual(['research']);
  }finally{store.close();}
 }finally{rmSync(dir,{recursive:true,force:true});}
});
