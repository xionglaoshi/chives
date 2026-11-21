# 老韭菜 Chives 安装说明

## GitHub 快速安装

在终端复制与你的系统对应的一行。向导会从本仓库的 `main` 分支下载源码，在你的电脑上构建工作台。默认安装在用户主目录下的 `.chives`，无需安装码。

**Linux、macOS、WSL2**

```bash
curl -fsSL https://raw.githubusercontent.com/xionglaoshi/chives/main/deploy/installer.sh | bash
```

**Windows · PowerShell**

```powershell
iex (irm https://raw.githubusercontent.com/xionglaoshi/chives/main/deploy/installer.ps1)
```

macOS 和 GNU/Linux 支持 x64、ARM64。WSL2 请在 Linux 终端运行第一条命令；原生 Windows 10/11 请在 PowerShell 运行第二条命令，并确保系统提供 `curl.exe` 和 `tar.exe`。Windows 11 ARM 使用 x64 兼容环境。

终端会分六步显示进度，依次是检查本机、选择网络、下载源码、准备运行环境、安装依赖并构建、启动工作台。下载时可看已收字节和速率。向导会启动本地服务，等健康检查通过并注册 `chives` 命令后，再显示 **100%**。

## 日常启停

安装完成后，**新开一个终端**。在 Windows Terminal 中，请退出应用后重新打开，让新的终端进程读取用户 PATH。

| 在终端输入 | 结果 |
| --- | --- |
| `chives` | 在默认浏览器打开工作台。服务已停止时会先启动，等就绪后再打开页面 |
| 再次输入 `chives` | 复用正在运行且健康的服务，重新打开页面 |
| `chives stop` | 关闭本机的 Chives 服务。下次输入 `chives` 可再次启动 |

