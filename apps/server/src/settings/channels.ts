import {execFile} from 'node:child_process';
import {homedir} from 'node:os';
import {existsSync,readdirSync,readFileSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {AppError} from '../errors.js';

const ids=['weixin','wecom','feishu','telegram','slack','discord'];
export class Channels {
  private pairing=new Set<string>();
  constructor(private root:string,private data:string){}
  private run(op:string,input:Record<string,unknown>,extra:string[]=[]):Promise<unknown> {
    return new Promise((res,rej)=>{
      const child=execFile(join(homedir(),'.agents/venvs/chives/bin/python'),
        [join(this.root,'scripts/settings-channels.py'),this.data,op,...extra],
        {timeout:op==='pair'?270000:45000,maxBuffer:200000,env:{...process.env,PYTHONUNBUFFERED:'1',HTTPS_PROXY:'http://127.0.0.1:7897',HTTP_PROXY:'http://127.0.0.1:7897'}},
        (err,out)=>{try{const r=JSON.parse(out);if(err||r.error)throw Error();res(r);}catch{rej(new AppError(400,'channel_failed','通讯平台未确认，请核对授权资料、会话和网络'));}});
      child.stdin?.on('error',()=>{});child.stdin?.end(JSON.stringify(input));
    });
  }
  async manage(action:string,body:Record<string,unknown>) {
    if(action==='list')return this.run('list',{});
    const id=String(body.id);
    if(!ids.includes(id))throw new AppError(400,'channel','未知平台');
    if(this.pairing.has(id))throw new AppError(409,'pairing','正在等待手机授权');
    if(action==='pair'&&ids.slice(0,4).includes(id)){
      rmSync(join(this.data,'secrets/channels',id+'.pair'),{force:true});
      this.pairing.add(id);
      void this.run('pair',{},[id]).catch(()=>{}).finally(()=>this.pairing.delete(id));
      return {started:true};
    }
    if(action==='save'||action==='delete')return this.run(action,body);
    throw new AppError(400,'channel','不支持的操作');
  }
  deliver(title:string,body:string){
    const folder=join(this.data,'secrets','channels');if(!existsSync(folder))return;
    for(const file of readdirSync(folder)){
      const id=file.replace(/\.json$/,'');if(!ids.includes(id))continue;
      try{if(JSON.parse(readFileSync(join(folder,file),'utf8')).enabled)void this.run('send',{id,message:title+'\n'+body}).catch(()=>{});}catch{continue;}
    }
  }
}
