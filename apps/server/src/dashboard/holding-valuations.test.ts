import {createHash} from 'node:crypto';
import {mkdirSync,mkdtempSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {afterEach,beforeEach,expect,it} from 'vitest';
import {latestHoldingValuation,readValuationReceipt} from './holding-valuations.js';

const code='600519.SH';
const date='2026-11-24';
let root:string;
beforeEach(()=>{root=mkdtempSync(join(tmpdir(),'chives-valuation-'));});
afterEach(()=>rmSync(root,{recursive:true,force:true}));

function write(day:string,dynamic:object|null) {
  const directory=join(root,'equity-research','valuations',code,day);
  mkdirSync(directory,{recursive:true});
  const contents=JSON.stringify({code,currency:'CNY',requested_as_of:day,as_of:day,model_version:'test',
    static:{low:100,high:120},dynamic});
  const id=createHash('sha256').update(contents).digest('hex');
  writeFileSync(join(directory,id+'.json'),contents);
  return id;
}

it('uses the latest eligible receipt and selects the same band as the watchlist',()=>{
  expect(latestHoldingValuation(root,code,date)).toBeUndefined();
  const staticId=write('2026-11-23',null);
  expect(readValuationReceipt(root,code,'2026-11-23',staticId).estimate)
    .toEqual({low:100,high:120,valuationKind:'静态参考'});
  write(date,{low:110,high:128});
  expect(latestHoldingValuation(root,code,date)).toEqual({low:110,high:128,valuationKind:'动态估值'});
});
