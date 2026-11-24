/** Export explicitly selected public research into a static, content-addressed directory. */
import { createHash, randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, realpathSync, renameSync, writeFileSync } from 'node:fs';
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { homedir } from 'node:os';
import { fileURLToPath } from 'node:url';
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

const installation = fileURLToPath(new URL('../', import.meta.url));
const standardRoot = join(homedir(), '.chives');
function resolvedPath(path: string): string {
  return existsSync(path) ? realpathSync(path) : join(resolvedPath(dirname(path)), basename(path));
}
const sourcePath = realpathSync(source);
const outputPath = resolvedPath(resolve(output));
for (const root of [resolvedPath(installation), resolvedPath(standardRoot)]) {
  for (const path of [sourcePath, outputPath]) {
    const position = relative(root, path);
    if (!isAbsolute(position) && position !== '..' && !position.startsWith('..' + sep)) {
      throw new Error('Feature source and release output must be outside the Chives installation');
    }
  }
}

const valuations = Object.fromEntries([...new Set(code)].map(id => {
  const estimate = latestHoldingValuation(sourcePath,id,day);
  if (!estimate) throw new Error('Missing approved valuation: ' + id);
  return [id,estimate];
}));
let hotspots = null;
if (board.length) {
  const file = realpathSync(join(sourcePath,'hotspots','latest.json'));
  const position = relative(sourcePath, file);
  if (isAbsolute(position) || position === '..' || position.startsWith('..' + sep)) {
    throw new Error('Board snapshot must be inside the production workspace');
  }
  const snapshot = JSON.parse(readFileSync(file,'utf8'));
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
mkdirSync(outputPath, { recursive: true });
const bytes = Buffer.from(JSON.stringify({hotspots,valuations}) + '\n');
const sha256 = createHash('sha256').update(bytes).digest('hex');
function publish(name: string, value: string | Buffer) {
  const temporary = join(outputPath,randomUUID()+'.tmp');
  writeFileSync(temporary,value,{flag:'wx'});
  renameSync(temporary,join(outputPath,name));
}
publish(sha256+'.json',bytes);
publish('manifest.json',JSON.stringify({schema:1,sha256})+'\n');
console.log(sha256);
