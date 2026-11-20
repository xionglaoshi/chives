import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
import {StreamableHTTPClientTransport} from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import {SSEClientTransport} from '@modelcontextprotocol/sdk/client/sse.js';
import type {McpDescriptor} from './mcp-connections.js';
import {AppError} from '../errors.js';

export async function connect(spec:McpDescriptor){
  const client=new Client({name:'chives-capabilities',version:'1'});
  const transport='command' in spec ? new StdioClientTransport({command:spec.command,args:spec.args,env:spec.env,stderr:'ignore'}) :
    spec.type==='sse'?new SSEClientTransport(new URL(spec.url),{requestInit:{headers:spec.headers,redirect:'error'}}):
    new StreamableHTTPClientTransport(new URL(spec.url),{requestInit:{headers:spec.headers,redirect:'error'}});
  let timer:NodeJS.Timeout|undefined;
  try{
    await Promise.race([client.connect(transport as Parameters<Client['connect']>[0]),new Promise<never>((_,reject)=>{timer=setTimeout(()=>reject(Error('timeout')),12000);})]);
    return client;
  }catch{await client.close().catch(()=>{});throw new AppError(422,'mcp_connection','未完成 MCP 握手，请检查服务地址、认证信息或本机命令。');}
  finally{clearTimeout(timer);}
}
export async function discover(spec:McpDescriptor){
  const client=await connect(spec);
  try{
    if(!client.getServerCapabilities()?.tools)throw new AppError(422,'no_tools','此服务没有声明 MCP 工具能力。');
    const tools:string[]=[], seen=new Set<string>();let cursor:string|undefined;
    do{
      const page=await client.listTools(cursor?{cursor}:{},{timeout:8000});
      tools.push(...page.tools.map(t=>t.name));cursor=page.nextCursor;
      if(cursor&&seen.has(cursor)||tools.length>2000||seen.size>=40)throw Error('invalid pagination');
      if(cursor)seen.add(cursor);
    }while(cursor);
    return tools;
  }catch(e){if(e instanceof AppError)throw e;throw new AppError(422,'tools_failed','服务已响应，但无法读取完整工具清单。');}
  finally{await client.close().catch(()=>{});}
}
