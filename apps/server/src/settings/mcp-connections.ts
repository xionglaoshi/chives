import {existsSync,readFileSync,mkdirSync,writeFileSync,renameSync,unlinkSync} from 'node:fs';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {z} from 'zod';
import type {McpServer} from '@chives/acp-client';
import {AppError} from '../errors.js';

const arg=z.string().max(8192).refine(s=>!s.includes('\0'));
const pairs=z.record(z.string().regex(/^[A-Za-z_][A-Za-z0-9_-]{0,100}$/),arg);
const remoteUrl=z.url().max(8192).refine(s=>{
  if(!URL.canParse(s))return false;
  const u=new URL(s);return !u.username&&!u.password&&!u.hash&&
    (u.protocol==='https:'||(u.protocol==='http:'&&['127.0.0.1','localhost','[::1]'].includes(u.hostname)));
});
const descriptor=z.union([
  z.object({type:z.literal('stdio').optional(),command:arg.min(1),args:z.array(arg).max(100).default([]),env:pairs.default({})}).strict(),
  z.object({type:z.enum(['http','streamable-http','sse']).default('http'),url:remoteUrl,headers:pairs.refine(h=>
    Object.entries(h).every(([k,v])=>!/[\r\n]/.test(v)&&!['host','connection','content-length','transfer-encoding'].includes(k.toLowerCase()))).default({})}).strict()
]);
export type McpDescriptor=z.infer<typeof descriptor>;
export const templates=[
  {id:'alphavantage',name:'Alpha Vantage',description:'查询市场行情、财务指标和经济数据，覆盖范围由供应商账户决定。',url:'https://mcp.alphavantage.co/mcp',docs:'https://github.com/alphavantage/alpha_vantage_mcp',hint:'使用供应商保留的 API Key 地址接入方式。'},
  {id:'context7',name:'Context7',description:'查询技术文档，供编写因子和回测工具时核对接口。',url:'https://mcp.context7.com/mcp',docs:'https://github.com/upstash/context7',hint:'使用 Context7 API Key 连接。'}
];
const presetSchema=z.enum(['alphavantage','context7']);
const entrySchema=z.object({id:z.string().regex(/^ext_[a-f0-9]{16}$/),name:z.string().trim().min(1).max(80),
  enabled:z.boolean(),source:z.union([presetSchema,z.literal('custom')]),spec:descriptor,tools:z.array(z.string()),revision:z.string()});
