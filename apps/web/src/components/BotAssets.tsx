import { useEffect, useState } from 'react';
import { appPath } from '../appPath';

const categories={skills:'技能',mcp:'MCP 服务',tools:'工具',databases:'本地数据库'} as const;
type Category=keyof typeof categories;
type Resources=Record<Category,string[]>;
type Profile=Resources & {skillMode?:'all'|'selected';instructions:string;preset:string};
const toolNames:Record<string,string>={read_skill:'读取技能',save_report:'保存研究报告',recall_memory:'读取 Bot 记忆',remember:'保存 Bot 记忆',inspect_database:'查询本地数据库','bot-library':'本 Bot 资料库','market-monitor':'市场监控库','strategy-results':'策略结果库'};

export function BotAssets({id,onSave}:{id:string;onSave:()=>void}){
  const [labels,setLabels]=useState<Record<string,string>>({});
  const [profile,setProfile]=useState<Profile|null>(null);
  const [options,setOptions]=useState<Resources|null>(null);
  const [notice,setNotice]=useState('');
  const [busy,setBusy]=useState(false);
  const url=appPath('/api/bots/')+encodeURIComponent(id)+'/assets';
  useEffect(()=>{
    const abort=new AbortController();
    fetch(url,{signal:abort.signal}).then(async r=>{
      if(!r.ok)throw Error('读取 Bot 配置失败');
      const value=await r.json();setProfile(value.profile);setOptions(value.options);setLabels(value.options.toolNames??{});
    }).catch(e=>{if(!abort.signal.aborted)setNotice(String(e))});
    return ()=>abort.abort();
  },[url]);
  if(!profile || !options)return <p>{notice}</p>;
  async function save(){
    setBusy(true);
    try{
      const r=await fetch(url,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(profile)});
      if(!r.ok)throw Error((await r.json()).error?.message || '保存失败');
      setNotice('已保存，下次任务使用新配置');onSave();
    }catch(e){setNotice(String(e))}finally{setBusy(false)}
  }
  return <details className="expert-assets"><summary>技能、工具与 Bot 指令</summary>
    {(Object.keys(categories) as Category[]).map(key=><fieldset key={key}><legend>{categories[key]}</legend>
      {key==='skills' && <label><input type="checkbox" role="switch" checked={profile.skillMode==='all'}
        onChange={e=>setProfile({...profile,skillMode:e.target.checked?'all':'selected'})}/>
        使用全部技能，自动包含以后新增的技能</label>}
      {options[key].map(value=><label key={value}><input type="checkbox" role="switch" disabled={key==='skills' && profile.skillMode==='all'} checked={(key==='skills' && profile.skillMode==='all') || profile[key].includes(value)}
        onChange={e=>setProfile({...profile,[key]:e.target.checked?[...profile[key],value]:profile[key].filter(x=>x!==value)})}/>
        {labels[value]??toolNames[value]??value}</label>)}</fieldset>)}
    <label>Bot 指令（AGENTS.md）<textarea value={profile.instructions} maxLength={16000} onChange={e=>setProfile({...profile,instructions:e.target.value})}/></label>
    <label>默认任务提示词<textarea value={profile.preset} maxLength={16000} placeholder="例如：引用关键数字时列出报告期和公告页码" onChange={e=>setProfile({...profile,preset:e.target.value})}/></label>
    <button type="button" disabled={busy} onClick={save}>保存 Bot 配置</button> <span role="status">{notice}</span>
  </details>
}
