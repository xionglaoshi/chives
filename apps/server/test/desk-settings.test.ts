import {execFileSync} from 'node:child_process';
import {mkdtempSync,mkdirSync,readFileSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {it,expect} from 'vitest';
import {Updates} from '../src/settings/updates.js';
import {Store} from '../src/store/index.js';
import {defaults,parsePreferences,preferenceKey} from '../src/settings/workbench.js';
import {backupPersonal,restorePersonal} from '../src/settings/personal-backup.js';

it('restores user configuration and memory together, rejecting invalid paths before changes',()=>{
 const data=mkdtempSync(join(tmpdir(),'chives-desk-')),store=Store.open(data);
 try{
   mkdirSync(join(data,'bots/example/memory'),{recursive:true});
   const memory=join(data,'bots/example/memory','interest.md');
   writeFileSync(memory,'first');store.settings.set(preferenceKey,parsePreferences({name:'Example',workspaceWrite:false},defaults));
   const snapshot=backupPersonal(data,store);
   writeFileSync(memory,'second');store.settings.set(preferenceKey,defaults);
   expect(()=>restorePersonal(data,store,{...snapshot,files:{...snapshot.files,'../escape':'bad'}})).toThrow();
   expect(readFileSync(memory,'utf8')).toBe('second');
   restorePersonal(data,store,snapshot);
   expect(store.settings.get(preferenceKey)).toEqual({...defaults,name:'Example',workspaceWrite:false});
   expect(readFileSync(memory,'utf8')).toBe('first');
 }finally{store.close();rmSync(data,{recursive:true,force:true});}
});

it('updates successive component releases, including new and removed files, protecting working edits',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'chives-upstream-')),repo=join(dir,'upstream'),local=join(dir,'local');
 const git=(root:string,...args:string[])=>execFileSync('git',['-C',root,...args],{stdio:'pipe'}).toString().trim();
 try{
   mkdirSync(repo);git(repo,'init','-b','main');git(repo,'config','user.name','Test');git(repo,'config','user.email','local@example.test');
   mkdirSync(join(repo,'skills'));writeFileSync(join(repo,'skills','第一项.md'),'v1');git(repo,'add','.');git(repo,'commit','-m','v1');
   git(dir,'clone',repo,local);const manager=new Updates(local);
   writeFileSync(join(repo,'skills','第一项.md'),'v2');writeFileSync(join(repo,'skills/new'),'new');git(repo,'add','.');git(repo,'commit','-m','v2');
   const v2=await manager.check(true);expect(v2.items.find(i=>i.id==='skills')?.state).toBe('available');
   const done=await manager.apply('skills',v2.revision);
   expect(done.items.find(i=>i.id==='skills')?.state).toBe('current');
   expect(git(local,'diff','--cached','--name-only')).toBe('');
   rmSync(join(repo,'skills/new'));writeFileSync(join(repo,'skills','第一项.md'),'v3');git(repo,'add','-A');git(repo,'commit','-m','v3');
   writeFileSync(join(local,'skills','第一项.md'),'user draft');const v3=await manager.check(true);
   expect(v3.items.find(i=>i.id==='skills')?.state).toBe('conflict');await expect(manager.apply('all',v3.revision)).rejects.toThrow();
   expect(readFileSync(join(local,'skills','第一项.md'),'utf8')).toBe('user draft');
   writeFileSync(join(local,'skills','第一项.md'),'v2');await manager.apply('all',v3.revision);
   expect(readFileSync(join(local,'skills','第一项.md'),'utf8')).toBe('v3');
   expect(()=>readFileSync(join(local,'skills/new'))).toThrow();
 }finally{rmSync(dir,{recursive:true,force:true});}
});

it('applies one component on its first click, then updates the rest while preserving conflicting work',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'chives-update-click-')),remote=join(dir,'upstream'),local=join(dir,'work');
 const git=(root:string,...args:string[])=>execFileSync('git',['-C',root,...args],{stdio:'pipe'});
 const paths=['apps/example.txt','skills/example.txt','fixtures/example.txt'];
 try{
   mkdirSync(remote);git(remote,'init','-b','main');git(remote,'config','user.name','Test');git(remote,'config','user.email','test@local.example');
   for(const path of paths){mkdirSync(join(remote,path.split('/')[0]!));writeFileSync(join(remote,path),'before');}
   git(remote,'add','.');git(remote,'commit','-m','base');git(dir,'clone',remote,local);
   const updates=new Updates(local);
   for(const path of paths)writeFileSync(join(remote,path),'after');
   git(remote,'add','.');git(remote,'commit','-m','release');
   writeFileSync(join(local,paths[0]!),'local edits');
   const checked=await updates.check(true);
   expect(checked.items.find(i=>i.id==='skills')?.state).toBe('available');
   expect(readFileSync(join(local,paths[1]!),'utf8')).toBe('before');
   const one=await updates.applyLatest('skills');
   expect(one.updated).toEqual(['skills']);
   expect(readFileSync(join(local,paths[1]!),'utf8')).toBe('after');
   expect(readFileSync(join(local,paths[2]!),'utf8')).toBe('before');
   const all=await updates.applyLatest('all');
   expect(all.updated).toEqual(['databases']);
   expect(all.items.find(i=>i.id==='app')?.state).toBe('conflict');
   expect(readFileSync(join(local,paths[0]!),'utf8')).toBe('local edits');
   expect(readFileSync(join(local,paths[2]!),'utf8')).toBe('after');
   expect((await updates.applyLatest('all')).updated).toEqual([]);
 }finally{rmSync(dir,{recursive:true,force:true});}
});
