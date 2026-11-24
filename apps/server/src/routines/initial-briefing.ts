export const initialBriefingTitle = '每日投研简报';

export const initialBriefingSchedule = {
  cron: '0 9 * * 1-5', tz: 'Asia/Shanghai',
} as const;

export function initialBriefingPrompt(additions: string) {
  return `生成每日投研简报，投递到 Chives Bot 消息。
先按需读取本机用户属性、关注和持仓，使用市场日历定位上一交易日，读取该交易日的证券行情；再读取机会榜单、A股热点资讯和全球股市热点资讯。

## 上一交易日持仓与关注表现
注明交易日期，分开列出持仓与关注股票的涨跌和关键异动。有可靠数据时列出持仓贡献。
## 机会榜单精选
从已发布榜单按证券去重，结合用户属性、持仓和关注选出最多10只股票，逐只给出来源榜单及具体关注理由。
## A股最值得关注的新闻
最多10条，仅列标题，来源提供原文链接时将链接加在标题上。
## 全球市场最值得关注的新闻
最多10条，仅列标题及可用的原文链接。
缺少资料时注明缺项，继续完成有依据的部分。
${additions ? '\n## 用户追加事项\n'+additions : ''}`;
}
