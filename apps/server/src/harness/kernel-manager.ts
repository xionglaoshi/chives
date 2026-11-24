import { execFile } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { promisify } from 'node:util';
import semver from 'semver';
import { AcpClient } from '@chives/acp-client';
import { AppError } from '../errors.js';

const run = promisify(execFile);
const registry = 'https://registry.npmjs.org';
const runtime = fileURLToPath(new URL('../../../../runtime/',import.meta.url));
const baseline = readFileSync(new URL('../../../../config/dsh-version',import.meta.url),'utf8').trim();
const versionFile = (data:string) => join(data,'harness','dsh','version');

export function selectedVersion(data:string):string {
  try {
    const value=readFileSync(versionFile(data),'utf8').trim();
    if (!semver.valid(value)) throw new Error('dsh 版本记录无效');
    return value;
  } catch(error) {
    if ((error as NodeJS.ErrnoException).code==='ENOENT') return baseline;
    throw error;
  }
}
function downloadEnv(){
  return { ...process.env, npm_config_registry:registry,
    npm_config_cache:process.env.npm_config_cache ?? join(runtime,'npm-cache'),
    HTTPS_PROXY:process.env.HTTPS_PROXY || 'http://127.0.0.1:7897',
    HTTP_PROXY:process.env.HTTP_PROXY || 'http://127.0.0.1:7897' };
}
async function latestRelease(){
  const {stdout}=await run('npm',['view','@deepseek-ai/dsh','dist-tags.latest','--json','--prefer-online','--fetch-retries=0'],{
    env:downloadEnv(),timeout:20_000
  });
  const version:unknown=JSON.parse(stdout);
  if(typeof version!=='string'||!semver.valid(version))throw new Error('无效的发布版本');
  return version;
}
async function verifyRelease(version:string){
  const temporary=join(runtime,'tmp');
  mkdirSync(temporary,{recursive:true});
  const home=await mkdtemp(join(temporary,'chives-dsh-upgrade-'));
  const pkg='@deepseek-ai/dsh@'+version;
  const env={...downloadEnv(),DSH_HOME:home};
  try {
    const result=await run('npx',['-y',pkg,'--version'],{env,timeout:180_000});
    if(result.stdout.trim()!==version)throw new Error('dsh 版本校验失败');
    const client=new AcpClient({command:'npx',args:['-y',pkg,'--profile','acp'],cwd:home,env},
      {initializeTimeoutMs:45_000});
    try {await client.initialize();} finally {await client.close();}
  } finally {await rm(home,{recursive:true,force:true});}
}
export class KernelManager {
  private latest:string|null=null;
  private busy=false;
  constructor(private readonly data:string,private reload:()=>Promise<void>,
    private discover=latestRelease,private verify=verifyRelease){}
  snapshot(){
    const current=selectedVersion(this.data);
    return {current,latest:this.latest,available:this.latest!==null && semver.gt(this.latest,current),busy:this.busy};
  }
  async check(){
    try {this.latest=await this.discover();}
    catch {throw new AppError(503,'registry_unavailable','无法查询 npm 发布版本，请检查网络后重试');}
  }
  async upgrade(target:unknown){
    if(this.busy) throw new AppError(409,'busy','内核正在升级');
    if(!this.snapshot().available || target!==this.latest || typeof target!=='string')
      throw new AppError(409,'stale_version','请先检查更新并确认目标版本');
    this.busy=true;
    try {
      await this.verify(target);
      const file=versionFile(this.data);
      mkdirSync(dirname(file),{recursive:true});
      const temporary=file+'.'+randomUUID();
      writeFileSync(temporary,target+'\n',{mode:0o600});
      renameSync(temporary,file);
    } catch {throw new AppError(503,'upgrade_failed','安装或 ACP 验证失败，仍使用原版本');}
    finally {this.busy=false;}
    await this.reload();
  }
}
