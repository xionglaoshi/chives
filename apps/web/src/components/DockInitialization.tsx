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
  ['briefing','创建每日投研简报任务'],
] as const;

export type InitializationStep = typeof steps[number][0];
type Status = Record<InitializationStep,boolean>;

export function useInitialization() {
  const [status,setStatus]=useState<Status|null>(null);
  useEffect(()=>{
    let active=true, timer:number;
    const refresh=async()=>{
      try {
        const next=await desk<Status>('initialization');
        if(active)setStatus(next);
      } catch { /* The next poll can recover once the service is available. */ }
      finally {if(active)timer=window.setTimeout(refresh,10000);}
    };
    void refresh();
    return ()=>{active=false;window.clearTimeout(timer);};
  },[]);
  return status ? steps.filter(([id])=>!status[id]) : [];
}

export const initializationPrompts = {
  watch: '请帮我创建盯盘任务。先问我希望盯盘哪些股票，可以输入名称或代码。如有同名或代码不清，先核实，再确认任务必要的触发条件。等待我的明确答复后再按给出的股票和条件创建，并告诉我已启用的规则。',
  briefing: '请为我准备「每日投研简报」，每周一至周五北京时间 09:00 执行（cron 为 0 9 * * 1-5）。先说明简报四部分并问我还想增加什么。我追加事项或明确回复「没有」后，再创建定时任务并告知执行时间、内容和投递位置。任何未回复或无关回复均保持等待。简报先按需读取用户属性、关注、持仓和上一交易日行情，再读机会榜单、A股热点资讯、全球股市热点资讯。依次汇报：上一交易日持仓与关注表现；机会榜单精选10只股票及具体理由；A股10大新闻；全球市场10大新闻。新闻仅给标题和可用原文链接。加入我确认的附加事项，缺项时说明，不编造。',
} as const;
