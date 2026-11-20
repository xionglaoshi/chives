# 用 dsh 定时任务做每日复盘与盘前核对

本页只写配方，**不创建任何任务**。任务属于用户自己的 dsh 配置，创建前必须把任务标题、时间、提示词全文给用户看，并得到**明确同意**；「复盘」页的"开启复盘定时任务"按钮只往对话里填指令，不直接创建。

两个任务的工作日节奏：**20:00 晚间复盘**、**08:30 盘前核对**，时区都是 `Asia/Shanghai`。

## 1. 先确认工具与前提

- `standard`、`cordis`、`ptc` 预设提供 `schedule_create`、`schedule_list`、`schedule_view`、`schedule_edit`；`minimal` 不提供。委派子会话即使能看到工具，调用也会被拒绝。[`docs/watch-schedule.md:7-7` (dsh-finance)]
- 四个工具管理整台 Host，创建或修改前需要用户明确授权。[`docs/watch-schedule.md:9-9` (dsh-finance)]
- `schedule_create` 的 `rrule` 必填且只接受 RRULE，不接受 cron；`prompt` 是每次触发投递给智能体的完整指令。[`docs/watch-schedule.md:13-13` (dsh-finance)]
- ⚠️ **prompt 必须写全文**：从 `presets/finance/review-evening.md` / `presets/finance/review-premarket.md` 复制整段文本，不要只写文件路径——定时投递只发 prompt 字符串，不会替你读文件。

## 2. 任务一：工作日 20:00 晚间复盘

```text
schedule_create(
  title="[复盘] 工作日 20:00 晚间复盘",
  rrule="DTSTART;TZID=Asia/Shanghai:20261104T200000\nRRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
  target="new",
  prompt=<presets/finance/review-evening.md 的全文>
)
```

- `title` ≤120 字符，统一以 `[复盘]` 开头，便于在 Automation 列表里识别。
- `rrule` 两行：`DTSTART;TZID=Asia/Shanghai` + `RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR`；`DTSTART` 只是锚点，可以早于创建时间，投递从创建后的第一个匹配时刻开始。[`docs/watch-schedule.md:15-22` (dsh-finance)]
- `target:"new"`：每次触发都新建一个会话，避免长期会话上下文膨胀；会话标题由提示词要求以 `[复盘]` 开头。
- `prompt` 全文见 `presets/finance/review-evening.md`，关键约束：先加载 `daily-review` 技能 → 第一步 `hub_get_review_data` 判断交易日 → `trading_day:false` 只回复"今日休市，不复盘"并结束 → 六步复盘 → 每只候选 `hub_propose_card` → 结束前必须 `hub_save_review`（`kind:"evening"`）→ 不用 sleep 或轮询。

## 3. 任务二：工作日 08:30 盘前核对

```text
schedule_create(
  title="[复盘] 工作日 08:30 盘前核对",
  rrule="DTSTART;TZID=Asia/Shanghai:20261104T083000\nRRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
  target="new",
  prompt=<presets/finance/review-premarket.md 的全文>
)
```

- `prompt` 全文见 `presets/finance/review-premarket.md`，关键约束：先加载 `premarket-check` 技能 → 第一步 `hub_get_review_data` 判断交易日 → 休市直接结束 → 逐张 `active` 卡给"保留/降级/移除"意见（移除只建议用户取消，不自行取消已确认卡）→ 09:00–09:25 竞价写"待确认" → 结束前必须 `hub_save_review`（`kind:"premarket"`）。
- 08:30 早于开盘，任务只做核对与保存，不盯盘、不下单。

## 4. 为什么第一步必须判断交易日

dsh 的日程**没有 A 股交易日历**：RRULE 只按星期几匹配，法定节假日、调休照常触发；这一点在 `docs/watch-schedule.md` 里标为未验证，不能假设会自动跳过。[`docs/watch-schedule.md:71-71` (dsh-finance)] [`docs/watch-schedule.md:77-77` (dsh-finance)]

所以两个提示词都把"交易日判断"固定为第一步：`hub_get_review_data` 返回 `trading_day:false` 时，只回复"今日休市，不复盘"并结束，不写复盘、不建卡、不保存。这样节假日最多多跑一次空任务，不会产生假复盘。

## 5. 运行前提与限制

- **Host 不在线就不触发**；Host 关闭期间不投递，重启后只补**最近一次**错过的 occurrence。[`docs/watch-schedule.md:68-68` (dsh-finance)]
- 时区必须显式写 IANA 名称（`Asia/Shanghai`）；本地日历规则遇到不存在的墙上时间会跳过。[`docs/watch-schedule.md:69-69` (dsh-finance)]
- 投递只证明消息进了目标会话 inbox，**不代表模型跑完，也不保存复盘正文**；结构化结果在 hub 里，由 `hub_save_review` 写入，「复盘」页读 hub，不翻会话。[`docs/watch-schedule.md:52-52` (dsh-finance)]
- 每次触发都消耗一次模型调用；20:00 那次通常较长（多工具、多子智能体），与盯盘分析的日额度分开看。

## 6. 暂停、恢复、删除

- 暂停：`schedule_edit(id, action="update", active=false)`。
- 恢复：同一接口传 `active=true`；若旧规则已耗尽，要同时给新的 `rrule`。
- 删除：`schedule_edit(id, action="delete")`，连同投递记录一起删掉；已经排进会话 inbox 的消息不会撤回。
- 以上语义见 [`docs/watch-schedule.md:58-62` (dsh-finance)]；也可以在 Automation tasks 页面操作。[`docs/watch-schedule.md:64-64` (dsh-finance)]

## 7. 创建前给用户看的清单

创建任何一条前，先在对话里展示并在得到明确同意后再调用 `schedule_create`：

1. 任务标题与是否以 `[复盘]` 开头；
2. `rrule` 两行原文、时区、星期几、触发时间；
3. `target:"new"`（每次新会话）；
4. `prompt` 全文（不是路径）；
5. 说明"没有交易日历，节假日会触发但第一步会直接结束"；
6. 说明"Host 不在线不触发，重启只补最近一次"；
7. 暂停/恢复/删除的方法。

**本页不创建任何任务。**
