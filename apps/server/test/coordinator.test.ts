import { cpSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { expect, it } from 'vitest';
import { createApp } from '../src/app.js';
import { buildCatalog, loadBots } from '../src/bots/index.js';
import { closeServer, listen, repoRoot, testConfig } from './support.js';

it('creates, configures, renames and delegates to a persistent specialist through the coordinator session', async () => {
  const root = mkdtempSync(join(tmpdir(),'chives-coordinator-'));
  const config = {...testConfig(join(root,'data')), botsDir:join(root,'bots')};
  for (const name of ['chives','_shared']) cpSync(join(repoRoot,'bots',name),join(config.botsDir,name),{recursive:true});
  const app = createApp({config});
  const base = await listen(app.server);
  try {
    const parent = app.store.tasks.create({botId:'chives',startedAt:new Date().toISOString()});
    const token = app.sessions.issue({botId:'chives',taskId:parent.id,depth:0});
    async function post(route:string, body:object, credential=token) {
      const res = await fetch(base+'/api/internal/'+route,{method:'POST',
        headers:{'Content-Type':'application/json',Authorization:'Bearer '+credential},body:JSON.stringify(body)});
      return {status:res.status,body:await res.json()};
    }
    const spec = {id:'cash-exam',name:'回款研究员',role:'核对现金流和应收账龄'};
    expect((await post('experts/create',spec,'invalid')).status).toBe(401);
    const childToken = app.sessions.issue({botId:spec.id,taskId:'child',depth:1});
    expect((await post('experts/create',spec,childToken)).status).toBe(403);
    expect((await post('experts/create',spec)).status).toBe(201);
    expect((await post('experts/create',spec)).status).toBe(409);
    expect((await post('experts/edit',{id:spec.id,name:'现金质量研究员',role:'检查利润兑现'})).status).toBe(200);
    const changes = {skillMode:'selected',skills:['financial-statement'],mcp:['cn_market'],tools:['read_skill','cash_quality'],databases:['bot-library'],preset:'给出证据'};
    expect((await post('experts/assets',{id:spec.id,changes})).body.profile).toMatchObject(changes);
    expect((await post('experts/assets',{id:spec.id,changes:{skills:['missing']}})).status).toBe(400);
    expect((await post('experts/assets',{id:spec.id})).body.profile).toMatchObject(changes);
    expect((await post('experts/roster',{})).body.experts).toContainEqual({id:spec.id,name:'现金质量研究员',role:'检查利润兑现'});
    const reloaded = loadBots(config.botsDir,buildCatalog(repoRoot));
    expect(reloaded.get('chives')?.can_delegate_to).toEqual([spec.id]);
    expect(reloaded.get(spec.id)?.role).toBe('检查利润兑现');
    const delegated = await post('delegations',{bot:spec.id,brief:'回传核对结果',report_back:false,wait_seconds:5});
    expect(delegated.body.status).toBe('done');
    expect(delegated.body.result).toBeTruthy();
  } finally {
    app.sse.closeAll(); await closeServer(app.server); await app.close();
    rmSync(root,{recursive:true,force:true});
  }
});
