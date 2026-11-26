# Chives 终端安装维护

[README 的一行命令](../../README.md#快速安装)分别进入 [Bash](../installer.sh) 和 [PowerShell](../installer.ps1)。两者从本仓库 main 的 codeload 地址取得一次源码快照，从中读取对应版本的 [源码安装程序](source.py) 和[公共运行助手](install.py)。安装无需安装码或维护者预生成附件。项目文档和平台要求见 [INSTALL.md](../../INSTALL.md#github-快速安装)。

Windows 一行命令的入口只含 ASCII 字节。它按 UTF-8 读取实际的 [PowerShell 向导](windows.ps1)，移除开头的 BOM 后执行，兼容 Windows PowerShell 5.1 的 `iex (irm …)`。在本地检出中直接运行入口时复用随仓向导。

入口负责代理探测、下载进度、CPython 探测和缺失时的下载校验。源码安装程序检查 Node.js 和 npm，按项目指定版本取得 pnpm、DSH 和 Playwright，用 PyPI 配置独立虚拟环境，用 pnpm 锁文件构建工作台。源码快照标识用于识别已构建版本，用户数据位于独立的 data 目录。工作台命令与服务健康检查共用现有的本地运行逻辑。

更新依赖版本时，同步维护源码包的包管理器版本、config/dsh-version、Python/Node 平台对应的归档和摘要。Node 包来自 [Node.js 官方分发](https://nodejs.org/dist/)，缺少 Python 时采用 [Astral 可迁移 CPython 构建](https://github.com/astral-sh/python-build-standalone)。Python 库使用 [PyPI](https://pypi.org/)，Node 库使用 [npm registry](https://registry.npmjs.org/)，Chromium 使用 [Playwright 浏览器下载器](https://playwright.dev/python/docs/browsers)。

## 终端卸载

三端共用 [交互确认和清理逻辑](../../scripts/chives_uninstall.py)。Windows 的 [命令入口](../../scripts/chives_cli.py) 等待专用 Python 退出后再移除程序树。验收时应从新终端核对命令、用户数据、服务端口、PATH 和安装目录，并确认安装目录内的符号链接或 Windows 目录联接指向的外部文件仍可读取。[用户操作](../../INSTALL.md#卸载)

## 历史离线包工具

build_release.py、check_release.py、channel 和手动 Actions 工作流属于早期的加密离线包方案。README 的快速安装入口直接使用仓库源码。旧服务器相关文件保留供历史部署维护。

## 后台服务守护

发行安装启动后，运行助手约每 30 秒检查主服务、网页、数据站、策略台、雷达、罗盘和信号枢纽。进程退出会在下一次巡检时拉起。进程仍在但健康接口连续三次失败时，仅重启该组件。进程退出码和重启记录写在安装根目录的 `logs/<组件>.log`。

本机源码工作台由 `local.chives.workbench-watchdog` 每 30 秒检查。五个引擎连续三次健康检查失败时，巡检调用 `scripts/chives.sh recover-engine <组件>` 按组件恢复。主服务或网页连续三次失败时，由 launchd 重启工作台。巡检日志在 `runtime/local.chives.workbench-watchdog.log`。

### 运行环境和系统服务

「设置 → 内核设置 → 运行环境」按系统、引擎、Bot 的顺序展示运行状态。系统诊断、数据同步及更新检查各由常驻子进程调度，通过 IPC 复用核心的数据缓存、配置和通知库。异常退出后由核心重新拉起。Mac 的 launchd 守护仍负责监测及恢复引擎，诊断进程同时检查巡检心跳。

- 健康守护约每 5 分钟检查引擎、用户目录读写、可用空间、关注文件和 SQLite 完整性，异常写入工作台通知。
- 数据同步约每分钟刷新动态看板、机会榜单、持仓、关注和资讯。盘中额外刷新主要排行和关注报价。数据时效取决于行情源、资讯抓取冷却和榜单发布频率。
- 更新服务约每 30 分钟检查 GitHub 与 npm 的 dsh 发布版本。发现可用版本时生成工作台提醒，从「升级更新」手动安装。

查看 `GET /api/settings/runtime` 可核对三类状态。Bot 的职责说明来自名册的 `role` 字段，未聘用的名册成员显示「未激活」。

### 任务管理

「设置 → 任务管理」汇总所有 Bot 的定时任务和盯盘。每条任务可独立暂停、恢复、编辑和删除。盯盘暂停时从雷达撤下计划，恢复时重新下发。编辑内置定时任务或删除它会保存本机覆盖，避免名册同步覆盖人工结果。未聘用 Bot 的遗留任务可编辑或删除，聘用后才能启用。全局观察模式位于「设置 → 权限设置」。

巡检可通过本机 `GET /api/settings/tasks` 核对实际任务名称、条件和开关。历史盯盘继续在原盯盘入口查询。

### Bot 市场人像库

Bot 市场资料卡可按 Bot 独立更换人像，选择保存在本地设置。图片和目录位于 `apps/web/public/bot-portraits/`，使用同名 WebP 和 `catalog.json` 中的 ID。目录共 67 张，40 张虚构人物和 27 张投资人胸像。更新素材后运行网页构建，核对桌面和窄屏选图以及保存后重新打开卡片。