export type Entry=z.infer<typeof entrySchema>;
export const approvedOnly=()=>process.env.CHIVES_MCP_POLICY==='approved';
const file=(data:string)=>join(data,'secrets','mcp-connections.json');
function read(data:string):Entry[]{return existsSync(file(data))?z.array(entrySchema).parse(JSON.parse(readFileSync(file(data),'utf8'))):[];}
function write(data:string,entries:Entry[]){
  mkdirSync(join(data,'secrets'),{recursive:true,mode:0o700});
  const tmp=file(data)+'.'+randomUUID();
  try{writeFileSync(tmp,JSON.stringify(entries),{mode:0o600,flag:'wx'});renameSync(tmp,file(data));}finally{if(existsSync(tmp))unlinkSync(tmp);}
}
function preset(id:string,token:unknown):McpDescriptor{
  const t=templates.find(i=>i.id===id);
  if(!t || typeof token!=='string'||!token.trim()||/[\r\n]/.test(token)||token.length>4096)throw new AppError(400,'invalid_preset','请选择预设并填写供应商密钥。');
  const key=token.trim();
  if(id==='context7') return {type:'http',url:t.url,headers:{CONTEXT7_API_KEY:key}};
  const u=new URL(t.url);u.searchParams.set('apikey',key);return {type:'http',url:u.href,headers:{}};
}
function permitted(e:Entry){
  if(!approvedOnly())return true;
  if(e.source==='custom'||!('url' in e.spec))return false;
  const t=templates.find(t=>t.id===e.source),u=new URL(e.spec.url);
  return !!t && u.origin+u.pathname===t.url && e.spec.type==='http';
}
export const installed=(data:string)=>read(data).filter(permitted);
export const findEnabled=(data:string,id:string)=>installed(data).find(e=>e.id===id&&e.enabled);
export function describeEntry(e:Entry){
  return {id:e.id,name:e.name,enabled:e.enabled,source:e.source,tools:e.tools,revision:e.revision,
    transport:'command' in e.spec?'stdio':e.spec.type==='sse'?'SSE':'HTTP'};
}
export function parseDraft(body:Record<string,unknown>,old?:Entry):Entry{
  const source=old?.source??body.source??'custom';
  if(source==='custom'&&approvedOnly())throw new AppError(403,'policy','此部署仅允许从认可目录添加 MCP。');
  let spec:McpDescriptor,name:unknown;
  if(source==='custom'){
    const parsed=descriptor.safeParse(body.spec);
    if(!parsed.success)throw new AppError(400,'invalid_spec','请检查传输类型、地址、请求头、命令及参数。HTTP 明文限本机地址。');
    spec=parsed.data;name=body.name;
  }else{
    if(!presetSchema.safeParse(source).success||body.spec!==undefined)throw new AppError(400,'invalid_preset','预设服务地址由 Chives 管理。');
    spec=preset(String(source),body.key);name=templates.find(t=>t.id===source)!.name;
  }
  const parsed=entrySchema.safeParse({source,name,spec,id:old?.id??'ext_'+randomUUID().replaceAll('-','').slice(0,16),
    revision:randomUUID(),enabled:old?.enabled??true,tools:[]});
  if(!parsed.success)throw new AppError(400,'invalid_name','请填写 1 至 80 字的服务名称。');
  return parsed.data;
}
export function updateEntry(data:string,entry:Entry,previous?:Entry){
  const all=read(data),i=all.findIndex(e=>e.id===entry.id);
  if(previous&&all[i]?.revision!==previous.revision)throw new AppError(409,'stale','连接已变更，请刷新后重试。');
  if(all.some(e=>e.id!==entry.id&&(e.name===entry.name||(entry.source!=='custom'&&e.source===entry.source))))throw new AppError(409,'duplicate','此服务已经添加。');
  entry.revision=randomUUID();
  if(i<0)all.push(entry);else all[i]=entry;
  write(data,all);
}
export function removeEntry(data:string,entry:Entry){write(data,read(data).filter(e=>e.id!==entry.id));}
export function mountConnections(data:string,ids:string[]):McpServer[]{
  if(!ids.some(id=>id.startsWith('ext_')))return [];
  return installed(data).filter(e=>e.enabled&&ids.includes(e.id)).map(e=>({name:e.id,command:process.execPath,
    args:[...(import.meta.url.endsWith('.ts')?['--import',import.meta.resolve('tsx'),join(import.meta.dirname,'mcp-bridge.ts')]:[join(import.meta.dirname,'mcp-bridge.js')]),data,e.id],env:approvedOnly()?[{name:'CHIVES_MCP_POLICY',value:'approved'}]:[]}));
}

export async function manageConnection(data:string,body:Record<string,unknown>,official:readonly string[]){
  const {discover}=await import('./mcp-client.js');
  const action=body.action;
  if(action==='add'||action==='probe'){
    if(body.id!==undefined)throw new AppError(400,'invalid_id','新服务的标识由平台生成。');
    const draft=parseDraft(body);
    if(official.includes(draft.name))throw new AppError(409,'reserved','该名称已用于内置服务。');
    draft.tools=await discover(draft.spec);
    if(action==='add')updateEntry(data,draft);
    return describeEntry(draft);
  }
  const entry=installed(data).find(e=>e.id===body.id);
  if(!entry)throw new AppError(404,'unknown_connection','请选择已添加的第三方服务。');
  if(body.revision!==entry.revision)throw new AppError(409,'stale','连接已变更，请刷新后重试。');
  if(action==='test')return {...describeEntry(entry),tools:await discover(entry.spec)};
  if(action==='delete'){removeEntry(data,entry);return {id:entry.id};}
  if(action==='toggle'&&typeof body.enabled==='boolean'){
    const changed={...entry,enabled:body.enabled};
    updateEntry(data,changed,entry);return describeEntry(changed);
  }
  if(action==='replace'){
    const draft=parseDraft(body,entry);
    if(official.includes(draft.name))throw new AppError(409,'reserved','该名称已用于内置服务。');
    draft.tools=await discover(draft.spec);
    updateEntry(data,draft,entry);return describeEntry(draft);
  }
  throw new AppError(400,'invalid_action','请选择可用操作。');
}
