import {execFile,spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {selectedVersion} from '../harness/kernel-manager.js';
import {AppError} from '../errors.js';

const script=fileURLToPath(new URL('../../../../scripts/codex-subscription.mjs',import.meta.url));
const failure=()=>new AppError(502,'codex_subscription','Codex 订阅请求失败，请检查网络、账户授权和套餐额度。');
export const codexBase='https://chatgpt.com/backend-api';
export class CodexSubscription {
 private flow:Promise<{url:string;code:string}>|undefined;
 private loginError=false;
 private stop:(()=>void)|undefined;
 cancel(){this.stop?.();this.stop=undefined;this.flow=undefined;}
 constructor(private data:string,private home=join(data,'dsh')){}
 private args(action:string,model=''){return [script,this.home,selectedVersion(this.data),action,model];}
 private call<T>(action:string,model='',input?:object){
  return new Promise<T>((resolve,reject)=>{
   const child=execFile(process.execPath,this.args(action,model),{timeout:115000,maxBuffer:2**20},(err,out)=>{
    if(err)return reject(failure());
    try{resolve(JSON.parse(out) as T);}catch{reject(failure());}
   });
   child.stdin?.on('error',()=>{});child.stdin?.end(input?JSON.stringify(input):'');
  });
 }
 async status(){return {...await this.call<{authorized:boolean;models:string[]}>('status'),failed:this.loginError};}
 complete(model:string,instructions:string,text:string){return this.call<{text:string}>('complete',model,{instructions,text});}
 login(device=false){
  if(this.flow)return this.flow;
  this.loginError=false;
  this.flow=new Promise((resolve,reject)=>{
   const child=spawn(process.execPath,this.args('login',device?'device':'browser'),{stdio:['ignore','pipe','ignore'],timeout:610000});
   const stop=()=>child.kill();this.stop=stop;
   const timer=setTimeout(()=>{child.kill();reject(failure());},20000);
   const done=(failed:boolean)=>{clearTimeout(timer);if(this.stop===stop){this.flow=undefined;this.stop=undefined;this.loginError=failed;}if(failed)reject(failure());};
   child.once('error',()=>done(true));child.once('close',code=>done(code!==0));
   createInterface({input:child.stdout}).once('line',line=>{
    try{const v=JSON.parse(line);
     if(new URL(v.url).origin!=='https://auth.openai.com'||typeof v.code!=='string')throw Error();
     clearTimeout(timer);resolve({url:v.url,code:v.code});
    }catch{child.kill();reject(failure());}
   });
  });
  return this.flow;
 }
}
