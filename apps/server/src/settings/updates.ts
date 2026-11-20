import { execFile } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { existsSync, lstatSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { promisify } from 'node:util';
import { AppError } from '../errors.js';

const run=promisify(execFile);
const scopes={
  factors:['packages/equity-evidence/src/equity_evidence/vendor/src/factors'],
  databases:['fixtures','config/trade_calendar.json'],
  tools:['packages','config/equity-tools.json'],
  skills:['skills','THIRD_PARTY_NOTICES.md'],
  app:['apps','start','scripts','pnpm-lock.yaml','pnpm-workspace.yaml','package.json','overlays','bots','config','plugins'],
};
type Scope=keyof typeof scopes;
type BlobEntry={mode:string;hash:string};
function scopeFor(path:string){
  return (Object.keys(scopes) as Scope[]).find(key=>scopes[key].some(p=>path===p||path.startsWith(p+'/')));
}
function same(a?:BlobEntry,b?:BlobEntry){return a?.hash===b?.hash&&a?.mode===b?.mode;}

export class Updates {
  private busy=false;
  constructor(private readonly root:string){}
  private async git(args:string[],env:NodeJS.ProcessEnv={}){
    return (await run('git',['-c','http.proxy=http://127.0.0.1:7897',...args],{
      cwd:this.root,timeout:30000,maxBuffer:32*1024*1024,env:{...process.env,GIT_TERMINAL_PROMPT:'0',...env},
    })).stdout;
  }
  private async tree(revision:string){
    const output=await this.git(['ls-tree','-rz',revision]);
    const entries=new Map<string,BlobEntry>();
    for(const line of output.split('\0')){
      const tab=line.indexOf('\t');
      if(tab<0)continue;
      const [mode,,hash]=line.slice(0,tab).split(' '),path=line.slice(tab+1);
      if(scopeFor(path)&&mode&&hash)entries.set(path,{mode,hash});
    }
    return entries;
  }
  private local(path:string):BlobEntry|undefined{
    const target=resolve(this.root,path);
    for(let p=dirname(target);p!==this.root;p=dirname(p)){
      if(!p.startsWith(this.root+'/')||(existsSync(p)&&lstatSync(p).isSymbolicLink()))return {mode:'unsupported',hash:''};
    }
    const stat=lstatSync(target,{throwIfNoEntry:false});
    if(!stat)return;
    if(!stat.isFile())return {mode:'unsupported',hash:''};
    const bytes=readFileSync(target);
    return {mode:stat.mode&0o111?'100755':'100644',hash:createHash('sha1').update('blob '+bytes.length+'\0').update(bytes).digest('hex')};
  }
  private async snapshot(fetchRemote:boolean){
    if(fetchRemote)await this.git(['fetch','--no-tags','origin','main']);
    const revision=(await this.git(['rev-parse','origin/main'])).trim();
    const stateFile=resolve(this.root,(await this.git(['rev-parse','--git-path','chives-update-state.json'])).trim());
    const installed:Partial<Record<Scope,string>>=existsSync(stateFile)?JSON.parse(readFileSync(stateFile,'utf8')):{};
    const head=(await this.git(['rev-parse','HEAD'])).trim();
    const remote=await this.tree(revision),trees=new Map([[revision,remote]]);
    const items=[];
    for(const id of Object.keys(scopes) as Scope[]){
      const base=installed[id]||head;
      if(!trees.has(base))trees.set(base,await this.tree(base));
      const before=trees.get(base)!;
      const files:string[]=[];
      let published=false,conflict=false;
      for(const path of new Set([...before.keys(),...remote.keys()])){
        if(scopeFor(path)!==id)continue;
        const old=before.get(path),next=remote.get(path);
        if(next)published=true;
        const local=this.local(path);
        if(same(next,local))continue;
        if(!same(old,local)|| (next&&!['100644','100755'].includes(next.mode)))conflict=true;
        else files.push(path);
      }
      const state=conflict?'conflict':files.length?'available':published?'current':'unpublished';
      items.push({id,state,count:files.length,files,base});
    }
    return {revision,installed,stateFile,items};
  }
  async check(fetchRemote:boolean){
    const {revision,items}=await this.snapshot(fetchRemote);
    return {revision,items:items.map(({id,state,count})=>({id,state,count}))};
  }
  async apply(id:string,revision:unknown){
    return this.install(id,{revision});
  }
  async applyLatest(id:string){
    return this.install(id,{latest:true});
  }
  private async install(id:string,target:{revision:unknown}|{latest:true}){
    if(id!=='all'&&!Object.hasOwn(scopes,id))throw new AppError(400,'bad_component','未知的更新组件');
    if(this.busy)throw new AppError(409,'busy','已有更新操作');
    this.busy=true;
    const temp=mkdtempSync(join(tmpdir(),'chives-update-'));
    try{
      const snapshot=await this.snapshot(true);
      if('revision' in target && snapshot.revision!==target.revision)throw new AppError(409,'changed','远端版本已变化，请重新检查');
      const selected=id==='all'?snapshot.items:snapshot.items.filter(i=>i.id===id);
      const items='latest' in target?selected.filter(item=>item.state!=='conflict'):selected;
      if(items.some(item=>item.state==='conflict'))throw new AppError(409,'conflict','存在本地修改，请先核对差异');
      for(const item of items){
        if(item.state==='unpublished')continue;
        if(item.files.length){
          // A separate index keeps the developer's staging area intact, including on file deletion.
          const env={GIT_INDEX_FILE:join(temp,item.id)};
          await this.git(['read-tree',item.base],env);
          for(let i=0;i<item.files.length;i+=200){
            await this.git(['--literal-pathspecs','restore','--source='+snapshot.revision,'--worktree','--',...item.files.slice(i,i+200)],env);
          }
        }
        snapshot.installed[item.id]=snapshot.revision;
        const path=snapshot.stateFile+'.'+randomUUID();
        writeFileSync(path,JSON.stringify(snapshot.installed),{mode:0o600});renameSync(path,snapshot.stateFile);
      }
      return {...await this.check(false),updated:items.filter(item=>item.files.length>0).map(item=>item.id)};
    }finally{rmSync(temp,{recursive:true,force:true});this.busy=false;}
  }
}
