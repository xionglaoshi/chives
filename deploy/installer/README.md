# Chives 终端安装维护

[README 的一行命令](../../README.md#快速安装)分别进入 [Bash](../installer.sh) 和 [PowerShell](../installer.ps1)。两者从本仓库 main 的 codeload 地址取得一次源码快照，从中读取对应版本的 [源码安装程序](source.py) 和[公共运行助手](install.py)。安装无需安装码或维护者预生成附件。项目文档和平台要求见 [INSTALL.md](../../INSTALL.md#github-快速安装)。

入口负责代理探测、下载进度、CPython 探测和缺失时的下载校验。源码安装程序检查 Node.js 和 npm，按项目指定版本取得 pnpm、DSH 和 Playwright，用 PyPI 配置独立虚拟环境，用 pnpm 锁文件构建工作台。源码快照标识用于识别已构建版本，用户数据位于独立的 data 目录。工作台命令与服务健康检查共用现有的本地运行逻辑。

更新依赖版本时，同步维护源码包的包管理器版本、config/dsh-version、Python/Node 平台对应的归档和摘要。Node 包来自 [Node.js 官方分发](https://nodejs.org/dist/)，缺少 Python 时采用 [Astral 可迁移 CPython 构建](https://github.com/astral-sh/python-build-standalone)。Python 库使用 [PyPI](https://pypi.org/)，Node 库使用 [npm registry](https://registry.npmjs.org/)，Chromium 使用 [Playwright 浏览器下载器](https://playwright.dev/python/docs/browsers)。

## 历史离线包工具

build_release.py、check_release.py、channel 和手动 Actions 工作流属于早期的加密离线包方案。README 的快速安装入口直接使用仓库源码。旧服务器相关文件保留供历史部署维护。
