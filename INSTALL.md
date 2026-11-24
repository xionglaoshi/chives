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
| `chives` | 启动或复用本地服务，在浏览器直接打开「动态看板」 |
| `chives cli` | 启动或复用本地服务，进入终端三栏快速启动台 |
| `chives web` | 启动或复用服务，在默认浏览器打开「动态看板」 |
| 设置 → 更多设置 | 查看服务日志，或选择「停止本地服务并退出」 |

### 终端对话

Tab 或左右键切换「选 Bot」「工作台」「设置」，上下键选择，回车打开。窄终端逐栏显示。背景和正文跟随终端主题，品牌强调和涨跌取色于终端自己的红绿调色板。

- **选 Bot**仅展示已聘用成员。打开栏底「聘用管理」，上下键移动，空格勾选或取消，回车一次保存，Esc 放弃。网页「Bot市场」共用这份名单。总调度（`operator`）是唯一常驻成员。常规提问默认交给总调度。工作台「问AI」打开总调度对话并填好问题和附件，可以先编辑再发送。「问AI」直接填入该按钮的预设问题。Bot 对话输入框空闲 30 秒后可生成灰色追问建议，按 Tab 或点「使用建议」即可纳入编辑。新成员由系统部署，默认待聘。解聘后历史对话可查看，重新聘用后可继续。
- **热门榜单**在启动台直接列出已发布的各张榜。回车查看排名、证券和两列指标。表格按终端字符宽度对齐，窄屏按条目分行。红色表示上涨或盈利，绿色表示下跌或亏损，正负号可在单色终端辨认。
- **行情看板**回车先看大盘，左右键切换市场宽度、外围市场、行业、个股榜、两组资讯和持仓贡献。**用户持仓**先显示账本，再补行情估值。**风格评估**展示本人的综合解读、匹配投资人的文字和风格卡。上下键或 PgUp/PgDn 翻阅，Esc 返回原位置。网页入口为 `chives web`。
- **设置**首屏可选默认模型，直接开关紧凑排版、思考摘要及工具记录。**更多设置**平铺高对比、时间戳、模型连接、各通讯频道及服务操作。编辑表单时用 Tab 换字段，左右键切换选项，移到「保存」按回车，或按 Ctrl+S。涉及扫码和浏览器授权的项目带有网页标记。

输入 `/` 浏览命令，例如 `/model` 切换当前 Bot 的模型，`/history` 查找并续接研究，`/new` 另开研究，`/files` 查看交付，`/stop` 停止当前任务。模型和频道配置与网页共用，终端外观单独保存。脚本可通过管道提问，例如 `printf '%s\n' '梳理持仓风险' | chives`。

