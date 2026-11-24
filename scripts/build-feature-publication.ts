/** Export explicitly selected public research into a static, content-addressed directory. */
import { createHash, randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, realpathSync, renameSync, writeFileSync } from 'node:fs';
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { homedir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

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

const files: {path: string; sha256: string}[] = [];
let publishedAt = '';

function readSource(path: string) {
  const file = realpathSync(join(sourcePath, path));
  const position = relative(sourcePath, file);
  if (isAbsolute(position) || position === '..' || position.startsWith('..' + sep)) {
    throw new Error('Publication input must be inside the production workspace');
  }
  return JSON.parse(readFileSync(file, 'utf8'));
}

function publish(path: string, value: unknown) {
  const bytes = Buffer.from(JSON.stringify(value) + '\n');
  const target = join(outputPath, path);
  mkdirSync(dirname(target), { recursive: true });
  const temporary = target + '.' + randomUUID() + '.tmp';
  writeFileSync(temporary, bytes, { flag: 'wx' });
  renameSync(temporary, target);
  return createHash('sha256').update(bytes).digest('hex');
}

const objects: { path: string; content: unknown }[] = [];
for (const id of new Set(board)) {
  if (!knownBoards.has(id)) throw new Error('Unknown ranking: ' + id);
  const path = 'rankings/' + id + '.json';
  const item = readSource(path);
  if (item.id !== id || !Array.isArray(item.board?.rows) || typeof item.publishedAt !== 'string') {
    throw new Error('Invalid ranking: ' + id);
  }
  if (!publishedAt || item.publishedAt > publishedAt) publishedAt = item.publishedAt;
  objects.push({ path, content: {
    id, publishedAt: item.publishedAt, retained: item.retained === true,
    board: { ...selectFields(item.board, boardFields),
      rows: item.board.rows.map((row: Record<string, unknown>) => selectFields(row, rowFields)) },
  } });
}
for (const codeId of new Set(code)) {
  if (!/^\d{6}\.(SH|SZ|BJ)$/.test(codeId)) throw new Error('Invalid stock code: ' + codeId);
  const path = 'stocks/' + codeId + '.json';
  const item = readSource(path);
  if (item.code !== codeId) throw new Error('Invalid stock profile: ' + codeId);
  const valuation = item.valuation ? selectFields(item.valuation, ['low','high','valuationKind','score']) : null;
  for (const field of ['analysis','strategy']) {
    if (item[field] != null && typeof item[field] !== 'string') throw new Error('Expected text: ' + field);
  }
  objects.push({ path, content: { code:codeId, ...selectFields(item,['name','asOf','analysis','strategy']), valuation } });
}
for (const object of objects) {
  files.push({ path: object.path, sha256: publish(object.path, object.content) });
}
publish('catalog.json', { schema: 2, publishedAt: publishedAt || day+'T00:00:00+08:00', files });
console.log(files.length + ' published feature files prepared');
