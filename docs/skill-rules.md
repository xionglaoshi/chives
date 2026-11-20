# Chives 技能规则

每个技能占据 `skills/<技能名>/` 的一个直接子目录。名称使用小写英文字母、数字和连字符，目录内放置 `SKILL.md`，脚本、模板和参考文件随该技能保存。技能名称和简介写在 Markdown 文件的 frontmatter 中。

持有「读取技能」权限的 Bot 使用 `read_skill()` 查看自己的清单，传入名称可读完整正文。勾选「使用全部技能」时自动包含新增技能，也可单独授权。技能说明中涉及其他工具、MCP 或数据库时，实际操作仍由 Bot 配置决定。

见[技能发现](../apps/server/src/bots/skill-links.ts)、[读取工具](../scripts/bot-assets.py)和[Bot 设置](专家内核与配置.md)。
