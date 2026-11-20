import {Server} from '@modelcontextprotocol/sdk/server/index.js';
import {StdioServerTransport} from '@modelcontextprotocol/sdk/server/stdio.js';
import {ListToolsRequestSchema,CallToolRequestSchema} from '@modelcontextprotocol/sdk/types.js';
import {findEnabled} from './mcp-connections.js';
import {connect} from './mcp-client.js';

const [data,id]=process.argv.slice(2);
if(!data||!id)throw Error('Missing connection');
const entry=findEnabled(data,id);
if(!entry)throw Error('Connection unavailable');
const server=new Server({name:entry.name,version:'1'},{capabilities:{tools:{}}});
let upstream:ReturnType<typeof connect>|undefined;
function remote(){
  const current=findEnabled(data!,id!);
  if(!current||current.revision!==entry?.revision)throw Error('连接已变更，请开始新的 Bot 任务。');
  return upstream??=connect(current.spec).catch(e=>{upstream=undefined;throw e;});
}
server.setRequestHandler(ListToolsRequestSchema,async request=>(await remote()).listTools(request.params??{}));
server.setRequestHandler(CallToolRequestSchema,async (request,ctx)=>{
  return (await remote()).callTool(request.params,undefined,{signal:ctx.signal});
});
server.onclose=()=>{void upstream?.then(c=>c.close()).catch(()=>{});};
await server.connect(new StdioServerTransport());
