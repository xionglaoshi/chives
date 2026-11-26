import {useEffect,useState} from 'react';
import {desk} from './deskApi';

const steps = [
  ['model','添加模型'],
  ['portrait','完成用户画像评测问卷'],
  ['profile','填写用户基本信息'],
  ['holdings','添加持仓股票'],
  ['watchlist','添加关注股票'],
  ['weixin','连接微信'],
  ['watch','创建盯盘任务'],
  ['briefing','创建盘前简报任务'],
] as const;

export type InitializationStep = typeof steps[number][0];
type Status = Record<InitializationStep,boolean> & {briefingPending:boolean};

export function useInitialization() {
  const [status,setStatus]=useState<Status|null>(null);
  const preview=new URLSearchParams(window.location.search).get('preview')==='initialization';
  useEffect(()=>{
    let active=true, timer:number;
    const refresh=async()=>{
      try {
        const next=await desk<Status>(preview?'initialization?preview=1':'initialization');
        if(active)setStatus(next);
      } catch { /* The next poll can recover once the service is available. */ }
      finally {if(active)timer=window.setTimeout(refresh,10000);}
    };
    void refresh();
    return ()=>{active=false;window.clearTimeout(timer);};
  },[preview]);
  return {
    steps:status?steps.filter(([id])=>!status[id]):[],
    briefingPending:status?.briefingPending??false,
    setBriefingPending(pending:boolean) {
      setStatus(current=>current?{...current,briefingPending:pending}:current);
    },
  };
}

export const initializationPrompts = {
  watch: '请帮我创建盯盘任务。先问我希望盯盘哪些股票，可以输入名称或代码。如有同名或代码不清，先核实，再确认任务必要的触发条件。等待我的明确答复后再按给出的股票和条件创建，并告诉我已启用的规则。',
  briefing: '请说明盘前简报如何结合持仓、关注、近期讨论、机会榜单、近三天新闻和资金流找机会。默认在 A 股交易日 08:30 运行。追加事项通过现有简报确认卡保存。',
} as const;
