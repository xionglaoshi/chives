import {spawn, type ChildProcess} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';

export function hotspotService(root:string, data:string) {
  const dir=join(data,'hotspots');
  let worker:ChildProcess|undefined;
  function read(file:string) {
    try {return JSON.parse(readFileSync(join(dir,file),'utf8'));}
    catch(error){if((error as NodeJS.ErrnoException).code==='ENOENT')return null;throw error;}
  }
  function current(){
    let status=read('status.json')??{state:'idle'};
    if(status.state==='running'){
      try{process.kill(status.pid,0);}catch{status={...status,state:'error'};}
    }
    if(worker)status={...status,state:'running'};
    return {snapshot:read('latest.json'),status};
  }
  async function start(){
    if(current().status.state==='running')return {state:'running'};
    const child=spawn((process.env.CALENDAR_PYTHON ?? join(root,'.venv/bin/python')),[join(root,'scripts/hotspots/generate.py'),'--data',dir],{stdio:'ignore'});
    worker=child;
    child.once('close',()=>{if(worker===child)worker=undefined;});
    await new Promise<void>((resolve,reject)=>{child.once('spawn',resolve);child.once('error',reject);});
    return {state:'running'};
  }
  return {current,start};
}
