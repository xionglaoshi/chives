# Chives 维护约定

本机的正式安装目录 `~/.chives` 是维护 Chives 和向 GitHub 同步的唯一 Git 工作区。直接在这里修改程序、核对改动并提交到 [xionglaoshi/chives](https://github.com/xionglaoshi/chives) 的 `main` 分支。推送后核对远端提交。

每次修改先读私有 WIKI 的 `personal/chives/老韭菜功能需求开发计划表.md`，并在对应页面更新技术方案、验收、经验和历史决策。本机股票AGENT工作区用于测试、备份、临时运算和研究样本。正式程序、生产数据库、Bot 档案、模型配置和专用运行依赖在正式安装中维护。测试使用隔离数据。

技能、工具和提示使用 Chives 的产品命名，外部组件按其实际名称与许可证分发。版本对应的组件说明见[随附组件许可](skills/NOTICE.md)。