工作台地址为 [http://127.0.0.1:8888/](http://127.0.0.1:8888/)。在没有图形浏览器的 Linux 或 WSL2 环境中，可手动在能访问该端口的浏览器里打开。

## 第一次使用

在模型设置中添加自己的连接，填写供应商的地址、协议、模型 ID 和密钥。验证连接并设为默认后，打开「投资专家」，选一家熟悉的公司试问。 [模型设置](http://127.0.0.1:8888/#/settings?tab=models) · [投资专家](http://127.0.0.1:8888/#/bot/expert)

> 请核对这家公司最近一期已披露的合并报表。列出报告期、归母净利润和经营活动现金流量净额，给出公告链接、页码和数据单位。找不到的项目请注明。

收到回答后，点开公告核对数字。如果能聊天但查不到数据，可分别检查 Bot 的工具授权和数据源连接。 [设置中心](docs/设置中心.md) · [投研工具](docs/投研工具.md)

## 代理与依赖

向导用实际的 GitHub HTTPS 请求探测环境变量、系统代理和常见本机代理端口。找到可用代理后，后续下载沿用该代理；没有可用代理时走直连。**若第一行命令本身就下载失败**，此时向导还没启动，需要先让终端能访问 `raw.githubusercontent.com`。Unix 的 curl 可读取 `HTTPS_PROXY`，Windows PowerShell 可使用系统代理。

| 组件 | 向导如何准备 |
| --- | --- |
| Python 3.12 | 先检查现有解释器的版本、架构、`venv` 和 `ensurepip`。缺少兼容环境时，从 Astral 下载可迁移的 CPython，并校验 SHA-256 |
| Node.js 26、npm 和 npx | 优先复用能运行的本机工具。缺少 Node.js 时从 Node.js 官网下载并校验；只有 npm 缺失时可单独补齐 |
| pnpm、DSH 和应用依赖 | 按仓库指定的版本复用或从 npm 下载，按锁文件构建工作台。Python 依赖从 PyPI 装入当前版本的专用虚拟环境 |
| Playwright 和 Chromium | 从 PyPI 取得 Playwright，检查已有 Chromium 是否匹配且能启动。缺少时由 Playwright 官方下载器安装。Linux 缺少浏览器动态库时可能提示输入 sudo 密码 |

安装入口和各步实现可在仓库查看。 [Bash](deploy/installer.sh) · [PowerShell](deploy/installer.ps1) · [安装机制](deploy/installer/README.md)

## 安装位置与排错

新安装的根目录为 macOS、Linux、WSL2 下的 `$HOME/.chives` 或 Windows 下的 `$HOME\.chives`。其中 `releases/` 存放本机从源码构建的版本，`tools/` 存放补装的工具，`data/` 存放用户数据。

- **提示已有源码检出。** 以前用 `git clone` 安装过的用户，请按下方 macOS 手动安装说明更新已有仓库。要另选目录试装，可在运行向导前把 `CHIVES_INSTALL_HOME` 设成独立的绝对路径。两套安装使用相同服务端口，切换前先停止正在运行的一套。
- **以前用过旧版安装向导。** 默认根目录尚不存在、旧目录含 `releases/` 时，向导会沿用 Unix 下的 `~/.chives-install` 或 Windows 下的 `%LOCALAPPDATA%\Chives`。第一步会打印实际使用的目录。
- **新终端找不到命令。** macOS、Linux 和 WSL2 检查 `~/.local/bin/chives` 及终端的 PATH；Windows 检查安装根目录的 `bin\chives.cmd` 和当前用户的 PATH。
- **构建失败或服务启动超时。** 先看终端标出的步骤。依赖和构建输出在安装根目录的 `logs/install.log`，服务启动日志在 `logs/supervisor.log` 及同目录的组件日志中。工作台使用 8888 端口，API 使用 8880，启动时这两个端口及后台组件端口均须空闲。

## 更新与备份

**用一行命令安装的用户**，更新时重新运行本页开头对应平台的命令。向导下载最新源码快照，相同版本复用已构建环境，新版本在独立目录构建后切换。程序版本共用同一安装根目录的 `data/`。

更新或迁移前，可以在「设置 → 备份及导入」导出个人配置。需要完整备份时，先运行 `chives stop`，再复制整个 `data/` 目录，并妥善保管其中的凭据。恢复时先准备相应版本的程序，在停服状态下恢复数据，然后运行 `chives`，检查模型连接并打开一条旧会话。 [设置中心](docs/设置中心.md)

旧版源码安装如果曾直接启动服务，数据可能位于安装目录中的第二层 `.chives/`。迁移前先停服并备份。若只有旧库，将旧目录的内容整体迁至 `data/`，包含 SQLite 数据库及同名的 WAL、SHM 文件。若 `data/` 已有业务文件，先核对重名文件和两处会话、画像、持仓及计划，保留当前有效记录，避免用旧库覆盖新库。确认启动后能读到原记录，再移除旧目录。

## macOS 开发者手动安装

需要直接修改代码时，可在 macOS 图形登录会话中维护 Git 检出。准备 Git、Node.js 26（含 npm 和 npx）、pnpm 10.33.0 和 uv。需要读取有文字层的 PDF 公告时，可另装 Poppler 的 `pdftotext`。请确保 launchd 能从其搜索路径找到 Node.js 和包管理器。 [启动脚本](scripts/serve-chives.sh)

首次安装时选择尚未使用的目录。以下示例使用 `~/.chives`。

```sh
git clone https://github.com/xionglaoshi/chives.git "$HOME/.chives"
cd "$HOME/.chives"
bash scripts/install-chives.sh
```

手动安装的浏览器脚本默认尝试 `http://127.0.0.1:7897`。若使用其他代理，请先设置 `HTTPS_PROXY`；若可直连，请将最后一行换成 `NO_PROXY='*' no_proxy='*' bash scripts/install-chives.sh`。安装后新开终端运行 `chives`。要在仓库内查看服务状态，运行 `./start status`；启动超时先查看 `runtime/workbench.log`。若本机已有 `~/Library/LaunchAgents/local.chives.workbench.plist`，请核对它指向当前检出。

**更新已有 Git 检出**时，先进入仓库运行 `git status --short --branch`，确认在 `main` 分支并保存好自己的改动，再执行以下命令。

```sh
chives stop
git pull --ff-only origin main
bash scripts/install-chives.sh
```

重新打开终端，输入 `chives`。如果只需重新注册已有检出的命令，可在仓库根目录执行 `"$HOME/.agents/venvs/chives/bin/python" scripts/chives_cli.py source --register`。
