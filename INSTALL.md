# 老韭菜安装说明

工作台和 API 分别监听本机的 8888 和 8880 端口。你可以使用[GitHub 安装向导](README.md#快速安装)，也可以在 **macOS 登录会话中从 GitHub 源码安装**。安装后，在任意目录的新终端运行 `chives` 即可启动服务并打开默认浏览器，运行 `chives stop` 即可关闭服务。以下依赖准备步骤适用于 macOS 源码安装。

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
```

如果你可以直接访问依赖下载站点，而且本机没有运行安装脚本默认使用的代理，将第三行换成 `NO_PROXY='*' no_proxy='*' bash scripts/install-chives.sh`。如果需要代理，在运行安装脚本前把 `HTTPS_PROXY` 设为本机实际可用的代理地址。安装过程需要下载 Python 和 Node 依赖、Chromium 及 dsh。

安装完成后新开终端，输入 `chives`。默认浏览器会打开[本机工作台](http://127.0.0.1:8888/)。macOS 源码安装还可在仓库目录用下面两条命令核对服务。

```sh
./start status
curl --noproxy '*' -fsS http://127.0.0.1:8880/api/health
```

## 3. 配置模型，做一次研究

在[模型设置](http://127.0.0.1:8888/#/settings?tab=models)添加自己的模型连接。使用 API 时，按供应商提供的地址、协议、模型 ID 和密钥填写，验证连接后设为默认模型。各 Bot 默认沿用全局连接，也可以在档案里单独指定。 [设置中心](docs/设置中心.md)

打开[投资专家](http://127.0.0.1:8888/#/bot/expert)，选一家熟悉的公司，试问：

> 请核对这家公司最近一期已披露的合并报表。列出报告期、归母净利润和经营活动现金流量净额，给出公告链接、页码和数据单位。找不到的项目请注明。

先确认能发出问题并收到完整回答，再点进公告核对数字。如果能聊天但查不到数据，分别检查 Bot 的工具授权和数据源连接。 [投研工具](docs/投研工具.md)

## 日常启停

macOS、Linux、Windows 都使用以下两个命令。安装会注册当前用户的命令目录，首次使用请重新打开终端。在 Windows Terminal 中请退出应用后重新打开。

| 命令 | 用途 |
| --- | --- |
| `chives` | 启动服务并在默认浏览器中打开工作台。服务已运行时直接打开页面 |
| `chives stop` | 停止当前安装的本地服务 |

macOS 和 Linux 的命令位于 `~/.local/bin/chives`，Windows 的命令位于分发安装目录的 `bin\chives.cmd`。升级旧分发版时重新运行对应的安装向导即可注册。已有 macOS 源码安装可在更新后于仓库根目录单独运行 `"$HOME/.agents/venvs/chives/bin/python" scripts/chives_cli.py source --register`。

macOS 源码安装启动超时时先看 `runtime/workbench.log`，并检查 8888 和 8880 端口是否已被其他程序占用。曾经安装过 Chives 的 Mac 如果还留有 launchd 配置，检查 `~/Library/LaunchAgents/local.chives.workbench.plist` 是否指向当前目录。

## 更新与备份

Chives 默认把数据库、Bot 工作区和用户画像保存在安装目录的 `data/` 下。本机使用 `~/.chives/data/`，直接启动服务和使用 `chives` 命令均采用这个目录。

旧版源码安装如果曾直接启动服务，数据可能位于安装目录中的第二层 `.chives/`。迁移前先停服并备份。若只有旧库，将旧目录的内容整体迁至 `data/`，包含 SQLite 数据库及同名的 WAL、SHM 文件。若 `data/` 已有业务文件，先核对重名文件和两处会话、画像、持仓及计划，保留当前有效记录，避免用旧库覆盖新库。确认启动后能读到原记录，再移除旧目录。

通过 Git 安装的用户，更新前可在「设置 → 备份及导入」下载个人配置，另行导出研究记录。如需完整恢复，在停机后备份 `data/`，妥善保管其中的凭据。Chives 的对话、持仓和个人资料属于本机数据。

确认目前位于 `main` 分支且工作区干净，再更新源码和依赖。若 `git status` 显示你自己的改动，先保存并核对这些改动。

```sh
cd "$HOME/.chives"
git status --short --branch
chives stop
git pull --ff-only origin main
bash scripts/install-chives.sh
```

更新后运行 `chives`。重新安装依赖时沿用首次安装的网络设置。更新后检查模型连接，并读回一条旧会话。恢复到新机器时，先准备对应版本的程序，再按需恢复个人数据并重新验证模型与频道授权。 [备份与导入说明](docs/设置中心.md)

## GitHub 快速安装

复制 [README 的一行命令](README.md#快速安装)。Bash 入口适用于 macOS、GNU/Linux 和 WSL2 的 x64、ARM64 系统；Windows 10/11 使用系统自带的 PowerShell、`curl.exe` 和 `tar.exe`，Windows 11 ARM 走 x64 兼容环境。Linux 建议使用 Playwright 支持的 Debian 或 Ubuntu 版本。 [Bash 入口](deploy/installer.sh) · [PowerShell 入口](deploy/installer.ps1)

| 安装内容 | 本机已有时 | 缺少时的来源 |
| --- | --- | --- |
| Chives 源码 | 同一份已构建的快照可以复用 | 本仓库 main 分支的源码归档 |
| CPython 3.12 | 检查架构、venv 和 ensurepip | Astral 维护的可迁移 CPython 构建，按平台校验 SHA-256 |
| Node.js 26、npm/npx | 检查 Node 架构与工具可执行性，可以单独补 npm | Node.js 官网分发或 npm 官方 registry |
| pnpm、DSH | 检查仓库指定版本以及全局或 Chives 私有工具 | npm 官方 registry；前端依赖按锁文件安装 |
| Python 项目依赖 | 安装在当前版本的独立虚拟环境，重跑同版本复用 | PyPI |
| Playwright、Chromium | 检查本机缓存或上个安装版本的浏览器能否由匹配版本的 Playwright 启动 | Playwright 的 Python 包来自 PyPI，Chromium 由 Playwright 官方下载器安装。Linux 缺少系统库时通过发行版包管理器补装，可能提示输入 sudo 密码 |

向导探测环境变量、系统代理和常见本机代理端口，选用能实际访问 GitHub 的代理，或使用直连。这个选择会传给后续安装工具。首次获取入口脚本发生在向导启动之前，需要时先为终端设置代理。终端显示阶段、勾选标记、文件传输速率及依赖工具输出。

新安装位于 `~/.chives`（Windows 为 `$HOME\.chives`）。程序快照与用户的 `data/` 分开存放。如果检测到现有 Git 源码检出，向导会提示按源码方式更新；如要独立试装，在运行命令前将 `CHIVES_INSTALL_HOME` 设为另一个绝对路径。启动时工作台及后台服务所用端口需要空闲。已有旧版分发目录时会沿用旧位置。

重新运行同一条命令即可取得最新源码。向导完成本机构建、启动服务并注册当前用户的命令后，新终端输入 `chives` 打开工作台，`chives stop` 关闭。安装日志在安装根目录的 `logs/install.log`，启动日志在 `logs/supervisor.log`。 [安装机制](deploy/installer/README.md)
