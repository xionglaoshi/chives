# 老韭菜公网工作台

[公网工作台](https://150.158.11.154/chives/)验证访问密码后加载 Mac 上的工作台前端和业务接口。[Mac 本地工作台](http://127.0.0.1:8888/)直接访问。两端使用同一份前端源码与本机业务数据。公网支持从设置退出登录。

| 位置 | 职责 |
|---|---|
| 腾讯云 Caddy | 对 `/chives` 和 `/chives/*` 做 HTTPS 反代 |
| 腾讯云 `chives-workbench-link.service` | 经 SSH 中继 22022，将 Caddy 可用的 `/run/chives-workbench/entry.sock` 转发到 Mac 回环 25829 |
| Mac `local.chives.public-entry` | 密码验证、会话、登录及离线页面、静态资源、业务接口转发 |
| Mac `local.chives.public-build` | 每 30 秒检查前端输入。变化后构建 `/chives/` 版本，先发布资源，再原子切换 HTML |
| Mac `local.chives.public-market` | 登录时及本地时间 16:30、20:30 刷新沪深 300 收盘快照 |
| Mac `local.chives.workbench` | 在 8888 提供本机工作台，业务接口由本机代理转至 8880 |

公网依赖 Mac 开机、联网、解锁并登录。Mac 网关仍可达时，业务服务停机显示工作台离线页。Mac 或隧道不可达时，公网连登录页也无法加载。

## 恢复与验收

1. Mac 按项目 README 恢复依赖、同一前端源码及本机资料。将密码校验文件恢复到 `~/.agents/credentials/chives-public-entry.json`，权限设为 600。重新设密码时运行 `~/.agents/venv/bin/python3 scripts/public-password.py`，再执行 `launchctl kickstart -k gui/$(id -u)/local.chives.public-entry`。网关重启后会话需重新登录。
2. 执行 `~/.agents/venv/bin/python3 scripts/install-public-jobs.py`。可立即运行 `scripts/build-public.sh` 启动一次本地构建。公网构建和网关日志在 `runtime/local.chives.public-*.log`。沪深 300 在 `public-data/mechanical-cache/market/login-chart/csi300.json`，未迁移的安装沿用 `data/market/login-chart/csi300.json`，双源不可用或冲突时沿用已有快照。旧的云端登录和行情服务模板供历史追溯。
3. 服务器恢复 SSH 中继和主机指纹，安装本目录 `chives-workbench-link.service`，执行 `systemctl daemon-reload` 和 `systemctl enable --now chives-workbench-link.service`。将 `chives.caddy` 装入 `/etc/caddy/`，保留主站配置的 import 与 HTTP 跳转。执行 `caddy validate --config /etc/caddy/Caddyfile` 后 reload。
4. 公网检查登录页、行情和匿名 API 的 401。用有效密码登录后核对工作台、Bot 列表及静态资源，退出后复验 401。Mac 和腾讯云的独立安装分发服务对应 `/chives-install/`。

2026-11-20 已核对公网登录页 200、行情与 Mac 快照 SHA-256 一致、匿名 API 与工作台资源 401。用临时密码在 Mac 隔离端口验证登录、退出、全部新版构建资源及 Bot API 与本机 8888 一致。公网浏览器正式密码登录待用户复核。

## 自动恢复

Mac 现有系统级 autossh 中继和腾讯云 Chives 专用转发断线自重连。用户登录后，工作台与认证网关由 launchd 保活。工作台健康任务每 30 秒探测本机页面和业务 API，连续三次失败会向工作台 LaunchAgent 发 TERM，清理子进程后由 launchd 重启。冷启动需先解锁 FileVault 并登录；锁屏可保留登录会话，Mac 须保持联网且未睡眠。已实测终止腾讯云专用转发进程后约 12 秒自动恢复，公网行情文件与 Mac SHA-256 一致，匿名 API 返回 401。工作台连续失败重启规则已隔离测试，未实际重启或锁屏 Mac。

登录后的个人设置、画像、持仓和备份读取 Mac 上的同一份资料。网关保留设置请求和上传需要的请求头，并将验证过的公网来源转换为本机工作台的来源。未登录请求返回 401，跨站修改和内部接口继续拒绝。重启网关会结束原公网会话。

登录后可使用持仓表单的证券名录和内核更新入口。名录由 Mac 提供，支持 gzip，只有有效公网会话可下载。登录后全部 27 张投资人物头像从 Mac 原样读取。浏览器发起的 Finder 操作由 Mac 主机执行。

## 特色数据分类发布

试点的匿名只读路径为 `/chives-features/`，服务器数据在 `/srv/chives-features/`。路由独立于公网工作台。实际路由模板见 [chives-features.caddy](chives-features.caddy)，仅允许 GET 和 HEAD，目录浏览关闭。

开发工作区生成的发布包包含分类文件及 `catalog.json`。先在服务器非公开目录核对各文件的 SHA-256，再更新 `rankings/`、`stocks/` 等分类文件，最后原子替换公开目录内的 `catalog.json`。旧版 `manifest.json` 和摘要命名快照仅供现有旧客户端读取。新客户端使用分类清单。

2026-11-24 分类切换备份在服务器 `/root/chives-features-v2.BIR9sB/`，`route.before` 为切换前路由。需要回滚时先恢复这一份特色数据路由，验证 Caddy 配置再 reload。备份及此前的公开版本继续保留。已比对 11 个公开文件的 SHA-256 和本机下载内容。付费账号的正式入口另行部署。