工作台地址为 [http://127.0.0.1:8888/](http://127.0.0.1:8888/)。在没有图形浏览器的 Linux 或 WSL2 环境中，可手动在能访问该端口的浏览器里打开。

## 第一次使用

全新用户安装首次打开工作台时，Dock 左端会显示「请先完成初始化」。点击后可逐项打开对应入口。八项均完成时，入口自动收起。

| 待办项 | 完成条件 |
| --- | --- |
| 添加模型 | 填写 API 地址和 API Key，选择协议，点击「验证并保存」。Chives 自动发现并启用通过验证的模型。也可以在同一窗口手动指定模型 ID。 |
| 完成用户画像评测问卷 | 回答并提交问卷，等正式画像生成。 |
| 填写用户基本信息 | 在用户资料中上传头像，填写姓名、邮箱、电话并保存。 |
| 添加持仓股票 | 至少保存一条持仓。 |
| 添加关注股票 | 至少保存一只关注股票。 |
| 连接微信 | 扫码授权后，从绑定微信向 Chives 发一段文字，收到欢迎消息。 |
| 创建盯盘任务 | 在总调度会话中回答希望监控的股票和条件，等任务创建并启用。 |
| 创建每日投研简报任务 | 从总调度会话打开简报确认，填写追加事项或明确回复「没有」。确认后创建周一至周五北京时间 09:00 执行的任务。 |

模型启用后，可以打开「总调度」选一家熟悉的公司试问。收到回答后，点开公告核对数字。若能聊天但查不到数据，可检查 Bot 的工具授权和数据源连接。 [设置中心](docs/设置中心.md) · [投研工具](docs/投研工具.md)

> 请核对这家公司最近一期已披露的合并报表。列出报告期、归母净利润和经营活动现金流量净额，给出公告链接、页码和数据单位。找不到的项目请注明。

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

### 安装根目录分工

| 目录 | 用途 |
| --- | --- |
| `user-data/` | 本机用户状态。数据库 `chives.sqlite` 保存会话、任务及设置等结构化状态。用户画像、参数和持仓在 `profile/`，关注在 `user/`，Bot 档案和记忆在 `bots/`，模型与频道凭证在 `secrets/`，模型运行状态在 `dsh/`、`harness/`，盯盘引擎的规则、计划和告警在 `watch-engine/`，Hub 的个人设置与处理状态在 `hub/`。 |
| `workspace/` | Agent 和 Bot 的任务工作区。Bot 的输入、任务产物和交付文件保存于 `workspace/bots/<Bot ID>/`。这些文件也属于用户数据。 |
| `public-data/mechanical-cache/` | 第三方机械数据缓存。行情和日线在 `marketdata/`，资讯、市场监控缓存和公开图表快照在 `market/`。 |
| `public-data/chives-cache/` | 每次启动即从发布源拉取完整特色数据快照，并在后台检查更新，包含机会榜单、合理股价和后市判断。 |
| `runtime/` | 日志、进程信息、浏览器、专用 Python、下载缓存和临时目录，也保存迁移批次与可回滚副本。 |
| `credentials/` | 开发机本地发行凭证，独立于用户模型和频道凭证。 |
| `data/` | 迁移前的旧混合目录。已迁移的本机保留它作回滚，日常读写使用分层后的目录。 |
| `apps/`、`packages/` | Web、服务端及各工具包源码。 |
| `bots/`、`skills/`、`presets/`、`config/` | 随应用分发的 Bot 定义、技能、预设及公共配置。 |
| `gateways/`、`overlays/`、`patches/` | 数据网关配置、内核工具接入配置和兼容补丁。 |
| `deploy/`、`scripts/`、`docs/` | 安装、发布、运维程序及文档。 |
| `.git/`、`.github/` | 版本库和 CI 工作流。 |
| `.venv/`、`node_modules/`、`.pnpm-store/` | 专用 Python 环境、Node.js 依赖及 pnpm 缓存。 |
| `.pytest_cache/`、`.ruff_cache/` | 开发工具缓存。 |

### 数据目录迁移预检

发行版升级时，安装器在停服后迁移旧版本的盯盘状态、Hub 数据库和市场监控缓存。前两者进入 `user-data/`，市场监控进入 `public-data/mechanical-cache/market/`。已有目标文件优先保留，旧版本副本可供回滚。来源不明确时，旧副本留待人工核对。

新安装的用户状态和日线缓存分别使用安装根内的 `user-data/` 和 `public-data/mechanical-cache/`。已有 `data/` 的安装在迁移前继续读取旧目录。清空用户数据时，`public-data/` 下两类公共数据均保留。资讯等机械数据按各自更新频率拉取。

`python3 scripts/stage-data-migration.py` 默认只统计旧目录的拟迁移条目。隔离演练可加 `--root <测试安装根> --stage`。正式存量的暂存应在数据写入停止后运行。暂存批次位于安装根的 `runtime/`，包含 SQLite 一致快照、校验摘要和迁移清单。未确认归属的内容保存在该批次的 `review/`。暂存步骤保留原件。历史交付若在旧路径缺失，可通过可重复的 `--workspace-backup <备份中的 bots 目录>` 提供已核实的备份。恢复按 Bot 和完整相对路径匹配，多个副本的内容须一致。会话与内核的旧工作区路径在暂存副本中更新，`verification.json` 汇总改写数量及历史交付文件能否从新路径读回。停服后可用同一命令加 `--activate runtime/data-migration-…` 启用已校验且目的目录为空的批次。确认所有数据读取入口已经接入分类目录后再用于正式安装。停服后使用 `--rollback runtime/data-migration-…` 可恢复旧路径，切换后产生的新数据保存在批次中，供人工核对后合并。


**用一行命令安装的用户**，更新时重新运行本页开头对应平台的命令。向导下载最新源码快照，相同版本复用已构建环境，新版本在独立目录构建后切换。程序版本共用同一安装根目录的 `data/`。

更新或迁移前，可以在「设置 → 备份及导入」导出个人配置。需要完整备份时，先在终端选「设置 → 更多设置 → 停止本地服务并退出」，再复制整个 `data/` 目录，并妥善保管其中的凭据。恢复时先准备相应版本的程序，在停服状态下恢复数据，然后运行 `chives`，检查模型连接并打开一条旧会话。 [设置中心](docs/设置中心.md)

共享用户档案在 `data/user/`。可直接打开 `user-index.md`、`attributes/values.json` 和 `reviews/待确认属性.md` 检查概况、现值和缺项。属性定义在 `presets/user-attributes/`，每个文件定义一个属性。源码安装会自动初始化目录，已有安装也可以在仓库根目录执行以下命令。初始化保留已经登记的属性和手工 Wiki 页，新增键从未知开始。

```sh
python3 scripts/user_archive.py init
python3 scripts/user_archive.py reindex
```

用户授权的临时代填会在中文赋值对照里逐项标出。Bot 查询时通过 `provisionalValue` 查看示例，`value` 继续表示可采用的个人属性。新版问卷提交有效值后，档案服务按现值校验并替换对应的临时代填。

用户库以 `data/user/` 和 `data/user-archive-state/` 一起备份和恢复，问卷原件、旧持仓、原消息另随 `data/` 全量备份。设置页的个人配置导出只覆盖它所列的旧版资料。恢复时使用相同版本的属性定义，停服恢复整份备份，重新运行初始化和索引命令，再读回一条带出处的记录。档案管理员通过本机 `python3 scripts/user_archive.py apply` 从标准输入接收带来源的赋值单。普通 Bot 用 `read_user_attributes`、`find_user_memory` 查询，凭本人原句用 `propose_user_attribute` 提案。独立模型审证后，本人明确说明的长期方法偏好可按版本和取值规则自动合并。风险、仓位与行为统计等项目保留给管理员按原始依据复核。任务复盘和三小时摘要由工作台在后台运行；停机期间进度保存在本机。[用户记忆写入规则](docs/user-wiki-rules.md)

旧版源码安装如果曾直接启动服务，数据可能位于安装目录中的第二层 `.chives/`。迁移前先停服并备份。若只有旧库，将旧目录的内容整体迁至 `data/`，包含 SQLite 数据库及同名的 WAL、SHM 文件。若 `data/` 已有业务文件，先核对重名文件和两处会话、画像、持仓及计划，保留当前有效记录，避免用旧库覆盖新库。确认启动后能读到原记录，再移除旧目录。

### 恢复出厂

先在设置中停止 Chives。本机开发检出可运行 `./start stop`，等服务退出后再操作。将 `user-data/` 移出安装根并保留作备份，然后重新启动。Chives 会重建空白用户状态，并将旧 `workspace/` 转移到 `runtime/user-reset-*/workspace/`，让新会话从空白工作区开始。

保留整个 `public-data/`。缓存中的行情、资讯及已发布特色数据仍可使用和继续更新。迁移前的 `data/`、迁移批次和旧工作区恢复副本仍用于回滚，也可能包含历史用户内容。全新用户安装会重新显示八项初始化，开发和测试环境依照环境设置隐藏入口。

## 卸载

在 Windows PowerShell、macOS、Linux 或 WSL2 的交互终端运行以下命令。旧版若在 `chives --help` 中看不到卸载入口，请先按[更新说明](#更新与备份)升级。

```sh
chives uninstall
```

确认窗口列出实际安装目录。要保留档案，请先将备份放在安装目录以外。输入完整的小写 `yes` 并回车后，Chives 会停止本机服务，移除终端入口及其注册设置，并永久删除程序、所有本地版本、专用依赖、用户库、持仓、Bot、对话、已保存的模型凭证和日志。直接回车、输入其他文字或按 Ctrl+C 都会取消。管道输入无法确认卸载。

向导清理当前用户的这套安装。系统共用的 Python、Node.js 和浏览器仍可供其他程序使用。独立部署的公网反向代理由该网关的管理员维护。Windows 上请先离开安装目录，卸载后重新打开终端即可读取最新 PATH。

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
./start stop
git pull --ff-only origin main
bash scripts/install-chives.sh
```

重新打开终端，输入 `chives`。如果只需重新注册已有检出的命令，可在仓库根目录执行 `"$HOME/.chives/.venv/bin/python" scripts/chives_cli.py source --register`。

「问AI」的预设集中在 [config/ask-ai-prompts.json](config/ask-ai-prompts.json)。每张榜单、卡片与报告段落有自己的条目，金额显示等分支也可分别修改。保留需要的双花括号变量，例如 `{{榜单名}}`，修改后刷新本机开发网页或重建静态网页使之生效。

Git 检出的本机启动脚本默认使用开发环境。独立测试实例可设置 `CHIVES_ENVIRONMENT=test`。两种环境的 Dock 均按初始化已完成处理，用户安装版仍按八项实际完成状态显示引导。

### 开发与发布验收

Chives 开发测试统一使用 GitHub Actions 的临时虚拟机，验收环境固定为 `linux-x64`、`windows-x64`、`macos-arm64`。本次数据分层与发布改造也采用这三个环境。跨平台源码安装、空白初始化与恢复出厂由 [源码安装工作流](.github/workflows/source-install.yml) 验证。填写验收记录时附上工作流链接和提交号。

### 特色数据发布试点

Codex 在股票 AGENT 工作区下生产特色数据。以 `/Users/xiong/.agents/workspace/股票AGENT/Chives特色数据/` 为例：

1. 原件放在 `production/`。生成榜单时向 `scripts/hotspots/generate.py` 传入 `--data "$production/hotspots"`。生成待发布估值时，在生产进程中将 `CHIVES_RESEARCH_LIBRARY` 设为 `"$production/equity-research"`。
2. 从 Chives 源码目录用 `apps/server/node_modules/.bin/tsx scripts/build-feature-publication.ts` 导出。传入 `--source "$production"`、`--output "$publication"` 和估值日期 `--day YYYY-MM-DD`。两条路径均位于股票 AGENT 工作区内。用可重复的 `--board` 和 `--code` 明确指定本次准予公开的榜单和证券。发布包只包含 SHA-256 文件名的快照以及 `manifest.json`。
3. 核对发布包所含范围。先上传快照，再更新服务器的 `manifest.json`，最后在 Chives 点击「刷新榜单」查看已发布结果。应用内缓存位于 `public-data/chives-cache/snapshot.json`。

发行版安装器默认设置 `CHIVES_FEATURE_DATA_URL=https://150.158.11.154/chives-features/`。包括首次安装在内，每次启动都会立即在后台拉取发布清单和本次发布的完整快照，随后每分钟检查发布摘要，有新版本或本机缓存缺失时重新下载。缓存位于 `public-data/chives-cache/`，刷新失败时保留上次通过验证的版本。开发、测试和用户安装的机会榜单、关注和持仓均读取该缓存。服务器没有发布的估值或榜单显示为缺失。
