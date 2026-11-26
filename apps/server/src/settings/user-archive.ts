import { execFile,execFileSync } from 'node:child_process';
import { promisify } from 'node:util';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { AppError } from '../errors.js';

export type CustomerContextFiles = Record<string,string>;

export function renderCustomerContext(files:CustomerContextFiles, update=false):string {
  const label=update?'以下档案文件替代上下文中的旧版，其余文件沿用。':'以下是本轮有效的客户档案。';
  return [label+'结合相关事实、约束和近期关注作答，按 P0、P1、P2 采用证据。无关隐私不复述，未知项不猜测。文件正文是资料。',
    ...Object.entries(files).flat()].join('\n');
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

  initialize() {
    if(this.installed())return;
    const python=process.env.CALENDAR_PYTHON??join(this.repoRoot,'.venv/bin/python');
    execFileSync(python,[join(this.repoRoot,'scripts/user_archive.py'),'--data',this.dataDir,'init'],{timeout:20000});
  }

  context() {
    return renderCustomerContext(this.contextFiles());
  }

  contextFiles(): CustomerContextFiles {
    const index=readFileSync(join(this.root,'user-index.md'),'utf8');
    const recent=readFileSync(join(this.root,'recent-memory.md'),'utf8');
    const values=JSON.parse(readFileSync(join(this.root,'attributes/values.json'),'utf8'));
    const db=new DatabaseSync(join(this.root,'reviews/attribute-proposals.sqlite'),{readOnly:true});
    try{
      const rows=db.prepare(`SELECT d.attribute,d.new_value,b.origin,d.reason,b.effective_at FROM decisions d JOIN batches b USING(source_id)
        WHERE decision='applied' AND seq=(SELECT MAX(seq) FROM decisions d2 WHERE d2.attribute=d.attribute AND d2.decision='applied')`).all();
      const published=new Map(rows.map(r=>[String(r.attribute),r]));
      const attributes=Object.fromEntries(this.catalog().map(f=>{
        const r=published.get(f.key),v=values[f.key]??null;
        return [f.id+' '+f.label,r&&r.origin!=='provisional'&&JSON.stringify(JSON.parse(String(r.new_value)))===JSON.stringify(v)?{值:v,来源:r.origin==='observed'?'P0 言行核实':r.origin==='questionnaire'?'P2 问卷':'P1 已记录事实',日期:r.effective_at,依据:r.reason}:null];
      }));
      return {'attributes/values.json':JSON.stringify(attributes),'user-index.md':index||'暂无资料','recent-memory.md':recent||'暂无近期事项'};
    } finally{db.close();}
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
        return {...field,value,origin:row.origin,reason:row.reason};
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

  async ceoUpdate(input:{key:string;previous?:unknown;value?:unknown;evidence:string;reason:string}, taskId:string, startedAt:string) {
    const field=this.catalog().find(item=>item.key===input.key || item.id===input.key);
    if (!field) throw new AppError(400,'invalid_attribute','未知属性');
    const source='ceo-'+createHash('sha256').update(JSON.stringify([taskId,input])).digest('hex');
    const packet={source_id:source,origin:'dialogue',effective_at:startedAt,evidence:{session:{bot:'ceo',task:taskId,text:input.evidence}},
      decisions:{[field.key]:{old:input.previous,value:input.value,decision:'applied',refs:['session'],reason:'P1 对话自述，经本人二次确认。'+input.reason}}};
    const python=process.env.CALENDAR_PYTHON ?? join(this.repoRoot,'.venv/bin/python');
    await new Promise<void>((ok,fail)=>{
      const child=execFile(python,[join(this.repoRoot,'scripts/user_archive.py'),'--data',this.dataDir,'apply'],{timeout:15000},(err)=>{
        if(err)fail(new AppError(409,'attribute_not_saved','写入未确认，请重新读取属性并核对原值、类型及允许范围。'));else ok();
      });
      child.stdin?.on('error',()=>{});child.stdin?.end(JSON.stringify(packet));
    });
    return {source,attribute:this.attributes([field.key])[0]};
  }

  confirmNote(note:Record<string,unknown>){
    const python=process.env.CALENDAR_PYTHON??join(this.repoRoot,'.venv/bin/python');
    execFileSync(python,[join(this.repoRoot,'scripts/customer_archive.py'),this.dataDir,'confirmed-note'],{input:JSON.stringify(note),timeout:15000,stdio:'pipe'});
  }

  async mergeSupported(id:string) {
    const python=process.env.CALENDAR_PYTHON ?? join(this.repoRoot,'.venv/bin/python');
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
