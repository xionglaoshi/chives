/** Export explicitly selected public research into a static, content-addressed directory. */
import { createHash, randomUUID } from 'node:crypto';
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { parseArgs } from 'node:util';
import { latestHoldingValuation } from '../apps/server/src/dashboard/holding-valuations.js';

const boardFields = ['title','note','url','asOf','columns'];
const rowFields = ['code','name','metric','why','url','rankGain','priceDate','r5','t5','r30','t30',
  'increasePct','example','disclosed','priceSource','net','capRatio','recommendingBrokers','recent',
  'shift','baselineGain','sampledDays','rank','comments','score','market','shareChange','volumeRatio','date'];
const knownBoards = new Set(['emerging','private','in','out','rating','popular','authors','global']);

function selectFields(record: Record<string, unknown>, fields: string[]) {
  return Object.fromEntries(fields.filter(field => Object.hasOwn(record, field)).map(field => {
    const value = record[field];
    const scalar = (item: unknown) => item === null || ['string','number','boolean'].includes(typeof item);
    if (!scalar(value) && !(Array.isArray(value) && value.every(scalar))) {
      throw new Error('Unsupported public field: ' + field);
    }
    return [field, value];
  }));
}

const {values} = parseArgs({ options: {
  source: {type:'string'}, output: {type:'string'}, day: {type:'string'},
  board: {type:'string',multiple:true}, code: {type:'string',multiple:true},
} });
const {source, output, day, board = [], code = []} = values;
if (!source || !output || !day || !/^\d{4}-\d{2}-\d{2}$/.test(day) || (!board.length && !code.length)) {
  throw new Error('Specify --source, --output, --day and explicit --board or --code selections');
}

const valuations = Object.fromEntries([...new Set(code)].map(id => {
  const estimate = latestHoldingValuation(source,id,day);
  if (!estimate) throw new Error('Missing approved valuation: ' + id);
  return [id,estimate];
}));
let hotspots = null;
if (board.length) {
  const snapshot = JSON.parse(readFileSync(join(source,'hotspots','latest.json'),'utf8'));
  hotspots = {
    ...selectFields(snapshot,['schema','publishedAt']),
    retained: board.filter(id => snapshot.retained?.includes(id)),
    boards: Object.fromEntries([...new Set(board)].map(id => {
      if (!knownBoards.has(id) || !Array.isArray(snapshot.boards?.[id]?.rows)) {
        throw new Error('Missing approved board: ' + id);
      }
      const entry = snapshot.boards[id];
      return [id,{...selectFields(entry,boardFields),
        rows: entry.rows.map((row: Record<string, unknown>) => selectFields(row,rowFields))}];
    })),
  };
}
const bytes = Buffer.from(JSON.stringify({hotspots,valuations}) + '\n');
const sha256 = createHash('sha256').update(bytes).digest('hex');
mkdirSync(output,{recursive:true});
function publish(name: string, value: string | Buffer) {
  const temporary = join(output,randomUUID()+'.tmp');
  writeFileSync(temporary,value,{flag:'wx'});
  renameSync(temporary,join(output,name));
}
publish(sha256+'.json',bytes);
publish('manifest.json',JSON.stringify({schema:1,sha256})+'\n');
console.log(sha256);
