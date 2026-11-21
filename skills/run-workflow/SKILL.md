---
name: run-workflow
description: 编排多标的、公告或证据批次的并行研究，为每项保留编号、来源和失败状态，再合成为一份可复核的结果。
---

# 多份公告怎样分头读、合起来核

在当前 Bot 确实获准使用 `workflow`、任务需要分发给多个研究者时启用。输入先整理成有限数组，每项包含唯一标识、公告日期、原文位置和要取的字段。单次委派用 `subagent`；单纯计算留给本地计算工具。

运行器接收独立的 `meta`、`script`、`args`，可选 `run_in_background`。元数据传简短的 kebab-case 名称与描述，不能把模块导出放进脚本体。脚本用 JavaScript，顶层可 await 和 return，返回可序列化对象。脚本本身没有文件、网络、定时器或 Node API；在子任务中按授权取证。子任务需要背景、单位、取数口径和原件位置，不能假设能看到父对话。

例如为三份设备交付公告提取已确认台数，把以下内容用作脚本体，参数结构为 `{items: [{id, url}]}`，元数据可取 `{name: "delivery-evidence", description: "核对交付台数"}`。

```js
phase('核对公告')
const reviewed = await parallel(args.items.map(item => () =>
  agent(`仅据这份公告提取已确认交付台数和原文位置。未披露时标明。\n${item.url}`,
    { label: item.id, schema: {
      type: 'object', properties: {
        disclosed: { type: 'boolean' }, evidence: { type: 'string' }
      }, required: ['disclosed', 'evidence']
    } })
))
return args.items.map((item, index) => ({ id: item.id, result: reviewed[index] }))
```

只有下一步必须看到全体结果时才设同步点。多阶段逐项处理用 `pipeline(items, ...stages)`，后续阶段接收上一步结果、原始项与序号。`null` 单列为未获得结果，不能据此写“未披露”。所有槽位失败时报告失败；若参数、权限或脚本有错误，保留错误并改正原因。不要传未支持的 `agentType`。可用 `phase` 和 `log` 记录进度，压缩最终表，避免超过输出限制。后台任务保留 job id，用 `job_list` 查状态、`job_output` 取结果，用户取消时才停止相应任务。
