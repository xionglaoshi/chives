# Chives 维护约定

本机的正式安装目录 `~/.chives` 是维护 Chives 和向 GitHub 同步的唯一 Git 工作区。直接在这里修改程序、核对改动并提交到 [xionglaoshi/chives](https://github.com/xionglaoshi/chives) 的 `main` 分支。推送后核对远端提交。

每次修改先查项目工作区 `~/.agents/workspace/股票AGENT/` 中的计划表和对应验收记录，完成后更新该表。技术方案、原型和内部验收材料保存在项目工作区。运行回归用例使用临时数据，真实会话、持仓、画像、密钥、运行日志及本机备份只在本机保存。

技能、工具和提示使用 Chives 的产品命名，外部组件按其实际名称与许可证分发。版本对应的组件说明见[随附组件许可](THIRD_PARTY_NOTICES.md)。
