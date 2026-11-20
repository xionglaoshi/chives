import {execFile} from 'node:child_process';
import {join} from 'node:path';
import {AppError} from '../errors.js';

export function holdings(repoRoot:string,dshHome:string,body:Record<string,unknown>){
 const cwd=join(repoRoot,'packages','portfolio-mcp');
 return new Promise<unknown>((resolve,reject)=>{
  const child=execFile(join(cwd,'.venv','bin','python'),['-m','portfolio_mcp.workbench'],{
   cwd,env:{DSH_HOME:dshHome,HOME:process.env.HOME,PATH:process.env.PATH},timeout:15000
  },(error,output)=>{
   if(error)return reject(new AppError(500,'ledger','读取或保存持仓失败，请重试。'));
   try{
    const value=JSON.parse(output);
    if(!value.ok)throw new AppError(400,'position',value.error?.message??'请核对持仓字段。');
    if(value.warnings.includes('portfolio_corrupt'))throw new AppError(409,'ledger','持仓文件异常，请先恢复备份。');
    resolve(value.data);
   }catch(e){reject(e);}
  });
  child.stdin?.on('error',reject);
  child.stdin?.end(JSON.stringify(body));
 });
}
