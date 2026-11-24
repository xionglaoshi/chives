import {execFile} from 'node:child_process';
import {join,extname,basename} from 'node:path';
import {AppError} from '../errors.js';

export async function previewExcerpt(root:string, data:Record<string,unknown>){
  const name=typeof data.name==='string'?basename(data.name).slice(0,160):'';
  const kind=extname(name).slice(1).toLowerCase();
  if(!['pdf','docx','xlsx','txt','md','tsv','csv','png','jpg','jpeg'].includes(kind)||typeof data.base64!=='string')throw new AppError(400,'invalid_document','请选择列表中支持的文件格式。');
  const bytes=Buffer.from(data.base64,'base64');
  if(!bytes.length||bytes.length>4*1024*1024)throw new AppError(400,'size','每份文件须小于等于 4 MB。');
  return new Promise<{name:string,text:string,truncated:boolean}>((resolve,reject)=>{
    const child=execFile((process.env.CALENDAR_PYTHON ?? join(root,'.venv/bin/python')),[join(root,'scripts/profile-excerpt.py'),kind],{timeout:30000,maxBuffer:256000},(error,stdout)=>{
      try{
        if(error)throw Error('解析超时或文档读取工具不可用。');
        const result=JSON.parse(stdout);
        if(!result.text)throw Error(result.error||'无法读取正文。');
        resolve({name,text:result.text,truncated:result.truncated});
      }catch(e){reject(new AppError(422,'extraction',e instanceof Error?e.message:'资料读取失败。'));}
    });
    child.stdin?.on('error',()=>{});child.stdin?.end(bytes);
  });
}
