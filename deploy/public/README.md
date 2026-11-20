# 老韭菜公网测试入口

[进入公网工作台](https://150.158.11.154/chives/)后输入访问密码。拥有密码的人共用同一套 Bot、研究记录和操作权限。设置页可以退出登录。Mac 也可以直接打开[本地工作台](http://127.0.0.1:8888/)。

登录后默认打开总经理。侧栏搜索和点将台排序通过现有鉴权通道访问 Mac，三个工作台入口预留给后续开发。

## 登录与工作台

腾讯云提供登录页、密码验证、会话、Logo、样式和沪深 300 走势。登录后，网关最多用三秒检查 Mac 工作台的 `/api/health`。在线时进入工作台，可读取 Bot、对话及事件流。Mac 关机、睡眠、服务停止或专用隧道中断时，正确密码会打开“工作台暂时离线”页，继续显示行情。离线页在前台每隔约 5 秒检查工作台，切回标签页或浏览器恢复联网时立即检查。工作台就绪后沿用有效会话自动进入；会话失效则回到密码页。工作台运行需要 Mac 开机解锁、登录并联网，研究数据和模型配置保存在 Mac。

| 位置 | 职责 |
|---|---|
| 腾讯云 Caddy | HTTPS 入口和行情 JSON；其余 Chives 路径发往本机回环 25829 |
| 腾讯云 chives-entry.service | `/opt/chives-entry` 内的 Node 密码门、登录与离线模板、生产版前端。systemd 将密码校验文件作为 credential 提供；会话在内存中保存 12 小时，重启密码门需要重新登录 |
| 腾讯云 chives-workbench-link.service | 通过原有 SSH 中继 22022，把权限受限的 `/run/chives-workbench/api.sock` 连到 Mac 工作台 8888 的 /api，由本地代理转发至业务服务 8880。密码门对业务请求校验会话 |
| 腾讯云 chives-market.timer | 16:30、20:30 获取指数日线，Caddy 从服务器读取 |
| Mac local.chives.workbench | 运行工作台和业务 API，登录即启动。本地直接访问 8888 |

## 更新与重建

1. Mac 按项目 README 恢复依赖及本机资料，执行 `~/.agents/venv/bin/python3 scripts/install-public-jobs.py` 加载工作台。运行 `./scripts/build-public.sh` 构建生产前端。
2. 云端安装 Node（本次 v22），创建无登录 shell 的系统用户和组 `chives-entry`。将 `scripts/public-gateway.mjs`、`scripts/public-password.py`、`deploy/public/{login.html,login-panel.html,offline-panel.html,offline-reconnect.js,chart.js,login.css}`、`apps/web/public/chives.svg` 和 `runtime/public-dist/` 按原相对位置装入 `/opt/chives-entry/`。仅发布这些网页资产和程序。前端更新时先上传版本化静态资源，最后替换 index.html。
3. 服务器 root 运行 `python3 /opt/chives-entry/scripts/public-password.py` 设置或轮换密码，生成 `/etc/chives-entry/entry.json`（目录 700、文件 600）。已有有效校验文件可通过受保护的 SSH 通道恢复。仓库和普通源码备份不含凭据。
4. 确认从服务器到 Mac 的原 SSH 中继、身份密钥与主机指纹可用。将本目录的 `chives-workbench-link.service`、`chives-entry.service` 放入 `/etc/systemd/system/`，执行 `systemctl daemon-reload`、`systemctl enable --now chives-workbench-link.service chives-entry.service`。修改登录模板、网关脚本或密码后重启 chives-entry.service。
5. 将 `chives.caddy` 装入 `/etc/caddy/`，保留 IP HTTPS 站点内原有的 import 和 HTTP 到 HTTPS 的路径重定向。执行 `caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile` 后 reload。云端行情任务按下节恢复。
6. 从公网无痕浏览器验证。匿名加载登录页、Logo、行情成功，业务 API 返回 401。为复验离线流程，只临时停止 chives-workbench-link.service，错误密码应拒绝，正确密码应显示“工作台暂时离线”。恢复该单元后保持离线页打开，观察它自动进入工作台，确认同一会话能读取五个 Bot 并接收事件流。本次已按该流程实测，Mac 未关机。

## 登录页行情

腾讯云的 `chives-market.timer` 按北京时间 16:30、20:30 触发。持久化定时器在服务器重新上线后会补跑错过的时段。Mac 已卸载原行情 LaunchAgent。公网 JSON 由服务器 Caddy 直接读取；登录和查看走势均可在 Mac 离线期间使用。

服务器恢复时，创建无登录权限的系统用户及同名组 `chives-market`，准备 Python 3、requests、系统时区数据库。把更新脚本放到 `/opt/chives-market/scripts/update-csi300.py`，把最近已验证的快照或包内基线放到 `/opt/chives-market/deploy/public/csi300.json`。两个 `chives-market.*` 单元装到 `/etc/systemd/system/`。执行 `systemctl daemon-reload`、`systemctl start chives-market.service`。确认 Caddy 用户能读取结果后，载入本目录的 chives.caddy，再执行 `systemctl enable --now chives-market.timer`。用 `journalctl -u chives-market.service` 查看取数记录，用 `systemctl list-timers chives-market.timer` 核对下次运行时间。

更新器从新浪和腾讯获取沪深 300 日线，选择通过校验且日期最新的来源，同日优先新浪。北京时间 16:30 前排除当日记录。按最新已收盘交易日向前滚动两年，检查覆盖范围及已发布交易日的连续性，并校验重叠收盘价（容差 0.02 点）。没有新交易日继续使用原快照；双源失败或冲突保留上次结果并记日志。有效数据原子写入服务器 `/var/lib/chives-market/csi300.json`，首次恢复时更新脚本从种子快照校验历史。打开页面即请求最新快照，已打开的可见页每 15 分钟检查一次。起止日和来源读取快照。2026-11-19 盘中首验回读 485 个交易日，截止 11-18；隔离验证覆盖备源切换、双源失败及长开页面刷新。

登录页保留统一白底，淡灰绿色代码雨缓慢下落；桌面 28 列、移动端 12 列，系统启用“减少动态效果”时隐藏代码雨。走势按交易日从左向右回放，约 20 秒走完，停留片刻后循环。鼠标悬停或键盘聚焦可暂停查价，移开后从该交易日继续。系统开启“减少动态效果”时默认显示完整走势。来源见[新浪日线](https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData?symbol=sh000300&scale=240&ma=no&datalen=520)和[腾讯日线](https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000300,day,2024-11-19,2026-11-19,640,qfq)。
