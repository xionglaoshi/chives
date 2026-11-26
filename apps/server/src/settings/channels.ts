import {createHash} from 'node:crypto';
import {setTimeout as delay} from 'node:timers/promises';
import {execFile} from 'node:child_process';
import {existsSync,readdirSync,readFileSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {AppError} from '../errors.js';
import {welcomeWeixin,type WeixinWelcomeState} from './weixin-welcome.js';

type InboxBatch = {
  binding: string;
  cursor: string;
  messages: {id: string; context: string; text: string; media: unknown[]}[];
};

const ids=['weixin','wecom','feishu','telegram','slack','discord'];
export class Channels {
  private inbox?: AbortController;
  private pairing=new Set<string>();
  constructor(private root:string,private data:string,private displayName:(botId:string)=>string,private weixinWelcome?:WeixinWelcomeState){}
  private run(op:string,input:Record<string,unknown>,extra:string[]=[]):Promise<unknown> {
    return new Promise((res,rej)=>{
      const child=execFile(process.env.CALENDAR_PYTHON ?? join(this.root,'.venv/bin/python'),
        [join(this.root,'scripts/settings-channels.py'),this.data,op,...extra],
        {timeout:op==='pair'?270000:op==='media_reply'?100000:45000,maxBuffer:op==='download'?30_000_000:op==='poll'?8_000_000:200000,signal:['poll','reply','ack','download','media_reply'].includes(op)?this.inbox?.signal:undefined,env:{...process.env,PYTHONUNBUFFERED:'1',PYTHONUTF8:'1'}},
        (err,out)=>{try{const r=JSON.parse(out);if(err||r.error)throw Error();res(r);}catch{rej(new AppError(400,'channel_failed','通讯平台未确认，请核对授权资料、会话和网络'));}});
      child.stdin?.on('error',()=>{});child.stdin?.end(JSON.stringify(input));
    });
  }
  hasWelcomedWeixin(): boolean {
    try {
      const config = JSON.parse(readFileSync(join(this.data, 'secrets/channels/weixin.json'), 'utf8'));
      const {account, target, key} = config;
      if (!config.paired || !config.verified || !config.enabled || !account || !target || !key
          || target !== (config.paired_target ?? target)) return false;
      const binding = createHash('sha256').update(JSON.stringify([account, target, key])).digest('hex');
      return this.weixinWelcome?.hasWelcomed(binding) === true;
    } catch {
      return false;
    }
  }

  async manage(action:string,body:Record<string,unknown>) {
    if(action==='list')return this.run('list',{});
    const id=String(body.id);
    if(!ids.includes(id))throw new AppError(400,'channel','未知平台');
    if(this.pairing.has(id))throw new AppError(409,'pairing','正在等待手机授权');
    if(action==='pair'&&ids.slice(0,4).includes(id)){
      rmSync(join(this.data,'secrets/channels',id+'.pair'),{force:true});
      this.pairing.add(id);
      void this.run('pair',{},[id]).catch(()=>{}).finally(()=>this.pairing.delete(id));
      return {started:true};
    }
    if(action==='save'||action==='delete')return this.run(action,body);
    throw new AppError(400,'channel','不支持的操作');
  }
  startInboxes(answer: (id: string, text: string, signal: AbortSignal, downloads: (() => Promise<{name: string; data: string}>)[]) =>
    Promise<{text: string; files: {path:string; botId:string}[]}>) {
    const inbox = new AbortController();
    this.inbox = inbox;
    const {signal} = inbox;
    for (const channel of ['weixin', 'telegram']) void (async () => {
      const run = (op: string, body: Record<string, unknown> = {}) => this.run(op, {...body, id: channel});
      let reportedFailure = false;
      while (!signal.aborted) {
        let wait = 1000;
        let stage = 'poll';
        try {
          const batch = await run('poll') as InboxBatch | {enabled: false};
          signal.throwIfAborted();
          if ('binding' in batch) {
            for (const message of batch.messages) {
              if (channel === 'weixin' && this.weixinWelcome) {
                stage = 'welcome';
                await welcomeWeixin(this.weixinWelcome, batch.binding, async (text, deliveryId) => {
                  const result = await run('reply', {binding: batch.binding, deliveryId, context: message.context,
                    message: this.signedMessage('ceo', text)}) as {ok?: boolean};
                  if (!result.ok) throw new Error('Weixin welcome did not complete');
                });
                signal.throwIfAborted();
              }
              const id = createHash('sha256').update(batch.binding + ':' + message.id).digest('hex');
              const downloads = message.media.map(item => async () =>
                await run('download', {binding: batch.binding, item}) as {name: string; data: string});
              stage = 'answer';
              const {text, files} = await answer(channel + '-' + id, message.text, signal, downloads);
              signal.throwIfAborted();
              stage = 'reply';
              await run('reply', {binding: batch.binding, deliveryId: id, context: message.context, message: this.signedMessage('ceo', text)});
              stage = 'media reply';
              for (const [index, file] of files.entries()) {
                const mediaId = id + '-file-' + index;
                await run('reply', {binding: batch.binding, deliveryId: mediaId + '-label', context: message.context,
                  message: this.signedMessage(file.botId, file.path.split('/').at(-1) ?? '附件')});
                await run('media_reply', {binding: batch.binding, deliveryId: mediaId, context: message.context, path: file.path});
              }
            }
            stage = 'ack';
            await run('ack', {binding: batch.binding, cursor: batch.cursor});
          } else {
            wait = 5000;
          }
          if (reportedFailure) console.info(`Chives ${channel} inbox recovered`);
          reportedFailure = false;
        } catch {
          if (!signal.aborted && !reportedFailure) console.warn(`Chives ${channel} inbox failed at ${stage}; will retry`);
          reportedFailure = true;
          wait = 10_000;
        }
        await delay(wait, undefined, {signal, ref: false}).catch(() => {});
      }
    })();
  }
  stopInboxes() {
    this.inbox?.abort();
  }

  private signedMessage(botId:string, message:string){
    return `【${this.displayName(botId)}：】${message}`;
  }
  deliver(botId:string,title:string,body:string){
    this.broadcastReply(botId, title+'\n'+body);
  }
  broadcastReply(botId:string, text:string, except?:string){

    const folder=join(this.data,'secrets','channels');if(!existsSync(folder))return;
    for(const file of readdirSync(folder)){
      const id=file.replace(/\.json$/,'');if(!ids.includes(id)||id===except)continue;
      try{if(JSON.parse(readFileSync(join(folder,file),'utf8')).enabled)void this.run('send',{id,message:this.signedMessage(botId,text)}).catch(()=>{});}catch{continue;}
    }
  }
}
