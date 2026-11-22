import { cpSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { expect, it } from 'vitest';
import { createApp } from '../src/app.js';
import { closeServer, listen, repoRoot, testConfig } from './support.js';

it('reserves hiring and staffing for the owner and permits delegation to a hired colleague', async () => {
  const root=mkdtempSync(join(tmpdir(),'chives-operator-'));
  const config={...testConfig(join(root,'data')),botsDir:join(root,'bots')};
  for (const name of ['operator','_shared']) cpSync(join(repoRoot,'bots',name),join(config.botsDir,name),{recursive:true});
  const app=createApp({config,startSchedulers:false});
  const base=await listen(app.server);
  try {
    const parent=app.store.tasks.create({botId:'operator',startedAt:new Date().toISOString()});
    const token=app.sessions.issue({botId:'operator',taskId:parent.id,depth:0});
    const staff='/api/settings/desk/staff', employment='/api/settings/desk/employment';
    async function send(url:string, body:object, method='POST', bot=false) {
      return fetch(base+url,{method,headers:{'Content-Type':'application/json','X-Chives-Kernel-Manager':'local',
        ...(bot?{Authorization:'Bearer '+token}:{})},body:JSON.stringify(body)});
    }
    const member={id:'cash-review',name:'回款研究员',role:'核对现金流'};
    expect((await send('/api/internal/experts/create',member,'POST',true)).status).toBe(403);
    expect((await send(staff,{action:'create',...member},'POST',true)).status).toBe(403);
    expect((await send(staff,{action:'delete',id:'operator'})).status).toBe(403);
    expect((await send(employment,{expected:{operator:true},hiredIds:[]},'PUT')).status).toBe(400);
    const created=await send(staff,{action:'create',...member});
    expect(await created.json()).toContainEqual({id:member.id,name:member.name,hired:false,permanent:false});
    const expected=(hired:boolean)=>({operator:true,[member.id]:hired});
    const hire={expected:expected(false),hiredIds:['operator',member.id]};
    expect((await send(employment,hire,'PUT',true)).status).toBe(403);
    expect((await send(employment,hire,'PUT')).status).toBe(200);
    const delegated=await send('/api/internal/delegations',{bot:member.id,brief:'核对现金流',report_back:false,wait_seconds:5},'POST',true);
    expect((await delegated.json()).status).toBe('done');
    expect((await send(employment,{expected:expected(true),hiredIds:['operator']},'PUT')).status).toBe(200);
    expect((await send(staff,{action:'delete',id:member.id})).status).toBe(200);
    expect(app.registry.list().map(bot=>bot.id)).toEqual(['operator']);
  } finally {
    app.sse.closeAll();await closeServer(app.server);await app.close();
    rmSync(root,{recursive:true,force:true});
  }
});
