import {mkdtemp,rm,stat} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createServer} from 'node:http';
import {it,expect,vi} from 'vitest';
import {Server} from '@modelcontextprotocol/sdk/server/index.js';
import {StreamableHTTPServerTransport} from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import {SSEServerTransport} from '@modelcontextprotocol/sdk/server/sse.js';
import {ListToolsRequestSchema} from '@modelcontextprotocol/sdk/types.js';
import {connect,discover} from '../src/settings/mcp-client.js';
import {mountConnections} from '../src/settings/mcp-connections.js';
import {createApp} from '../src/app.js';
import {closeServer,listen,repoRoot,testConfig} from './support.js';

it('installs, grants, invokes, revokes and removes a private MCP connection',async()=>{
 const data=await mkdtemp(join(tmpdir(),'chives-mcp-')), app=createApp({config:testConfig(data)});
 const url=await listen(app.server),api=url+'/api/settings/desk/capabilities',assets=url+'/api/bots/expert/assets';
 const headers={'Content-Type':'application/json','X-Chives-Kernel-Manager':'local'};
 const post=(body:object)=>fetch(api,{method:'POST',headers,body:JSON.stringify(body)});
 const get=async()=>(await fetch(api,{headers})).json();
 let client;
 try{
  expect((await fetch(api)).status).toBe(403);
  const spec={command:process.execPath,args:[join(repoRoot,'apps/server/test/fixtures/fake-profile-mcp.mjs')],env:{TEST_ONLY:'fixture-secret'}};
  const resp=await post({action:'add',name:'Fixture',spec});expect(resp.status).toBe(200);
  const entry=await resp.json();
  expect(entry.tools).toContain('profile_get');
  expect((await stat(join(data,'secrets','mcp-connections.json'))).mode&0o777).toBe(0o600);
  let state=await get(); expect(JSON.stringify(state)).not.toContain('fixture-secret');
  expect(state.connections[0].bots).toEqual([]);
  const {profile,options}=await (await fetch(assets)).json();
  expect(options.mcp).toContain(entry.id);expect(profile.mcp).not.toContain(entry.id);
  profile.mcp.push(entry.id);
  expect((await fetch(assets,{method:'PUT',headers,body:JSON.stringify(profile)})).status).toBe(200);
  expect((await get()).connections[0].bots).toHaveLength(1);
  const [bridge]=mountConnections(data,profile.mcp);
  client=await connect({command:bridge.command,args:bridge.args,env:{}});
  expect((await client.listTools()).tools.map(t=>t.name)).toContain('profile_get');
  const result=await client.callTool({name:'profile_get',arguments:{}});
  expect(result.isError).not.toBe(true);expect(JSON.stringify(result.content)).toContain('profile');
  const disabled=await (await post({action:'toggle',id:entry.id,revision:entry.revision,enabled:false})).json();
  expect(mountConnections(data,profile.mcp)).toEqual([]);
  try{const r=await client.callTool({name:'profile_get'});expect(r.isError).toBe(true);}catch(e){expect(String(e)).toContain('连接已变更');}
  expect((await post({action:'delete',id:state.official[0]})).status).toBe(404);
  vi.stubEnv('CHIVES_MCP_POLICY','approved');
  expect((await get()).connections).toEqual([]);
  expect((await post({action:'add',name:'custom',spec})).status).toBe(403);
  expect((await post({action:'add',source:'context7',key:'test',spec})).status).toBe(400);
  vi.unstubAllEnvs();
  expect((await post({action:'delete',id:entry.id,revision:disabled.revision})).status).toBe(200);
  expect((await (await fetch(assets)).json()).profile.mcp).not.toContain(entry.id);
 }finally{vi.unstubAllEnvs();await client?.close();app.sse.closeAll();await closeServer(app.server);await app.close();await rm(data,{recursive:true,force:true});}
},20000);

it.each(['http','sse'] as const)('discovers tools over authenticated %s',async type=>{
 const service=new Server({name:'fixture',version:'1'},{capabilities:{tools:{}}});
 service.setRequestHandler(ListToolsRequestSchema,()=>({tools:[{name:'quote_fixture',inputSchema:{type:'object'}}]}));
 const http=new StreamableHTTPServerTransport({sessionIdGenerator:()=> 'fixture'});
 let events:SSEServerTransport|undefined;
 const listener=createServer(async(req,res)=>{
  if(req.headers['x-fixture']!=='test'){res.writeHead(403).end();return;}
  if(type==='http'){await http.handleRequest(req,res);return;}
  if(req.method==='GET'){events=new SSEServerTransport('/messages',res);await service.connect(events);}
  else await events!.handlePostMessage(req,res);
 });
 try{
  if(type==='http')await service.connect(http);
  const url=await listen(listener);
  expect(await discover({type,url,headers:{'X-Fixture':'test'}})).toEqual(['quote_fixture']);
 }finally{await service.close();listener.closeAllConnections();await closeServer(listener);}
},20000);
