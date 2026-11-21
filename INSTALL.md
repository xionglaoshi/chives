# 老韭菜安装说明

工作台和 API 分别监听本机的 8888 和 8880 端口。你可以使用[三端安装向导](README.md#快速安装)，也可以在 **macOS 登录会话中从 GitHub 源码安装**。以下步骤以 macOS 源码安装为主。

## 1. 准备工具

准备 Git、Node.js 26（含 npm 和 npx）、pnpm 10.33、uv。安装脚本会准备 Python 3.12 环境，并下载 Chromium 和 dsh。要从有文字层的 PDF 公告提取文本，另准备 Poppler 的 `pdftotext`。

已有 Homebrew 的 Mac 可用 `brew install uv poppler` 安装 uv 和 Poppler。开始前在终端核对工具版本。

```sh
git --version
node --version
pnpm --version
uv --version
pdftotext -v
```

启动服务会使用固定的搜索路径。请确认 `node`、`npm`、`npx` 和 `pnpm` 能从 `/opt/homebrew/bin`、`~/.local/bin` 或 `~/.agents/bin` 找到。只在当前终端内生效的版本管理器配置，launchd 启动时可能读不到。

## 2. 下载、安装和启动

首次安装时选择尚未使用的目录。以下示例安装到 `~/.chives`。已有 Chives 的用户，请先看下方「更新与备份」。

```sh
git clone https://github.com/xionglaoshi/chives.git "$HOME/.chives"
cd "$HOME/.chives"
bash scripts/install-chives.sh
./start start
```

如果你可以直接访问依赖下载站点，而且本机没有运行安装脚本默认使用的代理，将第三行换成 `NO_PROXY='*' no_proxy='*' bash scripts/install-chives.sh`。如果需要代理，在运行安装脚本前把 `HTTPS_PROXY` 设为本机实际可用的代理地址。安装过程需要下载 Python 和 Node 依赖、Chromium 及 dsh。

看到「老韭菜已启动」后，打开[本机工作台](http://127.0.0.1:8888/)。也可以用下面两条命令核对服务。

```sh
./start status
curl --noproxy '*' -fsS http://127.0.0.1:8880/api/health
```

## 3. 配置模型，做一次研究

在[模型设置](http://127.0.0.1:8888/#/settings?tab=models)添加自己的模型连接。使用 API 时，按供应商提供的地址、协议、模型 ID 和密钥填写，验证连接后设为默认模型。各 Bot 默认沿用全局连接，也可以在档案里单独指定。 [设置中心](docs/设置中心.md)

打开[投资专家](http://127.0.0.1:8888/#/bot/expert)，选一家熟悉的公司，试问：

> 请核对这家公司最近一期已披露的合并报表。列出报告期、归母净利润和经营活动现金流量净额，给出公告链接、页码和数据单位。找不到的项目请注明。

先确认能发出问题并收到完整回答，再点进公告核对数字。如果能聊天但查不到数据，分别检查 Bot 的工具授权和数据源连接。 [投研工具与排查入口](docs/投研工具与验收.md)

## 日常启停

在仓库根目录运行：

| 命令 | 用途 |
| --- | --- |
| `./start start` | 启动工作台和后台服务 |
| `./start status` | 查看服务状态 |
| `./start restart` | 重启服务 |
| `./start stop` | 停止服务 |

启动超时时先看 `runtime/workbench.log`，并检查 8888 和 8880 端口是否已被其他程序占用。曾经安装过 Chives 的 Mac 如果还留有 launchd 配置，检查 `~/Library/LaunchAgents/local.chives.workbench.plist` 是否指向当前目录。

## 更新与备份

通过 Git 安装的用户，更新前可在「设置 → 备份及导入」下载个人配置，另行导出研究记录。如需完整恢复，在停机后备份 `data/`，妥善保管其中的凭据。Chives 的对话、持仓和个人资料属于本机数据。

确认目前位于 `main` 分支且工作区干净，再更新源码和依赖。若 `git status` 显示你自己的改动，先保存并核对这些改动。

```sh
cd "$HOME/.chives"
git status --short --branch
./start stop
git pull --ff-only origin main
bash scripts/install-chives.sh
./start start
```

重新安装依赖时沿用首次安装的网络设置。更新后检查模型连接，并读回一条旧会话。恢复到新机器时，先准备对应版本的程序，再按需恢复个人数据并重新验证模型与频道授权。 [备份与导入说明](docs/设置中心.md)

## 三端分发安装

[macOS 向导](deploy/installer/macos.sh)、[Linux 向导](deploy/installer/linux.sh)和 [Windows 向导](deploy/installer/windows.ps1)均需要有效安装码及可用的分发服务。向导会下载运行环境和 Chives，安装成功后直接启动。[三端安装命令](README.md#快速安装)

macOS 和 Linux 默认从 `~/.chives-install` 运行，Windows 默认目录为 `%LOCALAPPDATA%\Chives`。安装及运行日志分别在该目录的 `logs/install.log` 和 `logs/supervisor.log`。需要重新启动分发版时，可再次运行对应向导，它会检测现有安装并复用匹配版本的构建。上文的 `./start` 命令适用于 macOS 源码安装。Linux、Windows 实机验证待补齐。 [分发维护说明](deploy/installer/README.md)
