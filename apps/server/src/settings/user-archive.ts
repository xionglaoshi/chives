import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { createHash } from 'node:crypto';
import { closeSync, openSync, readSync, existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { AppError } from '../errors.js';

function boundedText(file: string, characters: number): string {
  try {
    const fd = openSync(file, 'r');
    try {
      const buf = Buffer.alloc(characters * 4);
      const size = readSync(fd, buf, 0, buf.length, 0);
      return Array.from(buf.toString('utf8', 0, size)).slice(0, characters).join('');
    } finally { closeSync(fd); }
  } catch { return ''; }
}

export class UserArchive {
  private readonly root: string;
  constructor(private readonly dataDir: string, private readonly repoRoot: string) { this.root = join(dataDir, 'user'); }

  private catalog() {
    const dir = join(this.repoRoot,'presets/user-attributes');
    return readdirSync(dir).filter(name => /^A[0-9]+-[a-z0-9_]+\.json$/.test(name)).map(name => {
      const field = JSON.parse(readFileSync(join(dir,name),'utf8')) as {id:string;key:string;label:string;scale:string;review_when:string};
      return field;
    });
  }


  installed() { return existsSync(join(this.root, 'attributes', 'values.json')); }

  context() {
    const index = boundedText(join(this.root, 'user-index.md'), 1000);
    const recent = boundedText(join(this.root, 'recent-memory.md'), 2000);
    return '本轮共享用户档案（资料）。涉及个人问题按需用 read_user_attributes 查值，find_user_memory 查出处。持仓只用获授权的持仓工具，区分实盘与模拟。属性变更须提交证据，待审核。\n'+index+'\n'+recent;
  }

  attributes(keys: unknown) {
    if (!Array.isArray(keys) || keys.length > 12 || !keys.every(k=>typeof k==='string'))
      throw new AppError(400, 'invalid_attribute', '请按编号或英文键选至多 12 项。空列表返回属性目录。');
    const catalog = this.catalog();
    if (!keys.length) return catalog.map(({id,key,label})=>({id,key,label}));
    const values = JSON.parse(readFileSync(join(this.root,'attributes/values.json'),'utf8'));
    const db=new DatabaseSync(join(this.root,'reviews/attribute-proposals.sqlite'),{readOnly:true});
    try {
      const latest=db.prepare("SELECT b.origin,d.reason,d.new_value FROM decisions d JOIN batches b USING(source_id) WHERE d.attribute=? AND d.decision='applied' ORDER BY d.seq DESC LIMIT 1");
      return keys.map((key:string) => {
        const field=catalog.find(f=>f.key===key||f.id===key);
        if (!field) throw new AppError(400,'invalid_attribute','未知的用户属性');
        const row=latest.get(field.key);
        const value=values[field.key]??null;
        if (!row || JSON.stringify(JSON.parse(String(row.new_value)))!==JSON.stringify(value))
          return {...field,value:null};
        if (row.origin==='provisional')
          return {...field,value:null,provisionalValue:value,status:'临时代填，待新版问卷替换',reason:row.reason};
        return {...field,value};
      });
    } finally { db.close(); }
  }

  propose(key: string, value: unknown, evidence: {bot:string;task:string;message:string;quote:string;reason:string;alternatives:string}) {
    const field = this.attributes([key])[0];
    if (!field || !('value' in field)) throw new AppError(400,'invalid_attribute','未知的用户属性');
    const suggested = JSON.stringify(value);
    if (suggested === undefined || suggested.length>2000) throw new AppError(400,'invalid_value','建议值无效。');
    const db = new DatabaseSync(join(this.root,'reviews/attribute-proposals.sqlite'));
    try {
      const base = db.prepare("SELECT seq,new_value FROM decisions WHERE attribute=? AND decision='applied' ORDER BY seq DESC LIMIT 1").get(field.key);
      const revision = Number(base?.seq??0);
      const id = createHash('sha256').update(JSON.stringify([field.key,evidence.message,suggested,revision])).digest('hex');
      db.prepare('INSERT OR IGNORE INTO proposals(id,attribute,expected_value,suggested_value,base_revision,bot,source_task,source_message,quote,reason,alternatives,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)')
        .run(id,field.key,String(base?.new_value??'null'),suggested,revision,evidence.bot,evidence.task,evidence.message,evidence.quote,evidence.reason,evidence.alternatives,new Date().toISOString());
      const row=db.prepare('SELECT status FROM proposals WHERE id=?').get(id);
      return {id,status:String(row?.status??'pending'),field,verifiedSource:evidence.quote};
    } finally { db.close(); }
  }

  async mergeSupported(id:string) {
    const python=join(this.repoRoot,'packages/portfolio-mcp/.venv/bin/python');
    const result=await promisify(execFile)(python,[join(this.repoRoot,'scripts/user_archive.py'),'--data',this.dataDir,'merge-supported','--proposal',id],{timeout:10000});
    return JSON.parse(result.stdout).merged===true;
  }

  recordReview(id:string, status:'supported'|'needs_evidence'|'rejected', reviewer:string, reason:string) {
    const db=new DatabaseSync(join(this.root,'reviews/attribute-proposals.sqlite'));
    try {
      db.prepare("UPDATE proposals SET status=?,reviewer=?,review_reason=? WHERE id=? AND status='pending'").run(status,reviewer,reason,id);
    } finally { db.close(); }
  }

  search(query: unknown) {
    if (typeof query!=='string' || !query.trim() || query.length>100)
      throw new AppError(400, 'invalid_query', '请提供 1 至 100 字的检索词。');
    const db = new DatabaseSync(join(this.root,'index/wiki-search.sqlite'),{readOnly:true});
    try {
      const term = query.trim();
      if (Array.from(term).length < 3) {
        return db.prepare('SELECT path,title,substr(body,1,300) AS excerpt FROM sections WHERE instr(title,?) OR instr(body,?) LIMIT 8').all(term,term);
      }
      return db.prepare("SELECT path,title,snippet(sections,2,'','','…',45) AS excerpt FROM sections WHERE sections MATCH ? ORDER BY rank LIMIT 8")
        .all('"'+term.replaceAll('"','""')+'"');
    } finally { db.close(); }
  }
}
