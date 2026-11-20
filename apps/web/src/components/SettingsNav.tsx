import {settingsEnglish,groupNames} from './deskLanguage';
import {useState} from 'react';
export const portraitDescription = '完成评测问卷、补充各类资料（例如从证券软件中导出的历史交易数据文件等）可以由Chives生成您的用户画像。用户画像会对Chives和各Bot在回答问题、执行任务时产生重大影响，请务必认真填写。也可以后续在Chives中，通过对话交流的方式完善您的用户画像。';
export const sections=[
 {label:'用户信息',items:[['account','用户资料','管理工作台中显示的身份和联系方式。'],['risk','风格评估',portraitDescription],['history','用户数据','回顾研究中的问题、证券和 Bot 记忆。']]},
 {label:'通用设置',items:[['messages','消息权限','决定 Bot 何时可以主动联系你。'],['channels','通讯频道','连接消息平台，将 Bot 提醒送到指定会话。'],['appearance','外观设置','调整工作台显示、时间格式和研究语言。']]},
 {label:'Agent 设置',items:[['chat','对话细节','选择任务进行时看到的细节，以及如何处理后续消息。'],['permissions','权限设置','为 Bot 资产设置统一上限，Bot 档案可以进一步收紧。'],['capabilities','能力管理','为 Bot 接入第三方 MCP，管理可用工具。'],['tasks','任务管理','查看各 Bot 的定时任务，调整自动执行安排。'],['kernels','内核设置','查看 dsh 版本，检查并选择是否升级。'],['models','模型设置','管理模型连接、测试可用性并选择默认模型。']]},
 {label:'系统维护',items:[['help','技术文档','常见操作和工作台运行说明。'],['backup','备份及导入','保存个人配置，在本机恢复已备份的数据。'],['updates','升级更新','比较私有仓库版本，按组件应用更新。']]}
];
const paths:Record<string,string>={
 capabilities:'M7 3v5m6-5v5M4 8h12v2a6 6 0 01-6 6v5m8-13h3m-1-2v4',tasks:'M5 5h14v16H5z M9 3h6v4H9z M8 12l1 1 2-3m2 2h3m-8 5h8',account:'M20 21a8 8 0 00-16 0 M16 7a4 4 0 11-8 0 4 4 0 018 0Z',risk:'M3 19V5m0 14h18M6 15l4-6 4 3 6-8',history:'M4 4v5h5 M4 9a8 8 0 118 11 M12 7v5l3 2',messages:'M5 16c2-2 2-5 2-7a5 5 0 0110 0c0 2 0 5 2 7H5ZM10 19a2 2 0 004 0',channels:'M9 15l6-6m-6 3-2 2a3 3 0 004 4l3-3m-4-6 3-3a3 3 0 014 4l-2 2',appearance:'M3 5h18v13H3zM8 21h8m-4-3v3',chat:'M3 4h18v13H9l-5 4v-4H3z',permissions:'M12 3l8 3v5c0 5-4 9-8 11-4-2-8-6-8-11V6z',kernels:'M6 6h12v12H6zM9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4',models:'M12 2l9 5v10l-9 5-9-5V7z M3 7l9 5 9-5m-9 5v10',help:'M3 4c3-1 6-1 9 1 3-2 6-2 9-1v15c-3-1-6-1-9 1-3-2-6-2-9-1z M12 5v15',backup:'M3 5h18v4H3zm2 4v11h14V9m-10 4h6',updates:'M20 4v5h-5m5 0a8 8 0 10-1 9'};
export function DeskIcon({id}:{id:string}){return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[id]}/></svg>;}
export function SettingsNav({page,go,english=false}:{page:string;english?:boolean;go:(id:string)=>void}){
 const [query,setQuery]=useState('');
 const groups=sections.map(g=>({...g,items:g.items.filter(x=>(g.label+groupNames[g.label]+x.join('')+settingsEnglish[x[0]!]?.join('')).toLowerCase().includes(query.trim().toLowerCase()))}));
 return <nav className="desk-nav" aria-label="设置分区"><a className="desk-back" href="#/bots">‹　{english?'Workbench':'返回工作台'}</a><h1>{english?'Settings':'设置'}</h1>
 <input aria-label="搜索设置" type="search" placeholder={english?'Search settings':'搜索设置'} value={query} onChange={e=>setQuery(e.target.value)}/>
 {groups.filter(g=>g.items.length).map(g=><section key={g.label}><button className="desk-group" onClick={()=>go(g.items[0]![0]!)}>{english?groupNames[g.label]:g.label}</button>{g.items.map(([id,title])=><button key={id} aria-current={page===id?'page':undefined} className="desk-nav-item" onClick={()=>go(id!)}><DeskIcon id={id!}/>{english?settingsEnglish[id!]![0]:title}</button>)}</section>)}
 {groups.every(g=>!g.items.length)&&<p>没有匹配的设置</p>}</nav>;
}
