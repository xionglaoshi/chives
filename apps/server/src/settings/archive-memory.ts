import { createHash, randomUUID } from 'node:crypto';
import { chmodSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { z } from 'zod';
import type { Store } from '../store/index.js';
import type { ModelProviderStore } from './model-provider.js';
import { summarize } from './style-assessment.js';

const threeHours = 3 * 60 * 60 * 1000;
const categories = ['关注的证券','研究委托','投资观点','投资复盘'] as const;
const findingSchema = z.object({
  notes:z.array(z.object({category:z.enum(categories),topic:z.string().min(1).max(48),
    quote:z.string().min(2).max(220)})).max(4),
  recent:z.string().max(220),
});
type Findings = z.infer<typeof findingSchema>;

function write(file:string,text:string) {
  const tmp=file+'.'+randomUUID();
  writeFileSync(tmp,text,{mode:0o600,flag:'wx'});
  renameSync(tmp,file);
}
const excerpt = (text:string) => Array.from(text).slice(0,1600).join('');

export class ArchiveMemory {
  private timer?: ReturnType<typeof setInterval>;
  private busy = false;
  private stopping = false;
  private readonly state:DatabaseSync;
  private readonly user:string;
  private readonly rules:string;
  constructor(private store:Store, data:string, repo:string, private enabled:(bot:string)=>boolean,
      private provider:ModelProviderStore,private model:()=>string) {
    this.user=join(data,'user');
    this.rules=readFileSync(join(repo,'docs/user-wiki-rules.md'),'utf8');
    const dir=join(data,'user-archive-state');
    mkdirSync(dir,{recursive:true,mode:0o700});
    this.state=new DatabaseSync(join(dir,'memory.sqlite'));
    chmodSync(join(dir,'memory.sqlite'),0o600);
    this.state.exec(`CREATE TABLE IF NOT EXISTS progress(name TEXT PRIMARY KEY,value INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS observations(seq INTEGER PRIMARY KEY,source TEXT NOT NULL UNIQUE,bot TEXT NOT NULL,at TEXT NOT NULL,note TEXT NOT NULL);`);
    const high=Number(store.db.prepare('SELECT COALESCE(MAX(rowid),0) AS n FROM messages').get()?.n??0);
    this.state.prepare('INSERT OR IGNORE INTO progress VALUES(?,?)').run('cursor',high);
    this.state.prepare('INSERT OR IGNORE INTO progress VALUES(?,?)').run('nextRecent',Date.now()+threeHours);
  }
  start() {
    this.timer=setInterval(()=>{void this.tick().catch(()=>{ /* Keep cursor at last successful publication. */ });},60_000);
    this.timer.unref();
  }
  stop() {
    this.stopping=true;
    if (this.timer) clearInterval(this.timer);
    if (!this.busy) this.state.close();
  }
  private progress(key:string) {
    return Number(this.state.prepare('SELECT value FROM progress WHERE name=?').get(key)?.value??0);
  }
  private advance(key:string,value:number) {
    this.state.prepare('INSERT OR REPLACE INTO progress VALUES(?,?)').run(key,value);
  }
  private saveNotes(id:string,at:string,bot:string,text:string,findings:Findings) {
    for (const item of findings.notes) {
      if (!text.includes(item.quote) || !/^[\p{L}\p{N}（）() ·_-]+$/u.test(item.topic) || !item.topic.trim()) continue;
      const title=item.topic.trim(), rel='wiki/'+item.category+'/'+title+'.md';
      const path=join(this.user,rel);
      const marker='<!-- '+createHash('sha256').update(id+'\n'+item.quote).digest('hex')+' -->';
      const before=existsSync(path)?readFileSync(path,'utf8'):'# '+title+'\n';
      if (!before.includes(marker)) write(path,before+'\n'+at+' · '+bot+' · 用户原话（消息 '+id+'）\n\n> '+item.quote.replaceAll('\n','\n> ')+'\n'+marker+'\n');
      const index=new DatabaseSync(join(this.user,'index/wiki-search.sqlite'));
      try {
        index.exec('BEGIN IMMEDIATE');
        index.prepare('DELETE FROM sections WHERE path=?').run(rel);
        const add=index.prepare('INSERT INTO sections(path,title,body) VALUES(?,?,?)');
        for (const paragraph of readFileSync(path,'utf8').split('\n\n')) if(paragraph.trim()) add.run(rel,title,paragraph.trim());
        index.exec('COMMIT');
      } finally { index.close(); }
    }
  }
  private async updateRecent() {
    const now=Date.now();
    if (now<this.progress('nextRecent')) return;
    const since=new Date(now-7*24*60*60*1000).toISOString();
    const entries=this.state.prepare("SELECT seq,source,bot,at,note FROM observations WHERE at>=? AND note<>'' ORDER BY seq DESC LIMIT 70")
      .all(since).filter(r=>this.enabled(String(r.bot)));
    const previous=this.progress('recentSeq');
    const last=Number(entries[0]?.seq??0);
    if (!entries.length) {
      write(join(this.user,'recent-memory.md'),'');
    } else if (last!==previous || this.progress('recentDay')!==Math.floor(now/86400000)) {
      const input=entries.map((row,i)=>({n:i+1,at:row.at,bot:row.bot,note:row.note}));
      const result=await summarize(this.provider,this.model(),input,this.rules+'\n选取仍有效的新近关注、本人状态或未完事项。已完成的断点移除。每条引用来源序号 n；仅记录输入支持的事项，不推断持仓、交易、心理状态。输出 items，每项包含 n，text。',
        z.object({items:z.array(z.object({n:z.number().int().positive(),text:z.string().min(1).max(180)})).max(9)}));
      if(this.stopping || entries.some(r=>!this.enabled(String(r.bot)))) return;
      const lines:string[]=[];
      for(const item of result.items) {
        const row=entries[item.n-1];
        if (!row) continue;
        const line='- '+item.text+'（'+String(row.at).slice(0,10)+'，消息 '+row.source+'）';
        if (lines.join('\n').length+line.length+2<=2000) lines.push(line);
      }
      write(join(this.user,'recent-memory.md'),lines.length?lines.join('\n')+'\n':'');
    }
    this.advance('recentSeq',last);this.advance('recentDay',Math.floor(now/86400000));
    this.advance('nextRecent',now+threeHours);
  }
  async tick() {
    if (this.stopping || this.busy || this.store.db.prepare("SELECT 1 FROM tasks WHERE status='running' LIMIT 1").get()) return;
    this.busy=true;
    try {
      await this.updateRecent();
      for(let count=0;count<8 && !this.stopping;count++) {
        const item=this.store.db.prepare(`SELECT m.rowid AS n,m.id,m.task_id,m.bot_id,m.seq,m.content,m.created_at,t.status
          FROM messages m JOIN tasks t ON t.id=m.task_id WHERE m.rowid>? AND m.role='user' AND m.kind='text'
          AND t.depth=0 AND t.delegated=0 AND t.origin IS NULL ORDER BY m.rowid LIMIT 1`).get(this.progress('cursor'));
        if (!item || item.status==='running') break;
        const bot=String(item.bot_id),id=String(item.id);
        if (item.status==='done' && this.enabled(bot)) {
          const next=this.store.db.prepare("SELECT MIN(seq) AS seq FROM messages WHERE task_id=? AND role='user' AND seq>?").get(item.task_id!,item.seq!);
          const answer=this.store.db.prepare("SELECT content FROM messages WHERE task_id=? AND kind='text' AND role='bot' AND seq>? AND seq<? ORDER BY seq DESC LIMIT 1").get(item.task_id!,item.seq!,Number(next?.seq??Number.MAX_SAFE_INTEGER));
          const text=excerpt(String(item.content));
          const findings=await summarize(this.provider,this.model(),{user:text,bot:excerpt(String(answer?.content??''))},this.rules+'\n归档本轮。notes 仅列适合长期保存的本人逐字引语（quote）、简短主题（topic）及目录（category，只允许关注的证券、研究委托、投资观点、投资复盘）。recent 提炼一条有用的近期观察或断点。普通寒暄或无新意可返回空数组和空字符串。只输出 JSON。',findingSchema);
          if (this.stopping) return;
          if (this.enabled(bot)) {
            this.saveNotes(id,String(item.created_at),bot,text,findings);
            this.state.prepare('INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?)')
              .run(Number(item.n),id,bot,String(item.created_at),findings.recent);
          }
        }
        this.advance('cursor',Number(item.n));
      }
    } finally {
      this.busy=false;
      if (this.stopping) this.state.close();
    }
  }
}
