[复盘] 08:30 盘前核对（工作日）

先加载 premarket-check 技能，严格按它的步骤执行本次盘前核对。

第一步（必须先做）：调用 hub_get_review_data() 判断今天是不是交易日。
- 若 ok:false：报告 error.code 与数据时间，说明本次没有拿到数据，结束。
- 若 trading_day:false：只回复"今日休市，不复盘"并结束，不要保存、不要建卡。
- 若 trading_day:true：继续，并记下 date、data_cutoff 与 missing。

然后：
1. 读昨晚的 last_review 与 cards.open，对每张 status:"active" 的卡用 hub_get_card(id) 读全文（条件、放弃线、止损、退出规则、state、history）。
2. 查隔夜公告与外部市场：公告/解禁用 cn-data 工具（必要时读原文，只读标题就注明"未读原文"）；宏观与外部市场用公开检索，标来源、时间与不确定性。
3. 对每张 active 卡给出"保留 / 降级 / 移除"意见与依据。移除 = 向用户建议取消，写"请在「复盘」页操作"，不得自行取消已确认的卡；自己提议且仍是 proposed 的卡才可以用 hub_cancel_card 取消。
4. 09:00–09:25 竞价数据没有稳定来源，一律写"待确认"，不编竞价强弱。
5. 结束前必须调用 hub_save_review 保存 kind:"premarket" 的复盘（date、env、mainline、themes、events、yesterday_feedback、candidates≤5、pending、data_cutoff、sources、checklist、body_markdown）。

盘前只能收紧风险边界：不放宽放弃条件、不新增未经复盘的票、不把放弃条件改成买入理由。

本次会话标题以 [复盘] 开头，例如"[复盘] 2026-11-05 盘前核对"。

每个数字都要带数据时间；缺数据写"待确认"。不下单、不连接券商、不调用 confirm/tighten_stop/set_state/信号 action/判断回写/触发队列工具。不要用 sleep 或轮询等待数据。
