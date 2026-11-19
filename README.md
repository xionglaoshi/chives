# 老韭菜 · chives

chives 是老韭菜的 Agent 版，面向 A 股投研。第一阶段开发单用户本地 Agent，让个股研究员、基金持仓研究员和其他专家 Bot 结合可溯源的数据与可复算的分析工具，为同一个投资问题提供不同角度的判断。

当前仓库已初始化，Agent 功能待开发。轻量版提供本地服务和 Skill，独立维护于 [xiong-sisyphus](https://github.com/xionglaoshi/xiong-sisyphus)。

## 本机开发与同步

开发目录为 `/Users/xiong/.chives`。登录 macOS 后每分钟检查一次，自动提交当前分支新增、修改和删除的非忽略文件，并推送到 GitHub 私有仓库的同名分支。离线期间仍会生成本地提交，恢复连接后补推。遇到远端分叉时，Git 会拒绝覆盖已有提交，手动合并后自动同步继续。合并、变基和 detached HEAD 期间暂停。

个人档案放 `user/`，数据库和运行数据放 `data/`、`runtime/`，模型密钥放 `.env` 或 `secrets/`。同步规则见 [.gitignore](.gitignore)。

### 在熊翔的 Mac 上恢复同步

将 [同步脚本](ops/git-sync.sh) 复制到 `~/.agents/scripts/chives-autosync.sh`，将 [启动项](ops/local.chives.git-sync.plist) 复制到 `~/Library/LaunchAgents/`。确保 `~/.agents/state/chives-autosync/` 已创建，GitHub CLI 登录账号对私有仓库有写权限，本机 7897 代理可用。执行以下命令加载启动项或查看状态。

```sh
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/local.chives.git-sync.plist
launchctl print "gui/$(id -u)/local.chives.git-sync"
```

最近推送结果与错误可在 `~/.agents/state/chives-autosync/stderr.log` 查看。修改同步脚本后，将新副本复制到上述共享脚本路径。
