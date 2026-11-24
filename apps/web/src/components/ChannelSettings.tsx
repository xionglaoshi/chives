import {useEffect,useState} from 'react';
import {desk} from './deskApi';
import weixinLogo from '../brand/channels/weixin.png';
import wecomLogo from '../brand/channels/wecom.png';
import feishuLogo from '../brand/channels/feishu.png';
import slackLogo from '../brand/channels/slack.png';
import discordLogo from '../brand/channels/discord.png';
import telegramLogo from '../brand/channels/telegram.png';

const platforms: Record<string, {name:string; logo:string}> = {
  weixin: {name:'微信', logo:weixinLogo},
  wecom: {name:'企业微信', logo:wecomLogo},
  feishu: {name:'飞书', logo:feishuLogo},
  slack: {name:'Slack', logo:slackLogo},
  discord: {name:'Discord', logo:discordLogo},
  telegram: {name:'Telegram', logo:telegramLogo},
};
interface Channel{id:string;configured:boolean;verified:boolean;enabled:boolean;account:string;target:string;qr:boolean;last:string;pair:{state?:string;image?:string}}
export function ChannelSettings(){
 const [items,set]=useState<Channel[]>([]),[selected,select]=useState(''),[mode,show]=useState(''),[form,edit]=useState({account:'',key:'',target:'',enabled:false}),[msg,notice]=useState(''),[busy,wait]=useState(false);
 async function load(){set(await desk<Channel[]>('channels'));}
 useEffect(()=>{let alive=true;const poll=()=>desk<Channel[]>('channels').then(v=>{if(alive)set(v);}).catch(e=>{if(alive)notice(e.message);});void poll();const timer=mode==='qr'?setInterval(()=>void poll(),2300):undefined;return()=>{alive=false;clearInterval(timer);};},[mode]);
 async function action(op:string,id:string,body:object={}){wait(true);notice('');try{await desk('channels','POST',{id,action:op,...body});await load();if(op==='save'){show('');select('');notice('已验证并保存频道配置');}if(op==='delete')notice('频道已断开');}catch(e){notice(String(e));}finally{wait(false);}}
 const curr=items.find(x=>x.id===selected);
 return <><div className="desk-list">{items.map(c=>{const {name,logo}=platforms[c.id]!;return <div className="desk-integration" key={c.id}><img className="channel-logo" src={logo} alt="" width={38} height={38}/><div><strong>{name}</strong><p>{c.verified?(c.enabled?'已启用提醒':'已授权 · 尚未启用提醒'):'未连接'}{c.last?' · '+c.last:''}</p></div>
 <div className="desk-end">{c.qr&&<button data-init-target={c.id==='weixin'?'weixin':undefined} disabled={busy} onClick={()=>{select(c.id);show('qr');void action('pair',c.id);}}>二维码接入</button>}<button onClick={()=>{select(c.id);show('manual');edit({account:c.account,key:'',target:c.target,enabled:c.enabled});notice('');}}>手动设置</button>{c.configured&&<button disabled={busy} onClick={()=>void action('delete',c.id)}>断开</button>}</div></div>;})}</div>
 {curr&&mode&&<div className="desk-modal-layer"><section role="dialog" aria-modal="true" aria-label={platforms[selected]!.name+'接入'} className="desk-modal"><button className="desk-close" aria-label="关闭" onClick={()=>{show('');notice('');}}>×</button><h2>{platforms[selected]!.name} · {mode==='qr'?'扫码授权':'手动设置'}</h2>
 {mode==='qr'?<><p>请使用对应平台扫码确认。授权后可设置接收会话并开启提醒。</p>{curr.pair.state==='waiting'&&curr.pair.image?<img className="desk-qr" alt="平台授权二维码" src={curr.pair.image}/>:<p role="status">{curr.pair.state==='done'?'授权完成，请进入手动设置确认接收会话。':curr.pair.state==='failed'?'平台未返回有效授权或二维码已过期。':'正在向平台申请二维码…'}</p>}</>:<form onSubmit={e=>{e.preventDefault();void action('save',selected,form);}}>
 <p>{selected==='weixin'?'首次接入先扫码。接收会话使用已绑定的微信用户 ID。':selected==='slack'||selected==='discord'?'填写应用机器人的 Token 与接收频道 ID。应用需获准向该频道发送消息。':'凭证保存在本机。设置接收会话后，可开启 Chives 消息投递。'}</p>
 {['weixin','wecom','feishu'].includes(selected)&&<label>{selected==='feishu'?'App ID':'Bot ID'}<input value={form.account} onChange={e=>edit({...form,account:e.target.value})}/></label>}
 <label>{['wecom','feishu'].includes(selected)?'应用 Secret':'Bot Token'}<input type="password" autoComplete="new-password" value={form.key} placeholder={curr.configured?'留空沿用已保存的凭证':''} onChange={e=>edit({...form,key:e.target.value})}/></label>
 <label>接收会话 ID<input value={form.target} onChange={e=>edit({...form,target:e.target.value})}/></label><label><input type="checkbox" role="switch" checked={form.enabled} onChange={e=>edit({...form,enabled:e.target.checked})}/> 向此会话投递主动提醒</label>
 <button className="desk-primary" disabled={busy}>验证并保存</button></form>}<p role="status">{msg}</p></section></div>}
 {!mode&&<p role="status">{msg||(!items.length?'正在读取频道…':'')}</p>}</>;
}
