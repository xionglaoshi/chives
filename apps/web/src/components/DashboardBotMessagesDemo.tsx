import { useState } from 'react';
import type { NotificationDto } from '@chives/server/protocol';
import { DashboardBotMessages } from './DashboardBotMessages';

const senders = [
  {id: 'ceo', name: '总经理'},
  {id: 'market', name: '市场观察'},
  {id: 'research', name: '行业研究'},
  {id: 'analyst', name: '个股分析'},
];

const subjects = [
  '上证放量探低后回升，3500 点附近成交集中',
  '沪深成交额较昨日同期增加，午后交投升温',
  '半导体设备成交放大，板块内部强弱分化',
  '三家公司发布回购进展，实施比例已更新',
  '主要指数午后分化，科创方向相对活跃',
  '港股科技板块冲高回落，关注尾盘成交',
  '电网设备板块领涨，招标进度出现新披露',
  '已更新两家公司的业绩说明会要点',
  '指数反弹期间上涨家数增多，成交仍偏集中',
  '个股涨停榜更新，成交量靠前标的发生变化',
  '有色板块上涨，铜铝相关个股表现分化',
  '关注名单中一只股票触及设定价格',
  '开盘缺口已回补，指数回到早盘震荡区间',
  '美元指数回落，外围股指期货走势分化',
  '家电板块回暖，白电与小家电表现分化',
  '跟踪公司披露产能利用率变化和后续计划',
  '市场涨跌比改善，量能高于昨日同一时段',
  '高成交个股集中在电子和通信板块',
  '已整理汽车零部件行业月度公开数据',
  '一只关注股触发成交量提醒',
  '早盘指数低开，盘中波动加大',
  '恒生科技指数转涨，成交量尚未明显放大',
  '政策公告提及设备更新，已整理涉及行业',
  '已对照最新季报核查关注公司的现金流',
  '沪深开盘成交额较上日同期上升',
  '美股盘后主要指数涨跌互现',
  '储能板块新增订单及交付数据已整理',
  '一家跟踪公司更新股东减持进度',
  '盘前整理今日财报和市场事件日历',
  '昨日尾盘量价异动标的复盘已更新',
];

export function DashboardBotMessagesDemo() {
  const [expanded, setExpanded] = useState(false);
  const [notifications, setNotifications] = useState<NotificationDto[]>(() => {
    const now = Date.now();
    return subjects.map((title, index) => ({
      id: 'demo-' + index,
      botId: senders[index % senders.length]!.id,
      taskId: 'demo-' + index,
      title: '（模拟）' + title,
      body: '',
      level: 'info',
      createdAt: new Date(now - index * 60_000).toISOString(),
      readAt: index < 20 && index % 3 === 1 ? new Date(now).toISOString() : null,
    }));
  });
  return <DashboardBotMessages notifications={notifications} bots={senders} expanded={expanded}
    loading={false} error={false} onLoadMore={() => setExpanded(true)}
    onOpen={entry => {
      const readAt = new Date().toISOString();
      setNotifications(current => current.map(item => item.id === entry.id ? {...item, readAt} : item));
    }}/>;
}
