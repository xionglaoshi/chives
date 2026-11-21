# GitHub 安装包分发维护

用户从 [Bash](../installer.sh) 或 [PowerShell](../installer.ps1) 进入。两者读取 main 的 [channel](channel)，按固定标签访问本仓库 GitHub Release。旧的三个入口转到同一向导。首次取得脚本由用户终端负责，之后的下载共用已验证的代理或直连。源码检出和分发安装的目录说明见 [INSTALL.md](../../INSTALL.md#github-快速安装)。

## 制作一次发行

1. 在准备发布的提交中给 `deploy/installer/channel` 填入新标签，如 `installer-2026.11.22.1`。每个标签唯一，先在发布分支准备提交和程序，再在测试通过、附件公开后将同一清单并入 main。首次发布需要先让工作流文件在默认分支上可用。
2. 在 GitHub Actions Secrets 中配置 `CHIVES_INSTALL_CODE`，使用随机生成的长安装码，通过已有私下渠道提供给授权用户。GitHub 上的源码公开，安装码保护便捷分发的程序包。离线验证支持按新版本轮换安装码，已下载的旧包仍可用其原安装码解开。
3. 在指定发布分支手工运行 [Build GitHub installer](../../.github/workflows/installer.yml)。维护者构建阶段从上游取得 Node、Python、npm 包、Python wheels 和 Chromium，将各平台运行所需文件随 Release 分发。打包机使用 Git 受控的程序文件，在隔离目录构建；生产数据、凭据和本机缓存均留在原处。GitHub Actions 的原生构建机覆盖 macOS 和 Linux 的 x64/ARM64，以及 Windows x64。[GitHub 托管运行器规格](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
4. 各平台打包成功后，以同一提交创建 Release。维护者可勾选工作流的试装选项，在发布前使用随包解释器、Node 和离线组件检查本地服务及重复安装。默认由使用者自行试装。Windows ARM 使用 x64 兼容环境；WSL2 使用相应的 Linux 包。两者另需实机验收。每个附件配有 SHA-256 和字节数，发布中断时先检查 Release 和附件再重试。
5. 发布后在干净机器分别按 README 验收终端入口、安装码、代理、CLI、工作台和首次 Bot 回复。将 main 的 channel 设为 `disabled` 可暂停向导的新安装；切回已发布的标签可回退分发。修改入口、校验逻辑或包格式时，对应脚本与发行包应一并验收。

## 发行内容

| 平台附件 | 用途 |
| --- | --- |
| `bootstrap-平台.tar.gz` | 安装引擎、离线解密模块 |
| `python-平台.tar.gz` | 无兼容 Python 时使用的可迁移 CPython 3.12 |
| `node-平台.tar.gz` | 无兼容 Node.js/npm 时使用的 Node.js 26 和 npm/npx |
| `browser-平台.tar.gz` | 本机缺少匹配修订时使用的 Chromium、FFmpeg 和适用的 Linux 浏览器动态库 |
| `chives-平台.zip` | AES 加密的程序、DSH 缓存、离线 pnpm 仓库、Python wheels、Playwright 和工作台构建产物 |

客户端只向 GitHub 请求入口、channel、附件和校验文件。业务运行时访问用户配置的模型和行情服务。目录内的 server.py、mirror.py 及其服务配置保留供历史部署恢复；GitHub 向导的构建、校验、授权和启动均独立运行。
