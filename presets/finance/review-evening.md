[复盘] 20:00 每日复盘（工作日）

先加载 daily-review 技能，严格按它的步骤执行本次复盘。

第一步（必须先做）：调用 hub_get_review_data() 判断今天是不是交易日。
- 若 ok:false：报告 error.code 与数据时间，说明本次没有拿到数据，结束。
- 若 trading_day:false：只回复"今日休市，不复盘"并结束，不要写复盘、不要建作战卡、不要保存。
- 若 trading_day:true：继续，并记下 date、next_trading_day、data_cutoff 与 missing。

然后按六步推进：定环境 → 找主线 → 拆涨停结构 → 看个股质量 → 对照昨日观察池 → 生成次日观察清单（≤5）。
- 龙虎榜用 cn-data 的龙虎榜工具，取不到写"待确认"。
- 解禁/业绩披露/公告用工具查；宏观政策用公开检索并标注来源与不确定性。
- 用 subagent-roles 的角色并行取数（行情环境、题材涨停、事件公告、个股质量），派完结束本轮等通知，不要用 sleep 或轮询。
- 取数完成后由"复核员"按设计文档 07 节检查表逐项核对（数据日期/口径/来源、待确认、事件日历、预案写明触发与放弃）；不通过就改。

每只候选（最多 5 只）都必须调用 hub_propose_card 写作战卡：
- 条件只用 Cond 白名单（regime/index_pct/sector_change/sector_rank/price_cross/price_in_range/pct_change/open_pct/volume_ratio），每类 ≤6 条；
- 写明确认条件、放弃条件、止损（低于入场参考价、距离 ≤30%）、退出规则（≤3 条）；
- tags 至少写 streak、theme、env；
- 仓位只用 hub 返回卡片里的 sizing，不自己编百分比或金额；sizing 为 null 时如实写原因。

环境标签以 hub 的规则标签为底；如果你综合判断改成另一档，必须写 differs_from_rule:true 和理由（differs_note）。

结束前必须调用 hub_save_review 保存 kind:"evening" 的复盘（date、env、mainline、themes、ladder_note、lhb_note、events、yesterday_feedback、candidates≤5、pending、data_cutoff、sources、checklist、body_markdown）。保存失败就报告错误码，不要谎称已保存。

本次会话标题以 [复盘] 开头，例如"[复盘] 2026-11-04 晚间复盘"。

每个数字都要带数据时间；缺数据写"待确认"，不推测补齐。不下单、不连接券商、不调用 confirm/tighten_stop/set_state/信号 action/判断回写/触发队列工具。
